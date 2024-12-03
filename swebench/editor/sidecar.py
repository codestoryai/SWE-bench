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
    anthropic_api_key: str,
    log_directory: str,
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
            "--anthropic-api-key", anthropic_api_key,
            "--repo-name", instance["repo"],
            "--log-directory", log_directory,
        ])
        print("sidecar_binary_args", command_args)

        link = f"""https://app.parea.ai/logs?colViz=%7B%220%22%3Afalse%2C%221%22%3Afalse%2C%222%22%3Afalse%2C%223%22%3Afalse%2C%22error%22%3Afalse%2C%22deployment_id%22%3Afalse%2C%22feedback_score%22%3Afalse%2C%22time_to_first_token%22%3Afalse%2C%22scores%22%3Afalse%2C%22start_timestamp%22%3Afalse%2C%22user%22%3Afalse%2C%22session_id%22%3Afalse%2C%22target%22%3Afalse%2C%22experiment_uuid%22%3Afalse%2C%22dataset_references%22%3Afalse%2C%22in_dataset%22%3Afalse%2C%22event_type%22%3Afalse%2C%22request_type%22%3Afalse%2C%22evaluation_metric_names%22%3Afalse%2C%22request%22%3Afalse%2C%22calling_node%22%3Afalse%2C%22edges%22%3Afalse%2C%22metadata_evaluation_metric_names%22%3Afalse%2C%22metadata_event_type%22%3Afalse%2C%22metadata_0%22%3Afalse%2C%22metadata_calling_node%22%3Afalse%2C%22metadata_edges%22%3Afalse%2C%22metadata_root_id%22%3Afalse%7D&filter=%7B%22filter_field%22%3A%22meta_data%22%2C%22filter_operator%22%3A%22equals%22%2C%22filter_key%22%3A%22%22%2C%22filter_value%22%3A%22{run_id}%22%7D&page=1"""

        print(f"PAREA LINK:\n===\n{link}\n===")

        process = await asyncio.create_subprocess_exec(
            *command_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
