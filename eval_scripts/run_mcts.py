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
            f"--sidecar_executable_path /home/z/sidecar/target/debug/swe_bench_mcts "
            f"--anthropic_api_key " # key needed
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

    instance_ids = [
        "django__django-10097",
        "django__django-10554",
        "django__django-10999",
        "django__django-11087",
        "django__django-11138",
        "django__django-11141",
        "django__django-11149",
        "django__django-11206",
        "django__django-11239",
        "django__django-11265",
        "django__django-11299",
        "django__django-11333",
        "django__django-11400",
        "django__django-11433",
        "django__django-11477",
        "django__django-11490",
        "django__django-11532",
        "django__django-11555",
        "django__django-11728",
        "django__django-11734",
        "django__django-11740",
        "django__django-11790",
        "django__django-11820",
        "django__django-11848",
        "django__django-11885",
        "django__django-11964",
        "django__django-12039",
        "django__django-12125",
        "django__django-12262",
        "django__django-12273",
        "django__django-12308",
        "django__django-12325",
        "django__django-12406",
        "django__django-12663",
        "django__django-12754",
        "django__django-12774",
        "django__django-12965",
        "django__django-13023",
        "django__django-13112",
        "django__django-13121",
        "django__django-13128",
        "django__django-13158",
        "django__django-13195",
        "django__django-13212",
        "django__django-13297",
        "django__django-13344",
        "django__django-13346",
        "django__django-13406",
        "django__django-13449",
        "django__django-13512",
        "django__django-13513",
        "django__django-13551",
        "django__django-13568",
        "django__django-13794",
        "django__django-13807",
        "django__django-13810",
        "django__django-13925",
        "django__django-14011",
        "django__django-14034",
        "django__django-14053",
        "django__django-14122",
        "django__django-14140",
        "django__django-14155",
        "django__django-14170",
        "django__django-14311",
        "django__django-14315",
        "django__django-14351",
        "django__django-14376",
        "django__django-14404",
        "django__django-14500",
        "django__django-14534",
        "django__django-14559",
        "django__django-14580",
        "django__django-14631",
        "django__django-14725",
        "django__django-14771",
        "django__django-14792",
        "django__django-15037",
        "django__django-15098",
        "django__django-15127",
        "django__django-15161",
        "django__django-15252",
        "django__django-15280",
        "django__django-15375",
        "django__django-15503",
        "django__django-15554",
        "django__django-15563",
        "django__django-15629",
        "django__django-15695",
        "django__django-15732",
        "django__django-15916",
        "django__django-15930",
        "django__django-15957",
        "django__django-15973",
        "django__django-16082",
        "django__django-16256",
        "django__django-16263",
        "django__django-16315",
        "django__django-16454",
        "django__django-16502",
        "django__django-16560",
        "django__django-16631",
        "django__django-16642",
        "django__django-16661",
        "django__django-16667",
        "django__django-16877",
        "django__django-16938",
        "django__django-16950",
        "django__django-17084",
    ]
    
    asyncio.run(process_strings(instance_ids)) 