"""Shell-free command parsing and Windows executable/shim resolution.

Windows strings use Microsoft's C runtime argument rules, not cmd.exe syntax:
https://learn.microsoft.com/en-us/cpp/c-language/parsing-c-command-line-arguments
Batch files can invoke a shell even with shell=False (Python subprocess docs).
Only recognized npm cmd-shim templates are translated; arbitrary batch code is
never interpreted or passed to CreateProcess by this module.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path


def parse_command_line(
    command: str, *, windows: bool | None = None, first_arg_is_executable: bool = True
) -> list[str]:
    """Parse argv without expansion. Single quotes are literal on Windows."""
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return shlex.split(command)
    result = []
    i = 0
    if first_arg_is_executable:
        # CRT argv[0] treats backslashes literally, including just before a
        # closing quote around part of an executable path.
        while i < len(command) and command[i] in " \t":
            i += 1
        if i == len(command):
            return []
        executable: list[str] = []
        quoted = False
        while i < len(command) and (quoted or command[i] not in " \t"):
            if command[i] == '"':
                quoted = not quoted
            else:
                executable.append(command[i])
            i += 1
        result.append("".join(executable))
    while i < len(command):
        while i < len(command) and command[i] in " \t":
            i += 1
        if i == len(command):
            break
        argument: list[str] = []
        quoted = False
        while i < len(command) and (quoted or command[i] not in " \t"):
            slashes = 0
            while i < len(command) and command[i] == "\\":
                slashes += 1
                i += 1
            if i < len(command) and command[i] == '"':
                argument.append("\\" * (slashes // 2))
                if slashes % 2:
                    argument.append('"')
                elif quoted and i + 1 < len(command) and command[i + 1] == '"':
                    argument.append('"')
                    i += 1
                else:
                    quoted = not quoted
                i += 1
            else:
                argument.append("\\" * slashes)
                if i < len(command) and (quoted or command[i] not in " \t"):
                    argument.append(command[i])
                    i += 1
        # The C runtime consumes the rest of the line if a quote is unclosed.
        result.append("".join(argument))
    return result


def display_argv(args: list[str], *, windows: bool | None = None) -> str:
    """Serialize for display only; never feed this string to a shell."""
    if windows is None:
        windows = os.name == "nt"
    return subprocess.list2cmdline(args) if windows else shlex.join(args)


def validate_argv(args: list[str]) -> None:
    if not args or not isinstance(args[0], str) or not args[0]:
        raise ValueError("No command provided")
    if any(not isinstance(arg, str) or "\0" in arg for arg in args):
        raise ValueError("argv must contain strings without NUL characters")


def environment_value(env: Mapping[str, str], key: str, *, windows: bool) -> str | None:
    if not windows:
        return env.get(key)
    return next((value for name, value in env.items() if name.upper() == key.upper()), None)


def find_executable(
    name: str,
    *,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    windows: bool | None = None,
    native_only: bool = False,
) -> str | None:
    """Search the child's PATH/PATHEXT, returning an absolute launch path.

    shutil.which on Windows reads PATHEXT from the parent environment. Windows
    CreateProcess also ignores the supplied env PATH during executable lookup,
    so resolve explicitly instead of relying on either behavior.
    """
    if windows is None:
        windows = os.name == "nt"
    environment = os.environ if env is None else env
    root = Path(cwd or Path.cwd()).absolute()
    path = environment_value(environment, "PATH", windows=windows)
    if not windows:
        if os.path.dirname(name):
            candidate = Path(name)
            candidate = candidate if candidate.is_absolute() else root / candidate
            return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None
        directories = [
            str((root / entry).absolute())
            for entry in (path if path is not None else os.defpath).split(os.pathsep)
        ]
        return shutil.which(name, path=os.pathsep.join(directories))
    suffixes = (
        [".exe", ".com"]
        if native_only
        else (
            environment_value(environment, "PATHEXT", windows=True) or ".COM;.EXE;.BAT;.CMD"
        ).split(";")
    )
    suffixes = [suffix.lower() for suffix in suffixes if re.fullmatch(r"\.[A-Za-z0-9]+", suffix)]
    # Prefer native binaries to adjacent npm batch launchers.
    suffixes = sorted(dict.fromkeys(suffixes), key=lambda suffix: suffix not in {".exe", ".com"})
    candidate = Path(name)
    if candidate.suffix:
        suffixes = [""]
    if candidate.is_absolute() or "/" in name or "\\" in name:
        bases = [candidate if candidate.is_absolute() else root / candidate]
    else:
        # Deliberately do not add the parent's cwd to a supplied PATH.
        bases = [
            (root / directory.strip('"') / name).absolute()
            for directory in (path or "").split(";")
            if directory or path == ""
        ]
    for base in bases:
        for suffix in suffixes:
            executable = Path(str(base) + suffix)
            if executable.is_file():
                if native_only and executable.suffix.lower() not in {".exe", ".com"}:
                    continue
                return str(executable)
    return None


_SHIM_HEAD = """@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0"""


def _normalized_batch(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).casefold()


def _npm_shim(target: str, flags: str = "", *, legacy: bool = False) -> str:
    # Templates from npm/cmd-shim v5 and current lib/index.js. Full template
    # comparison rejects custom pre/post commands and environment assignments.
    branch = "SET PATHEXT=%PATHEXT:;.JS;=;%\n" if legacy else ""
    tail = "" if legacy else "set PATHEXT=%PATHEXT:;.JS;=;% & "
    return f"""{_SHIM_HEAD}
IF EXIST "%dp0%\\node.exe" (
SET "_prog=%dp0%\\node.exe"
) ELSE (
SET "_prog=node"
{branch})
endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & {tail}"%_prog%" {flags} "%dp0%\\{target}" %*"""


def _npm_prefix_shim(name: str) -> str:
    variable = name.upper()
    return f''':: Created by npm, please don't edit manually.
@ECHO OFF
SETLOCAL
SET "NODE_EXE=%~dp0\\node.exe"
IF NOT EXIST "%NODE_EXE%" (
SET "NODE_EXE=node"
)
SET "NPM_PREFIX_JS=%~dp0\\node_modules\\npm\\bin\\npm-prefix.js"
SET "{variable}_CLI_JS=%~dp0\\node_modules\\npm\\bin\\{name}-cli.js"
FOR /F "delims=" %%F IN ('CALL "%NODE_EXE%" "%NPM_PREFIX_JS%"') DO (
SET "NPM_PREFIX_{variable}_CLI_JS=%%F\\node_modules\\npm\\bin\\{name}-cli.js"
)
IF EXIST "%NPM_PREFIX_{variable}_CLI_JS%" (
SET "{variable}_CLI_JS=%NPM_PREFIX_{variable}_CLI_JS%"
)
"%NODE_EXE%" "%{variable}_CLI_JS%" %*'''


# Preserve npm's prefix-selected CLI (including a user's upgraded npm). argv is
# data, never interpolated into JS or cmd syntax. Both children inherit the
# invocation-owned process tree and the actual supplied environment/cwd.
_NPM_PREFIX_DISPATCH = """
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const [prefixScript, localCli, ...args] = process.argv.slice(1);
let cli = localCli;
const prefix = cp.spawnSync(process.execPath, [prefixScript], {
  encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true
});
for (const line of (prefix.stdout || '').trim().split(/\\r?\\n/)) {
  if (!line) continue;
  const candidate = path.join(line, 'node_modules', 'npm', 'bin', path.basename(localCli));
  if (fs.existsSync(candidate)) cli = candidate;
}
const child = cp.spawn(process.execPath, [cli, ...args], {stdio: 'inherit', windowsHide: true});
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', (code, signal) => { process.exitCode = code === null ? 1 : code; });
""".strip()


def _shim_target(shim: Path, target: str) -> Path:
    if not target or any(character in target for character in '%"\r\n\0'):
        raise ValueError(f"Unsupported Windows shim target in {shim.name}")
    path = shim.parent / target.replace("\\", "/")
    if not path.is_file():
        raise ValueError(f"Windows shim {shim.name} points to a missing target")
    return path.absolute()


def prepare_process_argv(
    args: list[str],
    *,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    windows: bool | None = None,
) -> list[str]:
    """Resolve Windows native executables and translate supported npm shims."""
    validate_argv(args)
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return list(args)
    found = find_executable(args[0], cwd=cwd, env=env, windows=True)
    if found is None:
        raise FileNotFoundError(f"Executable {args[0]!r} not found in the subprocess PATH/PATHEXT")
    executable = Path(found)
    if executable.suffix.lower() in {".exe", ".com"}:
        return [found, *args[1:]]
    if executable.suffix.lower() not in {".cmd", ".bat"}:
        raise ValueError(
            f"Unsupported Windows executable {executable.name}; supply a native executable or Node script argv"
        )
    text = executable.read_text(encoding="utf-8-sig")
    normalized = _normalized_batch(text)
    target = None
    node_flags: list[str] = []
    prefix = False
    for name in ("npm", "npx"):
        if normalized == _normalized_batch(_npm_prefix_shim(name)):
            target = f"node_modules\\npm\\bin\\{name}-cli.js"
            prefix = True
            break
    if target is None:
        match = re.search(r'"%_prog%"\s+(.*?)\s*"%dp0%\\([^"\r\n]+)"\s+%\*', text, re.I)
        if match:
            flags, candidate = match.groups()
            if any(
                normalized == _normalized_batch(_npm_shim(candidate, flags, legacy=legacy))
                for legacy in (False, True)
            ):
                target = candidate
                node_flags = parse_command_line(flags, windows=True, first_arg_is_executable=False)
                if any(any(c in flag for c in "%&|<>^\r\n") for flag in node_flags):
                    target = None
        # npm cmd-shim without a shebang: a direct, relative native target.
        match = re.search(r'"%dp0%\\([^"\r\n]+)"\s+%\*', text, re.I)
        if target is None and match:
            candidate = match.group(1)
            direct = f'{_SHIM_HEAD}\n"%dp0%\\{candidate}"   %*'
            if normalized == _normalized_batch(direct):
                native = _shim_target(executable, candidate)
                if native.suffix.lower() in {".exe", ".com"}:
                    return [str(native), *args[1:]]
    if target is None:
        raise ValueError(
            f"Unsupported Windows batch shim {executable.name}; use native executable/Node script argv or explicitly enable the existing unsafe-shell option"
        )
    script = _shim_target(executable, target)
    adjacent_node = executable.parent / "node.exe"
    node = (
        str(adjacent_node)
        if adjacent_node.is_file()
        else find_executable("node", cwd=cwd, env=env, windows=True, native_only=True)
    )
    if node is None:
        raise FileNotFoundError(
            f"Windows shim {executable.name} requires node.exe in its directory or the subprocess PATH"
        )
    if prefix:
        prefix_script = _shim_target(executable, "node_modules\\npm\\bin\\npm-prefix.js")
        return [node, "-e", _NPM_PREFIX_DISPATCH, "--", str(prefix_script), str(script), *args[1:]]
    return [node, *node_flags, str(script), *args[1:]]
