"""MCP stdio shutdown that can unwind owned processes on POSIX SIGTERM."""

from __future__ import annotations

import asyncio
import os
import signal
import sys

import anyio
from mcp.server.stdio import stdio_server


class _Lines:
    def __init__(self, reader: asyncio.StreamReader):
        self.reader = reader

    def __aiter__(self):
        return self

    async def __anext__(self):
        line = await self.reader.readline()
        if not line:
            raise StopAsyncIteration
        return line.decode("utf-8", errors="replace")


def run_stdio_server(server) -> None:
    if os.name != "posix":
        server.run(transport="stdio")
        return

    async def run():
        reader = asyncio.StreamReader(limit=32_000_000)
        transport, _ = await asyncio.get_running_loop().connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer
        )
        try:
            with anyio.open_signal_receiver(signal.SIGTERM, signal.SIGINT) as signals:
                async with anyio.create_task_group() as group:

                    async def stop_on_signal():
                        async for _ in signals:
                            group.cancel_scope.cancel()
                            break

                    group.start_soon(stop_on_signal)
                    try:
                        async with stdio_server(stdin=_Lines(reader)) as (receive, send):
                            await server._mcp_server.run(
                                receive, send, server._mcp_server.create_initialization_options()
                            )
                    finally:
                        group.cancel_scope.cancel()
        finally:
            transport.close()

    anyio.run(run)
