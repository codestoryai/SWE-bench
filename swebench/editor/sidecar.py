import json
import os
import tempfile
import subprocess
from swebench.harness.constants import SWEbenchInstance


def sidecar_run(
    sidecar_path: str,
    git_drname: str,
    endpoint_url: str,
    instance: SWEbenchInstance,
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

        command_args.append("--input")
        command_args.append(temp_file_path)
        command_args.append("--timeout")
        command_args.append("1800")
        command_args.append("--editor-url")
        command_args.append(endpoint_url)

        print("sidecar_binary_args", command_args)

        process = subprocess.Popen(
            command_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,  # Ensures output is decoded as text (str) instead of bytes
        )

        # Stream and print stdout and stderr in real-time
        try:
            for line in process.stdout:
                print(f"STDOUT: {line.strip()}")
            for line in process.stderr:
                print(f"STDERR: {line.strip()}")
        except Exception as e:
            print(f"Error while streaming process output: {e}")

        # Wait for process to complete
        process.wait()

        # Check the exit code
        if process.returncode != 0:
            raise RuntimeError(f"Sidecar process failed with return code {process.returncode}")
