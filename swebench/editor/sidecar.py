import json
import os
import tempfile
import asyncio
from swebench.harness.constants import SWEbenchInstance


async def sidecar_run(
    sidecar_path: str,
    git_drname: str,
    endpoint_url: str,
    instance: SWEbenchInstance,
    run_id: str,
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

        command_args.extend([
            "--input", temp_file_path,
            "--timeout", "1800",
            "--editor-url", endpoint_url,
            "--run-id", run_id,
            "--anthropic-api-key", "",
        ])

        command_args.append("--run-id")
        command_args.append(run_id)

        command_args.append("--anthropic-api-key")
        command_args.append("")
        print("sidecar_binary_args", command_args)

        process = await asyncio.create_subprocess_exec(
            *command_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_stream(stream, name):
            async for line in stream:
                print(f"{name}: {line.decode().strip()}")

        # Concurrently read stdout and stderr
        await asyncio.gather(
            read_stream(process.stdout, "STDOUT"),
            read_stream(process.stderr, "STDERR"),
        )

        # Wait for the process to complete
        return_code = await process.wait()

        if return_code != 0:
            raise RuntimeError(f"Sidecar process failed with return code {return_code}")
