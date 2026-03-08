import pytest

from frontend_design_loop_mcp import __version__
from frontend_design_loop_mcp import mcp_server


def test_mcp_server_help_exits_cleanly(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        mcp_server.main(["--help"])

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "Frontend Design Loop MCP stdio server" in out


def test_mcp_server_version_prints(capsys) -> None:
    mcp_server.main(["--version"])
    out = capsys.readouterr().out.strip()
    assert out == __version__


def test_mcp_server_sets_stdio_env(monkeypatch) -> None:
    from frontend_design_loop_core import mcp_code_server

    sentinel = RuntimeError("stop-after-env-check")

    def fake_main() -> None:
        raise sentinel

    monkeypatch.delenv("FRONTEND_DESIGN_LOOP_STDIO_MCP", raising=False)
    monkeypatch.setattr(mcp_code_server, "main", fake_main)

    with pytest.raises(RuntimeError, match="stop-after-env-check"):
        mcp_server.main([])

    assert mcp_server.os.environ["FRONTEND_DESIGN_LOOP_STDIO_MCP"] == "1"
