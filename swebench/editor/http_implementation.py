#!/usr/bin/env python

import asyncio
from typing import Tuple
from swebench.editor.webserver import setup_webserver

async def setup_editor(git_dname, test_cmd) -> Tuple[str, asyncio.Task]:
    """
    Set up the Language Server Protocol for the code in `git_dname`.
    """
    # TODO(skcd): We want to setup LSP from the resouce, and we want to make
    # sure we set it up in such a way that we can expose it as an endpoint
    # and then talk to it from the sidecar
    # using JEDI
    port = 6897
    print("http_implementation::setup_editor")
    # We want to cancel the task here at teardown, how do we do that?
    task = asyncio.create_task(setup_webserver(git_dname, port, test_cmd))
    return f"http://localhost:{port}", task
