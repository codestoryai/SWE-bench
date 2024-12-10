import os

def collect_files_in_directory(directory):
    """Recursively walk a directory and return a list of all file paths."""
    file_paths = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            file_path = os.path.join(root, f)
            file_paths.append(file_path)
    return file_paths

def find_top_level_mcts_file(top_level_files, run_id):
    """Find the mcts-{run_id}.json file among top-level files."""
    target_filename = f"mcts-{run_id}.json"
    for f in top_level_files:
        if os.path.basename(f) == target_filename:
            return f
    return None

def extract_sidecar_required_files(sidecar_structure):
    """
    From sidecar_structure, extract the required files:
    patch.diff, report.json, eval.sh, test_output.txt, run_instance.log
    Assume they are directly under sidecar_instance_path in the '_files' key.
    """
    required_files = {
        "patch.diff": None,
        "report.json": None,
        "eval.sh": None,
        "test_output.txt": None,
        "run_instance.log": None
    }
    
    # sidecar_structure may look like { subdir_name: [files], '_files': [files], ... }
    sidecar_files = sidecar_structure.get("_files", [])
    
    # Fill in the required_files if found in sidecar_files
    for f in sidecar_files:
        fname = os.path.basename(f)
        if fname in required_files:
            required_files[fname] = f
    
    return required_files

def build_files_map(base_path):
    # The new structure we want:
    # {
    #   instance_id: {
    #       run_id: {
    #           "top_level": [...],
    #           "sidecar": {...},
    #           "trajs": {
    #               "mcts_file": ...,
    #               "patch.diff": ...,
    #               "report.json": ...,
    #               "eval.sh": ...,
    #               "test_output.txt": ...,
    #               "run_instance.log": ...
    #           }
    #       },
    #       ...
    #   },
    #   ...
    # }
    
    files_map = {}
    
    # Iterate over potential run_id directories
    for entry in os.listdir(base_path):
        run_id_dir = os.path.join(base_path, entry)
        # Skip if not a directory
        if not os.path.isdir(run_id_dir):
            continue
        
        # Check if this directory contains a sidecar subdir
        sidecar_dir = os.path.join(run_id_dir, "sidecar")
        if not os.path.isdir(sidecar_dir):
            # Not a run_id directory (as per given structure), skip
            continue
        
        run_id = os.path.basename(run_id_dir)
        
        # Identify top-level instance_id directories (excluding sidecar)
        top_level_instance_ids = [
            d for d in os.listdir(run_id_dir)
            if d != "sidecar" and os.path.isdir(os.path.join(run_id_dir, d))
        ]
        
        # For each instance_id found at the top-level, check the corresponding sidecar path
        for instance_id in top_level_instance_ids:
            top_level_path = os.path.join(run_id_dir, instance_id)
            sidecar_instance_path = os.path.join(sidecar_dir, instance_id)
            
            # If the sidecar instance directory doesn't exist, handle gracefully
            if not os.path.isdir(sidecar_instance_path):
                print(f"Warning: Sidecar directory for {instance_id} not found under {run_id}")
                continue
            
            # Collect all top-level instance_id files (recursively)
            top_level_files = collect_files_in_directory(top_level_path)
            
            # Build the sidecar_structure
            sidecar_structure = {}
            for subentry in os.listdir(sidecar_instance_path):
                sub_path = os.path.join(sidecar_instance_path, subentry)
                if os.path.isdir(sub_path):
                    # This is a subdirectory inside sidecar/instance_id
                    sidecar_structure[subentry] = collect_files_in_directory(sub_path)
                else:
                    # Files directly under sidecar/instance_id
                    sidecar_structure.setdefault("_files", []).append(sub_path)
            
            # Extract the required files
            mcts_file = find_top_level_mcts_file(top_level_files, run_id)
            sidecar_required_files = extract_sidecar_required_files(sidecar_structure)
            
            # Ensure this instance_id key exists in files_map
            if instance_id not in files_map:
                files_map[instance_id] = {}
            
            # Construct the final dictionary for this run_id
            files_map[instance_id][run_id] = {
                "top_level": top_level_files,
                "sidecar": sidecar_structure,
                "trajs": {
                    "mcts_file": mcts_file,
                    "patch.diff": sidecar_required_files["patch.diff"],
                    "report.json": sidecar_required_files["report.json"],
                    "eval.sh": sidecar_required_files["eval.sh"],
                    "test_output.txt": sidecar_required_files["test_output.txt"],
                    "run_instance.log": sidecar_required_files["run_instance.log"]
                }
            }
    
    return files_map

# Example usage:
# base_path = "/path/to/base_dir"
# result = build_files_map(base_path)
# print(result)
