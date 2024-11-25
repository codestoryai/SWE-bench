import subprocess
import asyncio
from datetime import datetime

async def run_command_for_string(str_input):
    try:
        # First command: Docker pull - this is Django-specific
        docker_name = str_input.replace('django__django-', 'django_1776_django-')
        docker_image = f"swebench/sweb.eval.x86_64.{docker_name}:v1"
        pull_command = f"docker pull {docker_image}"
        
        print(f"\nPulling Docker image for: {str_input}")
        pull_process = await asyncio.create_subprocess_shell(
            pull_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        pull_stdout, pull_stderr = await pull_process.communicate()
        pull_stdout = pull_stdout.decode()
        pull_stderr = pull_stderr.decode()
        
        # Second command: Run evaluation
        run_command = (
            f"python3 swebench/harness/run_evaluation.py "
            f"--dataset_name dataset/verified/output.jsonl "
            f"--instance_ids {str_input} "
            f"--sidecar_executable_path /Users/zi/codestory/sidecar/target/debug/swe_bench "
            f"--anthropic_api_key BOO" # key needed
        )
        
        print(f"Running evaluation for: {str_input}")
        run_process = await asyncio.create_subprocess_shell(
            run_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        run_stdout, run_stderr = await run_process.communicate()
        run_stdout = run_stdout.decode()
        run_stderr = run_stderr.decode()
        
        # Log both commands' output
        with open('output.log', 'a') as f:
            f.write(
                f"\n=== Processing {str_input} at {datetime.now()} ===\n"
                f"--- Docker Pull ---\n"
                f"Command: {pull_command}\n"
                f"stdout: {pull_stdout}\n"
                f"stderr: {pull_stderr}\n"
                f"Exit code: {pull_process.returncode}\n"
                f"\n--- Evaluation Run ---\n"
                f"Command: {run_command}\n"
                f"stdout: {run_stdout}\n"
                f"stderr: {run_stderr}\n"
                f"Exit code: {run_process.returncode}\n"
                f"=====================================\n"
            )

        if pull_process.returncode != 0 or run_process.returncode != 0:
            raise Exception(f"Command failed with exit codes: pull={pull_process.returncode}, run={run_process.returncode}")

        return {'success': True, 'string': str_input}
    
    except Exception as error:
        print(f"Error processing {str_input}:", error)
        with open('output.log', 'a') as f:
            f.write(
                f"\n!!! Error for: {str_input} at {datetime.now()} !!!\n{str(error)}\n"
            )
        return {'success': False, 'string': str_input, 'error': str(error)}

async def process_strings(strings):
    print('Starting processing...')
    results = []
    
    for str_input in strings:
        result = await run_command_for_string(str_input)
        results.append(result)
        
        # Log summary after each string is processed
        success = result['success']
        status = "✓ Success" if success else "✗ Failed"
        print(f"{status}: {str_input}")
    
    # Print final summary
    successful = sum(1 for r in results if r['success'])
    print(f'\nProcessing complete! {successful}/{len(strings)} successful')

# Example usage
if __name__ == "__main__":
    # strings_to_process = [
    #     "django__django-10880",
    #     "django__django-11211",
    #     "django__django-12193",
    #     "django__django-12713",
    #     "django__django-12741",
    #     "django__django-13028",
    #     "django__django-13279",
    #     "django__django-14017",
    #     "django__django-14238",
    #     "django__django-14434",
    #     "django__django-14539",
    #     "django__django-14608",
    #     "django__django-14672",
    #     "django__django-15022",
    #     "django__django-15103",
    #     "django__django-15128",
    #     "django__django-15278",
    #     "django__django-15380",
    #     "django__django-15561",
    #     "django__django-15741",
    #     "django__django-15814",
    #     "django__django-15863",
    #     "django__django-16100",
    #     "django__django-16116",
    #     "django__django-16136",
    #     "django__django-16485",
    #     "django__django-16899",
    #     "django__django-16901",
    #     "django__django-17087",
    #     "django__django-7530",
    # ]

    strings_to_process = [
        "django__django-15741",
        "django__django-15814",
    ]
    
    asyncio.run(process_strings(strings_to_process)) 