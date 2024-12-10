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

async def run_command_for_instance(instance_id, anthropic_api_key, openrouter_api_key, sidecar_binary_path, run_id, semaphore):
    async with semaphore:
        try:
            # First command: Docker pull - this is Django-specific
            if instance_id.startswith('django'):
                docker_name = instance_id.replace('django__django-', 'django_1776_django-')
            if instance_id.startswith('astropy'):
                docker_name = instance_id.replace('astropy__astropy-', 'astropy_1776_astropy-')
            if instance_id.startswith('matplotlib'):
                docker_name = instance_id.replace('matplotlib__matplotlib-', 'matplotlib_1776_matplotlib-')
            if instance_id.startswith('mwaskom'):
                docker_name = instance_id.replace('mwaskom__seaborn-', 'mwaskom_1776_seaborn-')
            if instance_id.startswith('pallets__flask'):
                docker_name = instance_id.replace('pallets__flask-', 'pallets_1776_flask-')
            if instance_id.startswith('pydata__xarray-'):
                docker_name = instance_id.replace('pydata__xarray-', 'pydata_1776_xarray-')
            if instance_id.startswith('pylint-dev__pylint'):
                docker_name = instance_id.replace('pylint-dev__pylint-', 'pylint-dev_1776_pylint-')
            if instance_id.startswith('sympy'):
                docker_name = instance_id.replace('sympy__sympy-', 'sympy_1776_sympy-')
            if instance_id.startswith('scikit-learn__scikit-learn-'):
                docker_name = instance_id.replace('scikit-learn__scikit-learn-', 'scikit-learn_1776_scikit-learn-')
            if instance_id.startswith('psf__requests-'):
                docker_name = instance_id.replace('psf__requests-', 'psf_1776_requests-')
            if instance_id.startswith('pydata__xarray-'):
                docker_name = instance_id.replace('pydata__xarray-', 'pydata_1776_xarray-')
            if instance_id.startswith('sphinx-doc__sphinx-'):
                docker_name = instance_id.replace('sphinx-doc__sphinx-', 'sphinx-doc_1776_sphinx-')
            if instance_id.startswith('pallets__flask'):
                docker_name = instance_id.replace('pallets__flask-', 'pallets_1776_flask-')
            
            docker_image = f"swebench/sweb.eval.x86_64.{docker_name}:v1"
            print(f"\nPulling Docker image: {docker_image}")
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

            key_command = ""
            if anthropic_api_key is not None:
                key_command = f"--anthropic_api_key {anthropic_api_key} "
            elif openrouter_api_key is not None:
                key_command = f"--openrouter_api_key {openrouter_api_key} "
            
            # Second command: Run evaluation
            run_command = (
                f"python3 -u swebench/harness/run_evaluation.py "
                f"--dataset_name dataset/verified/output.jsonl "
                f"--instance_ids {instance_id} "
                f"--sidecar_executable_path {sidecar_binary_path} "
                f"{key_command}"
                f"--run_id {run_id} "
                f"--output_log_path {output_log_path} "
                f"--traj_search_space 1"
            )

            print(run_command)
            
            print(f"Running evaluation for: {instance_id}")
            run_process = await asyncio.create_subprocess_shell(
                run_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=4**20,  # for example, set a 1MB limit
            )
            
            async def read_stream(stream, name):
                async for line in stream:
                    decoded_line: str = line.decode()
                    if decoded_line.strip():
                        print(f"PYTHON SCRIPT {name}: {decoded_line.rstrip()}")
            
            await asyncio.gather(
                read_stream(run_process.stdout, "STDOUT"),
                read_stream(run_process.stderr, "STDERR")
            )
            
            await run_process.wait()

            if pull_process.returncode != 0 or run_process.returncode != 0:
                raise Exception(f"Command failed with exit codes: pull={pull_process.returncode}, run={run_process.returncode}")

            return {'success': True, 'string': instance_id}
        
        except Exception as error:
            print(f"Error processing {instance_id}:", error)
            return {'success': False, 'string': instance_id, 'error': str(error)}


async def process_all_instances(instances, anthropic_api_key, openrouter_api_key, sidecar_binary_path):
    logger.info(json.dumps({"event": "start_processing", "total_instances": len(instances)}))

    run_id = int(time())
    total = len(instances)
    completed = 0
    success_count = 0
    failure_count = 0

    # Set the maximum concurrency to 10
    concurrency_limit = 10
    semaphore = asyncio.Semaphore(concurrency_limit)
    
    # Create all tasks upfront
    tasks = [
        asyncio.create_task(
            run_command_for_instance(
                instance_id=inst,
                anthropic_api_key=anthropic_api_key,
                openrouter_api_key=openrouter_api_key,
                sidecar_binary_path=sidecar_binary_path,
                run_id=run_id,
                semaphore=semaphore
            )
        )
        for inst in instances
    ]

    # Process tasks as they complete
    for future in asyncio.as_completed(tasks):
        result = await future
        completed += 1
        if result["success"]:
            success_count += 1
        else:
            failure_count += 1

        # Incremental logging could be done here
        logger.info(json.dumps({
            "event": "task_complete",
            "instance_id": result["string"],
            "success": result["success"],
            "completed": completed,
            "remaining": total - completed,
            "run_id": run_id
        }))

    # Final summary after all tasks
    logger.info(json.dumps({
        "event": "end_processing",
        "total_instances": total,
        "total_completed": completed,
        "total_success": success_count,
        "total_failure": failure_count,
        "run_id": run_id
    }))


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--anthropic_api_key", type=str, required=True, help="Anthropic API key")
    parser.add_argument("--openrouter_api_key", type=str, required=False, help="Open Router API key")
    parser.add_argument("--sidecar_binary_path", type=str, required=True, help="Sidecar binary path")
    parser.add_argument("--instances_file", type=str, required=True, help="Path to file containing instance IDs")
    args = parser.parse_args()

    if not os.path.exists(args.instances_file):
        raise ValueError(f"Instances file not found: {args.instances_file}")

    with open(args.instances_file, 'r') as f:
        instance_ids = [line.strip() for line in f if line.strip()]

    asyncio.run(process_all_instances(instance_ids, args.anthropic_api_key, args.openrouter_api_key, args.sidecar_binary_path))
