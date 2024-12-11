from google.cloud import storage
import json

def main():
    bucket_name = "swebench_logs"

    # Initialize the client and get the bucket
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    instance_status = {}

    # List all blobs in the bucket under the 'logs/' prefix
    for blob in bucket.list_blobs():
        # The expected path structure is: logs/instance_id/run_id/results.json
        parts = blob.name.split('/')
        # We expect something like ["logs", "<instance_id>", "<run_id>", "results.json"]
        if len(parts) < 4:
            # This might be a directory placeholder or another file structure; skip it
            continue

        filename = parts[-1]
        if filename == 'results.json':
            instance_id = parts[1]
            # Download and parse the JSON data
            data = json.loads(blob.download_as_string())

            # The JSON structure is assumed to have a single key equal to the instance_id
            # and within that key, an object containing a "resolved" field.
            instance_data = data.get(instance_id, {})
            resolved = instance_data.get('resolved', False)

            # If we haven't seen this instance_id yet, initialize to False
            if instance_id not in instance_status:
                instance_status[instance_id] = False

            # If this run_id has resolved = true, mark the instance as success
            if resolved:
                instance_status[instance_id] = True

    # Write the instance_status map to output.json
    with open('output.json', 'w') as f:
        json.dump(instance_status, f, indent=2)

if __name__ == '__main__':
    main()
