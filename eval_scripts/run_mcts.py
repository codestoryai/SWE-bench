from argparse import ArgumentParser
import os
import subprocess
import asyncio
from time import time

async def run_command_for_instance(instance_id, anthropic_api_key, sidecar_binary_path, run_id):
    try:
        # First command: Docker pull - this is Django-specific
        docker_name = instance_id.replace('django__django-', 'django_1776_django-')
        docker_image = f"swebench/sweb.eval.x86_64.{docker_name}:v1"
        pull_command = f"docker pull {docker_image}"
        
        print(f"\nPulling Docker image for: {instance_id}")
        pull_process = await asyncio.create_subprocess_shell(
            pull_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        pull_stdout, pull_stderr = await pull_process.communicate()
        pull_stdout = pull_stdout.decode()
        pull_stderr = pull_stderr.decode()

        output_log_path = f"output_{run_id}.log"
        
        # Second command: Run evaluation
        run_command = (
            f"python3 -u swebench/harness/run_evaluation.py " # -u is for unbuffered output
            f"--dataset_name dataset/verified/output.jsonl "
            f"--instance_ids {instance_id} "
            f"--sidecar_executable_path {sidecar_binary_path} "
            f"--anthropic_api_key {anthropic_api_key} " # don't forget to preserve the trailing space
            f"--run_id {run_id} "
            f"--output_log_path {output_log_path} "
        )

        print(run_command)
        
        print(f"Running evaluation for: {instance_id}")
        run_process = await asyncio.create_subprocess_shell(
            run_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Replace communicate() with real-time logging
        async def read_stream(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                print(line.decode().rstrip())
        
        # Read both stdout and stderr concurrently
        await asyncio.gather(
            read_stream(run_process.stdout),
            read_stream(run_process.stderr)
        )
        
        # Wait for process to complete
        await run_process.wait()

        if pull_process.returncode != 0 or run_process.returncode != 0:
            raise Exception(f"Command failed with exit codes: pull={pull_process.returncode}, run={run_process.returncode}")

        return {'success': True, 'string': instance_id}
    
    except Exception as error:
        print(f"Error processing {instance_id}:", error)
        return {'success': False, 'string': instance_id, 'error': str(error)}

async def process_instances(instances, anthropic_api_key, sidecar_binary_path):
    print('Starting processing...')
    results = []

    current_timestamp = int(time())  # will be run_id
    print(f"Current timestamp: {current_timestamp}")
    
    for instance_id in instances:
        result = await run_command_for_instance(instance_id, anthropic_api_key, sidecar_binary_path, current_timestamp)
        results.append(result)
        
        # Log summary after each string is processed
        success = result['success']
        status = "✓ Success" if success else "✗ Failed"
        print(f"{status}: {instance_id}")
    
    # Print final summary
    successful = sum(1 for r in results if r['success'])
    print(f'\nProcessing complete! {successful}/{len(instances)} successful')

# Example usage
if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--anthropic_api_key", type=str, help="Set the anthropic api key which we should be using")
    parser.add_argument("--sidecar_binary_path", type=str, help="Set the sidecar binary path which we should be using")
    parser.add_argument("--instances_file", type=str, help="Path to file containing instance IDs")
    
    args = parser.parse_args()

    if not args.anthropic_api_key:
        raise ValueError("Anthropic API key must be provided. Usage: --anthropic_api_key <key>")

    if not args.sidecar_binary_path:
        raise ValueError("Sidecar binary path must be provided. Usage: --sidecar_binary_path <path>")
    
     # Read instance IDs from file
    if not os.path.exists(args.instances_file):
        raise ValueError(f"Instances file not found: {args.instances_file}")

    # Read instance IDs from text file
    with open(args.instances_file, 'r') as f:
        instance_ids = [line.strip() for line in f if line.strip()]

    print(f"Processing {len(instance_ids)} instances")

    anthropic_api_key = args.anthropic_api_key
    sidecar_binary_path = args.sidecar_binary_path

    asyncio.run(process_instances(instance_ids, anthropic_api_key, sidecar_binary_path)) 