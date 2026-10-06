"""Job protocol tests everywhere; process ownership regressions on Windows only."""

import asyncio
import ctypes
import errno
import json
import os
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from frontend_design_loop_core import utils
from frontend_design_loop_core import windows_process_host as host

native_windows = pytest.mark.skipif(os.name != "nt", reason="Requires native Windows Job Objects")


class FakeJobApi:
    def __init__(self, failure=None):
        self.events = []
        self.failure = failure
        self.handle = 1 << 40

    def CreateJobObjectW(self, security, name):  # noqa: N802 -- Match the Win32 API.
        assert security is None and name is None
        self.events.append("create")
        return 0 if self.failure == "create" else self.handle

    def SetInformationJobObject(self, job, info_class, limits, size):  # noqa: N802
        assert job == self.handle
        assert info_class == 9
        assert size == ctypes.sizeof(host._ExtendedLimitInformation)
        assert limits._obj.BasicLimitInformation.LimitFlags == 0x2000
        self.events.append("configure")
        return self.failure != "configure"

    def GetCurrentProcess(self):  # noqa: N802
        return -1

    def AssignProcessToJobObject(self, job, process):  # noqa: N802
        assert job == self.handle and process == -1
        self.events.append("assign")
        return self.failure != "assign"

    def CloseHandle(self, job):  # noqa: N802
        assert job == self.handle
        self.events.append("close")
        return True


@pytest.mark.parametrize("failure", ["create", "configure", "assign"])
def test_host_refuses_to_launch_without_job_ownership(monkeypatch, failure):
    api = FakeJobApi(failure)
    monkeypatch.setattr(
        host, "_job_error", lambda operation: OSError(5, f"Windows Job ownership: {operation}")
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Target was launched before Job ownership was established")

    monkeypatch.setattr(host.subprocess, "Popen", forbidden)
    read_fd, write_fd = os.pipe()
    try:
        assert host._host(["target"], shell=False, status_fd=write_fd, api=api) == 125
        status = json.loads(os.read(read_fd, 4096))
    finally:
        os.close(read_fd)
    assert status["error"] == "OSError"
    assert "Windows Job ownership" in status["message"]
    assert ("close" in api.events) is (failure != "create")


@pytest.mark.parametrize(
    "shell,command",
    [(False, ["target", "", "a&b", 'quoted"', "trail\\"]), (True, "echo one && echo two")],
)
def test_host_owns_job_before_launch_and_keeps_handle_until_exit(monkeypatch, shell, command):
    api = FakeJobApi()
    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, True)

    def launch(actual, **kwargs):
        assert api.events == ["create", "configure", "assign"]
        assert actual == command
        assert kwargs == {
            "shell": shell,
            "close_fds": True,
            "stdin": sys.stdin,
            "stdout": sys.stdout,
            "stderr": sys.stderr,
        }
        assert not os.get_inheritable(write_fd)
        api.events.append("launch")

        def wait():
            assert json.loads(os.read(read_fd, 4096)) == {"ok": True}
            api.events.append("wait")
            return 0xC0000005

        return SimpleNamespace(wait=wait)

    monkeypatch.setattr(host.subprocess, "Popen", launch)
    try:
        assert host._host(command, shell=shell, status_fd=write_fd, api=api) == 0xC0000005
    finally:
        os.close(read_fd)
    assert api.events == ["create", "configure", "assign", "launch", "wait"]


def test_host_reports_target_launch_failure_separately_from_target_output(monkeypatch):
    api = FakeJobApi()

    def fail(*args, **kwargs):
        raise FileNotFoundError(errno.ENOENT, "missing target")

    monkeypatch.setattr(host.subprocess, "Popen", fail)
    read_fd, write_fd = os.pipe()
    try:
        assert host._host(["missing"], shell=False, status_fd=write_fd, api=api) == 125
        status = json.loads(os.read(read_fd, 4096))
    finally:
        os.close(read_fd)
    assert status["error"] == "FileNotFoundError" and status["errno"] == errno.ENOENT
    # Closing the Job while the host is a member would kill it before reporting.
    assert "close" not in api.events


def test_windows_abi_uses_fixed_width_flags_and_pointer_sized_handles(monkeypatch):
    api = SimpleNamespace(
        **{
            name: SimpleNamespace()
            for name in (
                "CreateJobObjectW",
                "SetInformationJobObject",
                "AssignProcessToJobObject",
                "GetCurrentProcess",
                "CloseHandle",
                "PeekNamedPipe",
                "ExitProcess",
            )
        }
    )
    monkeypatch.setattr(host, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(host.ctypes, "WinDLL", lambda *args, **kwargs: api, raising=False)
    assert host._kernel32() is api
    assert api.CreateJobObjectW.restype is ctypes.c_void_p
    assert api.AssignProcessToJobObject.argtypes == [ctypes.c_void_p, ctypes.c_void_p]
    assert ctypes.sizeof(host._DWORD) == 4
    assert ctypes.sizeof(host._ExtendedLimitInformation) == (
        144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("already_exited", [False, True])
async def test_windows_cleanup_uses_only_host_handle(monkeypatch, already_exited):
    calls = []
    process = SimpleNamespace(returncode=0 if already_exited else None)

    def kill():
        calls.append("kill")
        process.returncode = 1

    async def wait():
        calls.append("wait")
        return process.returncode

    process.kill = kill
    process.wait = wait
    monkeypatch.setattr(utils, "os", SimpleNamespace(name="nt"))
    await utils.terminate_process_tree(process)
    assert calls == (["wait"] if already_exited else ["kill", "wait"])


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_cleanup(monkeypatch):
    started, finished = asyncio.Event(), asyncio.Event()

    async def cleanup(*args, **kwargs):
        started.set()
        await finished.wait()

    monkeypatch.setattr(utils, "_terminate_process_tree", cleanup)
    task = asyncio.create_task(utils.terminate_process_tree(SimpleNamespace()))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finished.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        None,
        {"error": "FileNotFoundError", "errno": 2, "message": "missing"},
        {"error": "OSError", "errno": 5, "message": "Windows Job ownership failed"},
    ],
)
async def test_shared_windows_launch_protocol_preserves_stdio(monkeypatch, failure):
    actual_os = os
    read_fd, write_fd = os.pipe()
    closed = []
    cleaned = []
    calls = []
    process = SimpleNamespace(returncode=None)
    kwargs = {
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.STDOUT,
        "limit": 8192,
    }
    child_env = {"MARKER": "sanitized"}
    argv = ["target", "", "a&b", 'quoted"', "trail\\"]

    def close(fd):
        closed.append(fd)
        actual_os.close(fd)

    async def spawn(*args, **options):
        calls.append((args, options))
        return process

    async def status(fd):
        assert fd == read_fd
        assert write_fd in closed
        return failure or {"ok": True}

    async def cleanup(proc, **options):
        assert proc is process and options == {"drain_output": True}
        cleaned.append(proc)

    monkeypatch.setattr(utils, "os", SimpleNamespace(name="nt", close=close))
    monkeypatch.setattr(utils, "_windows_host_pipe", lambda options: (read_fd, write_fd, 12345))
    monkeypatch.setattr(utils, "_windows_host_status", status)
    monkeypatch.setattr(utils, "prepare_process_argv", lambda args, **options: args)
    monkeypatch.setattr(utils.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(utils, "terminate_process_tree", cleanup)
    if failure:
        with pytest.raises(OSError, match=failure["message"]):
            await utils.launch_process_argv(argv, cwd="child cwd", env=child_env, **kwargs)
        assert cleaned == [process]
    else:
        assert (
            await utils.launch_process_argv(argv, cwd="child cwd", env=child_env, **kwargs)
            is process
        )
        assert not cleaned
    args, options = calls[0]
    assert args[:3] == (sys.executable, "-I", "-S")
    assert Path(args[3]).is_absolute() and Path(args[3]).name == "windows_process_host.py"
    assert args[4:6] == ("12345", "argv") and json.loads(args[6]) == argv
    assert options == {**kwargs, "cwd": "child cwd", "env": child_env, "start_new_session": False}
    assert closed == [write_fd, read_fd]


@pytest.mark.asyncio
async def test_cancellation_during_host_creation_recovers_and_kills_host(monkeypatch):
    actual_os = os
    read_fd, write_fd = os.pipe()
    entered, release = asyncio.Event(), asyncio.Event()
    cleaned = []
    process = SimpleNamespace(returncode=None)

    async def spawn(*args, **kwargs):
        entered.set()
        await release.wait()
        return process

    async def cleanup(proc, **kwargs):
        cleaned.append(proc)

    monkeypatch.setattr(utils, "os", SimpleNamespace(name="nt", close=actual_os.close))
    monkeypatch.setattr(utils, "_windows_host_pipe", lambda options: (read_fd, write_fd, 12345))
    monkeypatch.setattr(utils.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(utils, "terminate_process_tree", cleanup)
    task = asyncio.create_task(utils._launch_process(["target"]))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned == [process]


def test_private_startup_pipe_does_not_mutate_caller_handle_list(monkeypatch):
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(get_osfhandle=lambda fd: fd))
    original = SimpleNamespace(lpAttributeList={"handle_list": [987]})
    options = {"startupinfo": original, "stdin": asyncio.subprocess.PIPE}
    read_fd, write_fd, handle = utils._windows_host_pipe(options)
    try:
        assert not os.get_inheritable(read_fd)
        assert os.get_inheritable(write_fd)
        assert options["startupinfo"] is not original
        assert options["startupinfo"].lpAttributeList["handle_list"] == [987, handle]
        assert original.lpAttributeList == {"handle_list": [987]}
        assert options["close_fds"] is True
        assert options["stdin"] == asyncio.subprocess.PIPE
    finally:
        os.close(write_fd)
        os.close(read_fd)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [False, True])
async def test_startup_status_is_polled_and_size_bounded(monkeypatch, invalid):
    data = b"x" * 4096 if invalid else b'{"ok": true}\n'
    read_fd, write_fd = os.pipe()
    os.write(write_fd, data)
    ready = iter([0, 0, len(data)])
    monkeypatch.setattr(host, "_kernel32", lambda: None)
    monkeypatch.setattr(host, "pipe_available", lambda fd, api: next(ready))
    try:
        if invalid:
            with pytest.raises(RuntimeError, match="invalid startup status"):
                await asyncio.wait_for(utils._windows_host_status(read_fd), timeout=1)
        else:
            assert await asyncio.wait_for(utils._windows_host_status(read_fd), timeout=1) == {
                "ok": True
            }
    finally:
        os.close(write_fd)
        os.close(read_fd)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "broken_pipe", "cancellation"])
async def test_failed_or_cancelled_startup_handshake_reclaims_host(monkeypatch, failure):
    read_fd, write_fd = os.pipe()
    entered = asyncio.Event()
    cleaned = []
    process = SimpleNamespace(returncode=None)

    async def spawn(*args, **kwargs):
        return process

    async def status(fd):
        entered.set()
        if failure == "timeout":
            raise asyncio.TimeoutError
        if failure == "broken_pipe":
            raise BrokenPipeError("host died")
        await asyncio.Event().wait()

    async def cleanup(proc, **kwargs):
        assert kwargs == {"drain_output": True}
        cleaned.append(proc)

    monkeypatch.setattr(utils, "os", SimpleNamespace(name="nt", close=os.close))
    monkeypatch.setattr(utils, "_windows_host_pipe", lambda options: (read_fd, write_fd, 12345))
    monkeypatch.setattr(utils, "_windows_host_status", status)
    monkeypatch.setattr(utils.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(utils, "terminate_process_tree", cleanup)
    task = asyncio.create_task(utils._launch_process(["target"]))
    await entered.wait()
    if failure == "cancellation":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(RuntimeError, match="before confirming Job ownership"):
            await task
    assert cleaned == [process]


@pytest.mark.asyncio
async def test_shared_launch_roundtrips_raw_binary_stdio_and_literal_argv(tmp_path):
    args = ["", "a&b", "%UNEXPANDED%", 'quoted"', "trail\\", "雪"]
    payload = b"\x00\xff\x80\r\n"
    code = (
        "import json,os,sys; "
        "assert json.loads(os.environ['EXPECTED_ARGS'])==sys.argv[1:]; "
        "assert os.getcwd()==os.environ['EXPECTED_CWD']; "
        "sys.stdout.buffer.write(sys.stdin.buffer.read()); sys.stdout.buffer.flush(); "
        "sys.stderr.buffer.write(b'err'); sys.exit(37)"
    )
    env = {**os.environ, "EXPECTED_ARGS": json.dumps(args), "EXPECTED_CWD": str(tmp_path)}
    env.pop("PYTHONPATH", None)
    proc = await utils.launch_process_argv(
        [sys.executable, "-c", code, *args],
        cwd=tmp_path,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        limit=8192,
        start_new_session=os.name == "posix",
    )
    try:
        output, error = await asyncio.wait_for(proc.communicate(payload), timeout=15)
        assert output == payload + b"err" and error is None
        assert proc.returncode == 37
    finally:
        await utils.terminate_process_tree(proc, drain_output=True)


def _parent_code(pid_file, *, redirected=False, wait=True):
    redirection = (
        ",stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL"
        if redirected
        else ""
    )
    return (
        "import subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']"
        f"{redirection}); "
        f"open({str(pid_file)!r},'w').write(str(p.pid)); "
        + ("time.sleep(60)" if wait else "sys.exit(23)")
    )


async def _wait_for_child(pid_file):
    async def read():
        while True:
            try:
                return int(pid_file.read_text())
            except (OSError, ValueError):
                await asyncio.sleep(0.01)

    return await asyncio.wait_for(read(), timeout=15)


@contextmanager
def _child_handle(pid):
    # A fixture-specific process handle, never a broad process search. Retaining
    # it makes failure cleanup safe even if Windows later reuses this PID.
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    api.OpenProcess.restype = ctypes.c_void_p
    api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    api.WaitForSingleObject.restype = ctypes.c_uint32
    api.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    api.TerminateProcess.restype = ctypes.c_int
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    api.CloseHandle.restype = ctypes.c_int
    handle = api.OpenProcess(0x100000 | 0x1000 | 1, False, pid)
    if not handle:
        assert ctypes.get_last_error() == 87, "Could not inspect fixture child"
    try:
        yield api, handle
    finally:
        if handle:
            if api.WaitForSingleObject(handle, 0) == 258:
                api.TerminateProcess(handle, 1)
                api.WaitForSingleObject(handle, 5000)
            api.CloseHandle(handle)


def _assert_child_dead(api, handle):
    assert not handle or api.WaitForSingleObject(handle, 5000) == 0, (
        "Invocation child survived cleanup"
    )


@native_windows
@pytest.mark.asyncio
@pytest.mark.parametrize("redirected", [False, True])
async def test_native_job_reclaims_children_after_parent_immediately_exits(tmp_path, redirected):
    pid_file = tmp_path / "child.pid"
    rc, _, error = await asyncio.wait_for(
        utils.run_process_argv(
            [sys.executable, "-c", _parent_code(pid_file, redirected=redirected, wait=False)],
            timeout_s=10,
        ),
        timeout=20,
    )
    assert rc == 23, error
    with _child_handle(await _wait_for_child(pid_file)) as (api, handle):
        _assert_child_dead(api, handle)


@native_windows
@pytest.mark.asyncio
@pytest.mark.parametrize("shell", [False, True])
async def test_native_job_timeout_kills_child_holding_pipes_open(tmp_path, shell):
    pid_file = tmp_path / "child.pid"
    args = [sys.executable, "-c", _parent_code(pid_file)]
    if shell:
        running = utils.run_command(subprocess.list2cmdline(args), timeout_ms=3000)
    else:
        running = utils.run_command_argv(args, timeout_ms=3000)
    task = asyncio.create_task(running)
    try:
        with _child_handle(await _wait_for_child(pid_file)) as (api, handle):
            assert handle and api.WaitForSingleObject(handle, 0) == 258
            rc, _, error = await asyncio.wait_for(task, timeout=20)
            assert rc == -1 and "timed out" in error
            _assert_child_dead(api, handle)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@native_windows
@pytest.mark.asyncio
@pytest.mark.parametrize("shell", [False, True])
async def test_native_job_cancellation_kills_child_holding_pipes_open(tmp_path, shell):
    pid_file = tmp_path / "child.pid"
    args = [sys.executable, "-c", _parent_code(pid_file)]
    run = (
        utils.run_command(subprocess.list2cmdline(args))
        if shell
        else utils.run_process_argv(args, timeout_s=60)
    )
    task = asyncio.create_task(run)
    try:
        with _child_handle(await _wait_for_child(pid_file)) as (api, handle):
            assert handle and api.WaitForSingleObject(handle, 0) == 258
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=20)
            _assert_child_dead(api, handle)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@native_windows
@pytest.mark.asyncio
@pytest.mark.parametrize("shell", [False, True])
async def test_native_job_preview_stop_kills_redirected_child(tmp_path, shell):
    pid_file = tmp_path / "child.pid"
    args = [sys.executable, "-c", _parent_code(pid_file, redirected=True)]
    manager = (
        utils.managed_process(subprocess.list2cmdline(args))
        if shell
        else utils.managed_process_argv(args)
    )
    with ExitStack() as children:
        async with manager as proc:
            api, handle = children.enter_context(_child_handle(await _wait_for_child(pid_file)))
            assert handle and api.WaitForSingleObject(handle, 0) == 258
        _assert_child_dead(api, handle)
    assert proc.returncode is not None


@native_windows
@pytest.mark.asyncio
async def test_native_host_preserves_raw_shell_semantics():
    rc, output, error = await utils.run_command("echo one && echo two")
    assert rc == 0, error
    assert output.splitlines() == ["one ", "two"] or output.splitlines() == ["one", "two"]


@native_windows
@pytest.mark.asyncio
async def test_native_target_launch_error_raises_instead_of_becoming_exit_code(tmp_path):
    with pytest.raises(FileNotFoundError):
        await utils.launch_process_argv(
            [str(tmp_path / "missing.exe")],
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )


@native_windows
@pytest.mark.asyncio
async def test_native_host_reports_createprocess_failure(tmp_path):
    executable = tmp_path / "invalid-target.exe"
    executable.write_bytes(b"This is not a Windows executable.")
    with pytest.raises(OSError, match="WinError 193"):
        await utils.launch_process_argv(
            [str(executable)],
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )


@native_windows
@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", [None, "stdin prompt 雪\n"])
async def test_native_host_starts_without_package_environment_and_preserves_stdin(tmp_path, prompt):
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT")
    assert system_root
    env = {"SystemRoot": system_root, "FIXTURE_MARKER": "child environment"}
    code = (
        "import json,os,sys; print(json.dumps([sys.stdin.buffer.read().decode('utf-8'),os.getcwd(),"
        "os.environ['FIXTURE_MARKER'],os.environ.get('PYTHONPATH')]))"
    )
    rc, output, error = await utils.run_process_argv(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        input_text=prompt,
    )
    assert rc == 0, error
    assert json.loads(output) == [prompt or "", str(tmp_path), "child environment", None]


@native_windows
@pytest.mark.asyncio
async def test_native_host_preserves_windows_dword_exit_status():
    code = "import ctypes; ctypes.windll.kernel32.ExitProcess(0xC0000005)"
    rc, _, error = await utils.run_process_argv([sys.executable, "-c", code])
    assert rc == 0xC0000005, error


def test_default_stdio_is_explicit_at_host_boundary():
    kwargs = {}
    utils._windows_inherited_stdio(kwargs, SimpleNamespace(get_osfhandle=lambda fd: 100 + fd))
    assert kwargs == {"stdin": 0, "stdout": 1, "stderr": 2}
    explicit = {"stdin": asyncio.subprocess.PIPE, "stdout": None, "stderr": None}
    utils._windows_inherited_stdio(explicit, SimpleNamespace(get_osfhandle=lambda fd: pytest.fail("must preserve explicit stdio")))
    assert explicit == {"stdin": asyncio.subprocess.PIPE, "stdout": None, "stderr": None}


def test_absent_standard_descriptors_use_devnull():
    def handle(fd):
        if fd == 0:
            raise OSError("no standard input")
        return -2 if fd == 1 else 102
    kwargs = {"stdin": None, "stdout": None, "stderr": None}
    utils._windows_inherited_stdio(kwargs, SimpleNamespace(get_osfhandle=handle))
    assert kwargs == {"stdin": asyncio.subprocess.DEVNULL, "stdout": asyncio.subprocess.DEVNULL, "stderr": 2}


@native_windows
def test_native_default_stdio_preserves_redirected_parent_streams(tmp_path):
    script = tmp_path / "parent.py"
    package_root = str(Path(utils.__file__).resolve().parents[1])
    child = "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read());sys.stdout.buffer.flush();sys.stderr.buffer.write(b'child-stderr');sys.exit(23)"
    script.write_text(
        "import asyncio,sys\n"
        + f"sys.path.insert(0, {package_root!r})\n"
        + "from frontend_design_loop_core import utils\n"
        + "async def main():\n"
        + f"    process = await utils.launch_process_argv([sys.executable, '-c', {child!r}])\n"
        + "    try:\n        await asyncio.wait_for(process.wait(), 10)\n        assert process.returncode == 23\n"
        + "    finally:\n        await utils.terminate_process_tree(process, drain_output=True)\n"
        + "asyncio.run(main())\n"
    )
    payload = b"redirected-input\x00\xff\r\n"
    result = subprocess.run([sys.executable, str(script)], input=payload, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert result.stdout == payload
    assert result.stderr == b"child-stderr"
