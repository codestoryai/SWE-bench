#!/usr/bin/env python

import asyncio
from typing import Tuple
from swebench.editor.webserver import setup_webserver
import socket

def find_free_port(start_port: int = 6897) -> int:
    """Find the first available port starting from start_port."""
    port = start_port
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return port
        except OSError:
            port += 1

async def setup_editor(git_dname, test_cmd, terminal_command_runner) -> Tuple[str, asyncio.Task]:
    """
    Set up the Language Server Protocol for the code in `git_dname`.
    """
    # TODO(skcd): We want to setup LSP from the resouce, and we want to make
    # sure we set it up in such a way that we can expose it as an endpoint
    # and then talk to it from the sidecar
    # using JEDI
    port = find_free_port()
    print(f"http_implementation::setup_editor using port {port}")
    # We want to cancel the task here at teardown, how do we do that?
    task = asyncio.create_task(setup_webserver(git_dname, port, test_cmd, terminal_command_runner))
    return f"http://localhost:{port}", task
