import json
import os
import tempfile
import asyncio
from typing import Optional
from swebench.harness.constants import SWEbenchInstance
from swebench.utils import get_parea_link


async def sidecar_run(
    sidecar_path: str,
    git_drname: str,
    endpoint_url: str,
    instance: SWEbenchInstance,
    run_id: str,
    anthropic_api_key: str,
    log_directory: str,
    traj_search_space: Optional[int],
):
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmp_path = tmpdirname

        command_args = [
            sidecar_path,
        ]
        json_data = {
            "git_drname": git_drname,
            "instance": instance,
        }
        temp_file_path = os.path.join(tmp_path, 'data.json')
        with open(temp_file_path, 'w') as temp_file:
            json.dump(json_data, temp_file)

        args = [
            "--input", temp_file_path,
            "--timeout", "1800",
            "--editor-url", endpoint_url,
            "--run-id", run_id,
            "--anthropic-api-key", anthropic_api_key,
            "--repo-name", instance["repo"],
            "--log-directory", log_directory,
        ]
        if traj_search_space != None and traj_search_space != 0:
            args.extend(["--single-traj-search", str(traj_search_space)])

        command_args.extend(args)
        print("sidecar_binary_args", command_args)

        link = get_parea_link(run_id)

        print(f"PAREA LINK:\n===\n{link}\n===")

        # Copy the os.environment and set the force cli color to true
        env = os.environ.copy()
        env["CLICOLOR_FORCE"] = "1"
        process = await asyncio.create_subprocess_exec(
            *command_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=4**20,  # for example, set a 1MB limit
            env=env,
        )

        async def read_stream(stream, name):
            async for line in stream:
                decoded_line: str = line.decode()
                if decoded_line == '\n':
                    continue
                print(f"{name}: {decoded_line.rstrip()}")

        # Concurrently read stdout and stderr
        await asyncio.gather(
            read_stream(process.stdout, "STDOUT"),
            read_stream(process.stderr, "STDERR"),
        )

        # Wait for the process to complete
        return_code = await process.wait()

        if return_code != 0:
            raise RuntimeError(f"Sidecar process failed with return code {return_code}")
