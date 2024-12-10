import os
from google.cloud import storage
from google.cloud.storage import transfer_manager
from concurrent.futures import ThreadPoolExecutor

def upload_trajs_to_gcs(bucket_name, files_map, base_path, workers=8):
    """
    Upload the required traj files for each run_id of each instance_id to GCS.
    The structure on GCS will be: gs://bucket_name/instance_id/run_id/<filename>.
    If any of the 6 required files for a run_id are missing, that run_id is skipped.

    Parameters:
        bucket_name (str): Name of your GCS bucket.
        files_map (dict): The dictionary constructed such that:
                          files_map[instance_id][run_id] = {
                            "trajs": {
                               "mcts_file": ...,
                               "patch.diff": ...,
                               "report.json": ...,
                               "eval.sh": ...,
                               "test_output.txt": ...,
                               "run_instance.log": ...
                            }
                            ...
                          }
        base_path (str): The local base path from which these files were collected.
        workers (int): Number of concurrent upload threads.
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    required_keys = [
        "mcts_file",
        "patch.diff",
        "report.json",
        "eval.sh",
        "test_output.txt",
        "run_instance.log"
    ]

    def upload_one(local_path, blob_name):
        # Upload a single file to the given blob_name
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(local_path)
        print(f"Uploaded {local_path} to gs://{bucket_name}/{blob_name}")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []

        # Iterate over instance_ids
        for instance_id, run_ids_data in files_map.items():
            # Iterate over run_ids for each instance_id
            for run_id, data in run_ids_data.items():
                trajs = data["trajs"]
                # Check if all required files are present
                if any(trajs.get(k) is None for k in required_keys):
                    print(f"Skipping {run_id} under {instance_id} due to missing traj files.")
                    continue

                # All required files are present
                # Schedule uploads of each file
                for key in required_keys:
                    local_file = trajs[key]
                    filename = os.path.basename(local_file)
                    blob_name = f"{instance_id}/{run_id}/{filename}"
                    futures.append(executor.submit(upload_one, local_file, blob_name))

        # Wait for all uploads to complete
        for future in futures:
            # Will raise exception here if any upload failed
            future.result()

    print("All eligible run_ids have been uploaded successfully.")


def upload_directory(bucket_name, source_directory, workers=8):
    """
    Upload all files in the given local directory (including subdirectories) to a GCS bucket.
    Uses concurrent processes for faster bulk uploads.

    Parameters:
        bucket_name (str): Name of your GCS bucket.
        source_directory (str): Path to the local directory you want to upload.
        workers (int): Number of concurrent workers to use. Increase for more concurrency.

    """
    # Initialize the storage client and get the bucket
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    # Collect all files from the directory recursively
    all_files = []
    for root, dirs, files in os.walk(source_directory):
        for file_name in files:
            local_path = os.path.join(root, file_name)
            # Get the file path relative to the source directory
            relative_path = os.path.relpath(local_path, source_directory)
            all_files.append(relative_path)

    # Use the transfer manager to upload the files concurrently
    results = transfer_manager.upload_many_from_filenames(
        bucket, all_files, source_directory=source_directory, max_workers=workers
    )

    # Check the results of each upload
    for name, result in zip(all_files, results):
        if isinstance(result, Exception):
            print(f"Failed to upload {name}: {result}")
        else:
            print(f"Uploaded {name} to gs://{bucket_name}/{name}")