import json

from swebench.gcp.upload import upload_trajs_to_gcs
from swebench.gcp.log_collector import build_files_map

bucket_name = "swebench_logs"

root_dir = "/Users/zi/codestory/SWE-bench/logs/run_evaluation"

result = build_files_map(root_dir)
json_result = json.dumps(result, indent=4)

with open("sidecar.logs.json", "w") as f:
    f.write(json_result)

upload_trajs_to_gcs(bucket_name, result, root_dir)