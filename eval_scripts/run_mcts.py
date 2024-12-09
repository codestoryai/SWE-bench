import asyncio
import logging
import json
import os
from time import time
from argparse import ArgumentParser

# Set up structured logging
logger = logging.getLogger("batch_processor")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(handler)

async def run_command_for_instance(instance_id, anthropic_api_key, sidecar_binary_path, run_id):
    try:
        # First command: Docker pull - this is Django-specific
        docker_name = instance_id.replace('django__django-', 'django_1776_django-')
        docker_image = f"swebench/sweb.eval.x86_64.{docker_name}:v1"
        pull_command = f"docker pull {docker_image}"
        
        print(f"\nPulling Docker image for: {instance_id}")
        pull_process = await asyncio.create_subprocess_shell(
            pull_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
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
            f"--traj_search_space 1" # allow for upto 2 trajectories to be generated, trying to exhaust the search space
        )

        print(run_command)
        
        print(f"Running evaluation for: {instance_id}")
        run_process = await asyncio.create_subprocess_shell(
            run_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=4**20,  # for example, set a 1MB limit
        )
        
        # Replace communicate() with real-time logging
        async def read_stream(stream, name):
            async for line in stream:
                decoded_line: str = line.decode()
                if decoded_line == '\n':
                    continue
                print(f"PYTHON SCRIPT {name}: {decoded_line.rstrip()}")
        
        # Read both stdout and stderr concurrently
        await asyncio.gather(
            read_stream(run_process.stdout, "STDOUT"),
            read_stream(run_process.stderr, "STDERR")
        )
        
        # Wait for process to complete
        await run_process.wait()

        if pull_process.returncode != 0 or run_process.returncode != 0:
            raise Exception(f"Command failed with exit codes: pull={pull_process.returncode}, run={run_process.returncode}")

        return {'success': True, 'string': instance_id}
    
    except Exception as error:
        print(f"Error processing {instance_id}:", error)
        return {'success': False, 'string': instance_id, 'error': str(error)}


async def process_batch(batch, anthropic_api_key, sidecar_binary_path, run_id, start_index):
    """
    Process a single batch of instance_ids concurrently.
    `start_index` is the index of the first instance in the overall sequence, for logging.
    """
    tasks = [
        run_command_for_instance(instance_id, anthropic_api_key, sidecar_binary_path, run_id)
        for instance_id in batch
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    return results

async def process_all_instances(instances, anthropic_api_key, sidecar_binary_path):
    logger.info(json.dumps({"event": "start_processing", "total_instances": len(instances)}))

    run_id = int(time())  # Could also be a UUID or another unique ID
    batch_size = 20
    total = len(instances)
    completed = 0

    # Break instances into batches of 100 since each batch runs one after the other
    for start in range(0, total, batch_size):
        batch = instances[start:start+batch_size]

        # Log that we're starting a new batch
        logger.info(json.dumps({
            "event": "start_batch",
            "batch_index": start // batch_size,
            "batch_size": len(batch),
            "run_id": run_id
        }))

        # Process this batch concurrently
        results = await process_batch(batch, anthropic_api_key, sidecar_binary_path, run_id, start)

        # Count how many succeeded
        batch_success = sum(r["success"] for r in results)
        batch_failure = len(batch) - batch_success
        completed += len(batch)

        # Log batch summary
        logger.info(json.dumps({
            "event": "end_batch",
            "batch_index": start // batch_size,
            "batch_completed": len(batch),
            "batch_success": batch_success,
            "batch_failure": batch_failure,
            "total_completed": completed,
            "total_remaining": total - completed,
            "run_id": run_id
        }))

    # Final summary after all batches
    logger.info(json.dumps({
        "event": "end_processing",
        "total_instances": total,
        "total_completed": completed,
        "run_id": run_id
    }))

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--anthropic_api_key", type=str, required=True, help="Anthropic API key")
    parser.add_argument("--sidecar_binary_path", type=str, required=True, help="Sidecar binary path")
    parser.add_argument("--instances_file", type=str, required=True, help="Path to file containing instance IDs")
    args = parser.parse_args()

    if not os.path.exists(args.instances_file):
        raise ValueError(f"Instances file not found: {args.instances_file}")

    # Read instance IDs from text file
    with open(args.instances_file, 'r') as f:
        instance_ids = [line.strip() for line in f if line.strip()]

    # Run the main process
    asyncio.run(process_all_instances(instance_ids, args.anthropic_api_key, args.sidecar_binary_path))
