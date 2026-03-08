"""Frontend Design Loop MCP stdio server entrypoint.

We keep this thin on purpose: the full implementation lives in
`frontend_design_loop_core.mcp_code_server` so the package surface stays small and the
runtime can be reused by scripts and tests.
"""

from __future__ import annotations

import argparse
import os

from frontend_design_loop_mcp import __version__

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="frontend-design-loop-mcp",
        description="Frontend Design Loop MCP stdio server. Run with no arguments under an MCP client.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the installed Frontend Design Loop MCP version and exit",
    )
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return

    # MCP stdio transport requires stdout cleanliness. Ensure any Rich-based logs
    # end up on stderr, even if downstream imports log warnings.
    os.environ.setdefault("FRONTEND_DESIGN_LOOP_STDIO_MCP", "1")

    from frontend_design_loop_core.mcp_code_server import main as _main

    _main()


if __name__ == "__main__":
    main()
