from __future__ import annotations
import asyncio
from datetime import datetime
import os
import random
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import docker
import json
import resource
import time
import signal
import traceback

from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import docker.models
import docker.models.containers
from tqdm import tqdm

from swebench.editor.setup_repo import checkout_repo
from swebench.editor.sidecar import sidecar_run
from swebench.google_sheets import update_instance_run_status
from swebench.harness.constants import (
    APPLY_PATCH_FAIL,
    APPLY_PATCH_PASS,
    INSTANCE_IMAGE_BUILD_DIR,
    KEY_INSTANCE_ID,
    KEY_MODEL,
    KEY_PREDICTION,
    MAP_REPO_VERSION_TO_SPECS,
    RUN_EVALUATION_LOG_DIR,
    SWEbenchInstance,
)
from swebench.harness.docker_utils import (
    exec_run_with_timeout_and_error_code,
    exec_run_with_timeout_and_error_code_only_stdout,
    remove_image,
    copy_to_container,
    exec_run_with_timeout,
    cleanup_container,
    list_images,
    should_remove,
    clean_images,
)
from swebench.harness.docker_build import (
    BuildImageError,
    build_container,
    build_env_images,
    close_logger,
    setup_logger,
)
from swebench.editor import (
    http_implementation,
    webserver,
)
from swebench.harness.grading import get_eval_report
from swebench.harness.test_spec import make_eval_script_for_terminal_command, make_eval_script_for_test_files, make_test_spec, TestSpec
from swebench.harness.utils import load_swebench_dataset, str2bool
from swebench.utils import get_parea_link


# Contains all the running docker container which are in the dev-loop and their reference
DEV_DOCKER_CONTAINERS: List[docker.models.containers.Container] = []

def signal_handler(sig, frame):
    for container in DEV_DOCKER_CONTAINERS:
        print("Stopping {}", container.id)
        container.stop()
        print("Stopped {}", container.id)

signal.signal(signal.SIGINT, signal_handler)


class EvaluationError(Exception):
    def __init__(self, instance_id, message, logger):
        super().__init__(message)
        self.super_str = super().__str__()
        self.instance_id = instance_id
        self.log_file = logger.log_file
        self.logger = logger

    def __str__(self):
        return (
            f"Evaluation error for {self.instance_id}: {self.super_str}\n"
            f"Check ({self.log_file}) for more information."
        )

def run_instance_for_test_path(
    test_spec: TestSpec,
    instance: SWEbenchInstance,
    git_drname: str,
    model_name_or_path: str,
    client: docker.DockerClient,
    run_id: str,
    test_files: List[str],
    container: docker.models.containers.Container,
    timeout: int | None = None,
) -> Tuple[str, Dict[str, Any], Path, int]:
    # Set up logging directory
    instance_id = test_spec.instance_id
    # This is the full path
    model_name_or_path = model_name_or_path.replace("/", "__")
    log_dir = RUN_EVALUATION_LOG_DIR / run_id / model_name_or_path / instance_id / "test_output" / str(int(time.time()))
    log_dir.mkdir(parents=True, exist_ok=True)

    # Link the image build dir in the log dir
    build_dir = INSTANCE_IMAGE_BUILD_DIR / test_spec.instance_image_key.replace(":", "__")
    image_build_link = log_dir / "image_build_dir"
    if not image_build_link.exists():
        try:
            # link the image build dir in the log dir
            image_build_link.symlink_to(build_dir.absolute(), target_is_directory=True)
        except:
            # some error, idk why
            pass
    log_file = log_dir / "run_instance.log"

    # Set up report file + logger
    report_path = log_dir / "report.json"
    if report_path.exists():
        return instance_id, json.loads(report_path.read_text())
    logger = setup_logger(instance_id, log_file)


    # Create the git diff as a patch string
    try:
        # first git add all the files which are in the git_drname
        _ = subprocess.check_output(["git", "add", "."], cwd=git_drname).decode("utf-8")
        git_diff_cached_output = subprocess.check_output(
            ["git", "diff", "--cached"], cwd=git_drname
        ).decode("utf-8")
        git_diff_normal = subprocess.check_output(
            ["git", "diff"], cwd=git_drname
        ).decode("utf-8")
        pred = {
            "model_patch": git_diff_cached_output + git_diff_normal,
            "model_name_or_path": model_name_or_path,
            "instance_id": instance_id,
        }
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to create git diff: {e}")
        raise EvaluationError(instance_id, "Failed to create git diff", logger)

    try:
        logger.info(f"Container for {instance_id} already started: {container.id}")

        # Copy model prediction as patch file to container
        patch_file = Path(log_dir / "patch.diff")
        patch_file.write_text(pred["model_patch"] or "")
        logger.info(
            f"Intermediate patch for {instance_id} written to {patch_file}, now applying to container..."
        )
        # Stash all the recent changes so we apply a clean patch
        container.exec_run("git clean -fdX", workdir="/testbed", user="root")
        container.exec_run("git clean -fdx", workdir="/testbed", user="root")
        container.exec_run("git add . && git stash", workdir="/testbed", user="root")
        # Run git reset to clean up the container repo properly
        container.exec_run(f"git reset --hard {instance['base_commit']}", workdir="/testbed", user="root")

        copy_to_container(container, patch_file, Path("/tmp/patch.diff"))

        # Attempt to apply patch to container
        val = container.exec_run(
            "git apply -v /tmp/patch.diff",
            workdir="/testbed",
            user="root",
        )
        if val.exit_code != 0:
            logger.info(f"Failed to apply patch to container, trying again...")
            
            # try "patch --batch --fuzz=5 -p1 -i {patch_path}" to try again
            val = container.exec_run(
                "patch --batch --fuzz=5 -p1 -i /tmp/patch.diff",
                workdir="/testbed",
                user="root",
            )
            if val.exit_code != 0:
                logger.info(f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8')}")
                raise EvaluationError(
                    instance_id,
                    f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8')}",
                    logger,
                )
            else:
                logger.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8')}")
        else:
            logger.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8')}")

        # Get git diff before running eval script
        git_diff_output_before = (
            container.exec_run("git diff", workdir="/testbed").output.decode("utf-8").strip()
        )
        logger.info(f"Git diff before:\n{git_diff_output_before}")

        # Creating the eval script
        eval_file = Path(log_dir / "eval.sh")

        # The following is taken from the TestSpec generation but we are reusing the logic
        # here so we can run the tests and any tests as we want
        eval_script_list = make_eval_script_for_test_files(
            env_name="testbed",
            repo_directory="/testbed",
            files=test_files,
            git_drname=git_drname,
            instance=instance,
            specs=MAP_REPO_VERSION_TO_SPECS[instance['repo']][instance['version']],
        )
        eval_script = "\n".join(["#!/bin/bash", "set -uxo pipefail"] + eval_script_list) + "\n"
        eval_file.write_text(eval_script)
        logger.info(
            f"Eval script for {instance_id} written to {eval_file}; copying to container..."
        )
        copy_to_container(container, eval_file, Path("/eval.sh"))

        # Run eval script, write output to logs
        test_output, timed_out, total_runtime, exit_code = exec_run_with_timeout_and_error_code(container, "/bin/bash /eval.sh", timeout)
        test_output_path = log_dir / "test_output.txt"
        logger.info(f'Test runtime: {total_runtime:_.2f} seconds')
        logger.info(f'Test run exit code: {exit_code}')
        with open(test_output_path, "w") as f:
            f.write(test_output)
            logger.info(f"Test output for {instance_id} written to {test_output_path}")
            if timed_out:
                f.write(f"\n\nTimeout error: {timeout} seconds exceeded.")
                raise EvaluationError(
                    instance_id,
                    f"Test timed out after {timeout} seconds.",
                    logger,
                )

        # Get git diff after running eval script
        git_diff_output_after = (
            container.exec_run("git diff", workdir="/testbed").output.decode("utf-8").strip()
        )

        # Check if git diff changed after running eval script
        logger.info(f"Git diff after:\n{git_diff_output_after}")
        if git_diff_output_after != git_diff_output_before:
            logger.info(f"Git diff changed after running eval script")

        # Get report from test output
        logger.info(f"Grading answer for {instance_id}...")
        report = get_eval_report(
            test_spec=test_spec,
            prediction=pred,
            log_path=test_output_path,
            include_tests_status=True,
            instance=instance,
        )
        logger.info(
            f"report: {report}\n"
            f"Result for {instance_id}: resolved: {report[instance_id]['resolved']}"
        )

        # Write report to report.json
        with open(report_path, "w") as f:
            f.write(json.dumps(report, indent=4))
        return instance_id, report, test_output_path, exit_code
    except EvaluationError as e:
        error_msg = traceback.format_exc()
        logger.info(error_msg)
        print(e)
    except BuildImageError as e:
        error_msg = traceback.format_exc()
        logger.info(error_msg)
        print(e)
    except Exception as e:
        error_msg = (f"Error in evaluating model for {instance_id}: {e}\n"
                     f"{traceback.format_exc()}\n"
                     f"Check ({logger.log_file}) for more information.")
        logger.error(error_msg)
    finally:
        # Cleanup the docker over here after the test run
        container.exec_run("git clean -fdX", workdir="/testbed", user="root")
        container.exec_run("git clean -fdx", workdir="/testbed", user="root")
        container.exec_run("git add . && git stash", workdir="/testbed", user="root")
        pass
        # No need to pause anything as we are reusing the resources
        # during a single run
        # Remove instance container + image, close logger
        # cleanup_container(client, container, logger)
        # close_logger(logger)
    return


def start_debug_environment(
    test_spec: TestSpec,
    client: docker.DockerClient,
    run_id: str,
) -> Tuple[docker.models.containers.Container, Path]:
    """
    Starts a debug container which we can use for the agent to freely run
    commands and other things, this also sets up the environment properly
    """
    log_dir = RUN_EVALUATION_LOG_DIR / run_id / test_spec.instance_id / "debug_environment"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "run_instance.log"
    logger = setup_logger(test_spec.instance_id, log_file)
    
    # we really balling here
    max_retries = 10
    for attempt in range(max_retries):
        try:
            container = build_container(test_spec, client, run_id, logger, False, False)
            # Starts a debug container which we can use as our debug environment
            container.start()
            return [container, log_dir]
        except BuildImageError as e:
            if "Conflict" in str(e) and attempt < max_retries - 1:
                run_id_as_int = int(run_id)
                run_id_as_int += random.randint(1,1000)
                run_id = str(run_id_as_int)
                logger.info(f"Container name conflict, retrying with new run_id: {run_id}")
                continue
            raise  # Re-raise the exception if we've exhausted retries or it's not a conflict error

def run_terminal_command(
    test_spec: TestSpec,
    instance: SWEbenchInstance,
    command: str,
    run_id: str,
    model_name_or_path: str,
    git_drname: str,
    container: docker.models.containers.Container,
    log_directory: Path,
    timeout: int | None = None,
) -> str:
    """
    Runs the terminal command on a persistent container which is running
    This makes sure that we are able to reuse the same container over and over again
    instead of spinning up a new one all the time
    """


    # First create the logger for the output
    # Set up logging directory
    instance_id = test_spec.instance_id
    # This is the full path
    model_name_or_path = model_name_or_path.replace("/", "__")
    log_dir = RUN_EVALUATION_LOG_DIR / run_id / model_name_or_path / instance_id / "terminal_output" / str(int(time.time()))
    log_dir.mkdir(parents=True, exist_ok=True)

    # Link the image build dir in the log dir
    build_dir = INSTANCE_IMAGE_BUILD_DIR / test_spec.instance_image_key.replace(":", "__")
    image_build_link = log_dir / "image_build_dir"
    if not image_build_link.exists():
        try:
            # link the image build dir in the log dir
            image_build_link.symlink_to(build_dir.absolute(), target_is_directory=True)
        except:
            # some error, idk why
            pass
    log_file = log_dir / "run_instance.log"

    logger = setup_logger(instance_id, log_file)

    # Second we stash all the pending changes which we might have done
    container.exec_run("git clean -fdX", workdir="/testbed", user="root")
    container.exec_run("git clean -fdx", workdir="/testbed", user="root")
    container.exec_run("git add . && git stash", workdir="/testbed", user="root")
    # Run git reset to clean up the container repo properly
    container.exec_run(f"git reset --hard {instance['base_commit']}", workdir="/testbed", user="root")
    container_git_diff = container.exec_run("git status", workdir="/testbed", user="root")
    print('git status container', container_git_diff.output.decode('utf-8'))
    container_git_diff = container.exec_run("git stash show -p", workdir="/testbed", user="root")
    print('git stash show -p inside container', container_git_diff.output.decode('utf-8'))
    
    
    # Now we get the patch file we are interested in
    # - First add all the files which are there to the git tracking so we can track them
    _ = subprocess.check_output(["git", "add", "."], cwd=git_drname).decode("utf-8")
    git_diff_cached_output = subprocess.check_output(
        ["git", "diff", "--cached"], cwd=git_drname
    ).decode("utf-8")
    git_diff_normal = subprocess.check_output(
        ["git", "diff"], cwd=git_drname
    ).decode("utf-8")
    patch_file = Path(log_directory / "patch.diff")
    patch_file.write_text(git_diff_cached_output + git_diff_normal)
    print("git_diff_output::terminal", git_diff_cached_output + git_diff_normal)
    copy_to_container(container, patch_file, Path("/tmp/patch.diff"))
    # Attempt to apply patch to container
    val = container.exec_run(
        "git apply -v /tmp/patch.diff",
        # "git apply --allow-empty -v /tmp/patch.diff",
        workdir="/testbed",
        user="root",
    )
    print("git apply patch output", val.output.decode('utf-8'))
    if val.exit_code != 0:
        print(f"Failed to apply patch to container, trying again...")
        
        # try "patch --batch --fuzz=5 -p1 -i {patch_path}" to try again
        val = container.exec_run(
            "patch --batch --fuzz=5 -p1 -i /tmp/patch.diff",
            workdir="/testbed",
            user="root",
        )
        if val.exit_code != 0:
            print(f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8')}")
            raise KeyError()
        else:
            print(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8')}")
    else:
        print(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8')}")
    
    terminal_file = Path(log_dir / "eval.sh")

    terminal_script_list = make_eval_script_for_terminal_command(
        instance=instance,
        specs=MAP_REPO_VERSION_TO_SPECS[instance['repo']][instance['version']],
        env_name="testbed",
        repo_directory="/testbed",
        terminal_command=command,
        git_drname=git_drname,
    )
    eval_script = "\n".join(["#!/bin/bash", "set -uxo pipefail"] + terminal_script_list) + "\n"
    terminal_file.write_text(eval_script)
    logger.info(f"Terminal script for {instance_id} written to {terminal_file}; copying to container...")
    copy_to_container(container=container, src=terminal_file, dst=Path("/eval.sh"))

    # Run the script and then write the output to the logs
    terminal_output, timed_out, total_runtime, exit_code = exec_run_with_timeout_and_error_code_only_stdout(container, "/bin/bash /eval.sh", timeout)
    terminal_output_path = log_dir / "terminal_output.txt"
    with open(terminal_output_path, "w") as f:
        f.write(terminal_output)
    
    # Reset the docker over here so its clean
    container.exec_run("git clean -fdX", workdir="/testbed", user="root")
    container.exec_run("git clean -fdx", workdir="/testbed", user="root")
    container.exec_run("git add . && git stash", workdir="/testbed", user="root")
    # Run git reset to clean up the container repo properly
    container.exec_run(f"git reset --hard {instance['base_commit']}", workdir="/testbed", user="root")
    return terminal_output


def run_instance(
        test_spec: TestSpec,
        pred: dict,
        rm_image: bool,
        force_rebuild: bool,
        client: docker.DockerClient,
        run_id: str,
        instance: Optional[SWEbenchInstance],
        timeout: int | None = None,
    ):
    """
    Run a single instance with the given prediction.

    Args:
        test_spec (TestSpec): TestSpec instance
        pred (dict): Prediction w/ model_name_or_path, model_patch, instance_id
        rm_image (bool): Whether to remove the image after running
        force_rebuild (bool): Whether to force rebuild the image
        client (docker.DockerClient): Docker client
        run_id (str): Run ID
        timeout (int): Timeout for running tests
    """
    # Set up logging directory
    instance_id = test_spec.instance_id
    model_name_or_path = pred.get("model_name_or_path", "None").replace("/", "__")
    log_dir = RUN_EVALUATION_LOG_DIR / run_id / model_name_or_path / instance_id
    log_dir.mkdir(parents=True, exist_ok=True)

    # Link the image build dir in the log dir
    build_dir = INSTANCE_IMAGE_BUILD_DIR / test_spec.instance_image_key.replace(":", "__")
    image_build_link = log_dir / "image_build_dir"
    if not image_build_link.exists():
        try:
            # link the image build dir in the log dir
            image_build_link.symlink_to(build_dir.absolute(), target_is_directory=True)
        except:
            # some error, idk why
            pass
    log_file = log_dir / "run_instance.log"

    # Set up report file + logger
    report_path = log_dir / "report.json"
    if report_path.exists():
        return instance_id, json.loads(report_path.read_text())
    logger = setup_logger(instance_id, log_file)

    # Run the instance
    container = None
    try:
        # Build + start instance container (instance image should already be built)
        container = build_container(test_spec, client, run_id, logger, rm_image, force_rebuild)
        container.start()
        logger.info(f"Container for {instance_id} started: {container.id}")

        # Copy model prediction as patch file to container
        patch_file = Path(log_dir / "patch.diff")
        patch_file.write_text(pred["model_patch"] or "")
        logger.info(
            f"Intermediate patch for {instance_id} written to {patch_file}, now applying to container..."
        )
        copy_to_container(container, patch_file, Path("/tmp/patch.diff"))

        # Attempt to apply patch to container
        val = container.exec_run(
            "git apply --allow-empty -v /tmp/patch.diff",
            workdir="/testbed",
            user="root",
        )
        if val.exit_code != 0:
            logger.info(f"Failed to apply patch to container, trying again...")
            
            # try "patch --batch --fuzz=5 -p1 -i {patch_path}" to try again
            val = container.exec_run(
                "patch --batch --fuzz=5 -p1 -i /tmp/patch.diff",
                workdir="/testbed",
                user="root",
            )
            if val.exit_code != 0:
                logger.info(f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8')}")
                raise EvaluationError(
                    instance_id,
                    f"{APPLY_PATCH_FAIL}:\n{val.output.decode('utf-8')}",
                    logger,
                )
            else:
                logger.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8')}")
        else:
            logger.info(f"{APPLY_PATCH_PASS}:\n{val.output.decode('utf-8')}")

        # Get git diff before running eval script
        git_diff_output_before = (
            container.exec_run("git diff", workdir="/testbed").output.decode("utf-8").strip()
        )
        logger.info(f"Git diff before:\n{git_diff_output_before}")

        eval_file = Path(log_dir / "eval.sh")
        eval_file.write_text(test_spec.eval_script)
        logger.info(
            f"Eval script for {instance_id} written to {eval_file}; copying to container..."
        )
        copy_to_container(container, eval_file, Path("/eval.sh"))

        # Run eval script, write output to logs
        test_output, timed_out, total_runtime = exec_run_with_timeout(container, "/bin/bash /eval.sh", timeout)
        test_output_path = log_dir / "test_output.txt"
        logger.info(f'Test runtime: {total_runtime:_.2f} seconds')
        with open(test_output_path, "w") as f:
            f.write(test_output)
            logger.info(f"Test output for {instance_id} written to {test_output_path}")
            if timed_out:
                f.write(f"\n\nTimeout error: {timeout} seconds exceeded.")
                raise EvaluationError(
                    instance_id,
                    f"Test timed out after {timeout} seconds.",
                    logger,
                )

        # Get git diff after running eval script
        git_diff_output_after = (
            container.exec_run("git diff", workdir="/testbed").output.decode("utf-8").strip()
        )

        # Check if git diff changed after running eval script
        logger.info(f"Git diff after:\n{git_diff_output_after}")
        if git_diff_output_after != git_diff_output_before:
            logger.info(f"Git diff changed after running eval script")

        # Get report from test output
        logger.info(f"Grading answer for {instance_id}...")
        report = get_eval_report(
            test_spec=test_spec,
            prediction=pred,
            log_path=test_output_path,
            include_tests_status=True,
            instance=instance,
        )
        logger.info(
            f"report: {report}\n"
            f"Result for {instance_id}: resolved: {report[instance_id]['resolved']}"
        )

        # Write report to report.json
        with open(report_path, "w") as f:
            f.write(json.dumps(report, indent=4))
        return instance_id, report
    except EvaluationError as e:
        error_msg = traceback.format_exc()
        logger.info(error_msg)
        print(e)
    except BuildImageError as e:
        error_msg = traceback.format_exc()
        logger.info(error_msg)
        print(e)
    except Exception as e:
        error_msg = (f"Error in evaluating model for {instance_id}: {e}\n"
                     f"{traceback.format_exc()}\n"
                     f"Check ({logger.log_file}) for more information.")
        logger.error(error_msg)
    finally:
        # Remove instance container + image, close logger
        cleanup_container(client, container, logger)
        if rm_image:
            remove_image(client, test_spec.instance_image_key, logger)
        close_logger(logger)
    return


def run_instances(
        predictions: dict,
        instances: list,
        cache_level: str,
        clean: bool,
        force_rebuild: bool,
        max_workers: int,
        run_id: str,
        timeout: int,
    ):
    """
    Run all instances for the given predictions in parallel.

    Args:
        predictions (dict): Predictions dict generated by the model
        instances (list): List of instances
        cache_level (str): Cache level
        clean (bool): Clean images above cache level
        force_rebuild (bool): Force rebuild images
        max_workers (int): Maximum number of workers
        run_id (str): Run ID
        timeout (int): Timeout for running tests
    """
    client = docker.from_env()
    test_specs = list(map(make_test_spec, instances))

    # print number of existing instance images
    instance_image_ids = {x.instance_image_key for x in test_specs}
    existing_images = {
        tag for i in client.images.list(all=True)
        for tag in i.tags if tag in instance_image_ids
    }
    if not force_rebuild and len(existing_images):
        print(f"Found {len(existing_images)} existing instance images. Will reuse them.")

    # run instances in parallel
    print(f"Running {len(instances)} instances...")
    with tqdm(total=len(instances), smoothing=0) as pbar:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Create a future for running each instance
            futures = {
                executor.submit(
                    run_instance,
                    test_spec,
                    predictions[test_spec.instance_id],
                    should_remove(
                        test_spec.instance_image_key,
                        cache_level,
                        clean,
                        existing_images,
                    ),
                    force_rebuild,
                    client,
                    run_id,
                    # Pass instance id as None over here
                    None,
                    timeout,
                ): None
                for test_spec in test_specs
            }
            # Wait for each future to complete
            for future in as_completed(futures):
                pbar.update(1)
                try:
                    # Update progress bar, check if instance ran successfully
                    future.result()
                except Exception as e:
                    traceback.print_exc()
                    continue
    print("All instances run.")


def get_dataset_for_instances(
    dataset_name: str,
    split: str,
    instance_ids: list,
)-> list[SWEbenchInstance]:
    """
    Returns the instances which are part of the instance-ids and exludes any predictions
    """
    dataset = load_swebench_dataset(dataset_name, split)
    filtered_dataset = []
    for data_part in dataset:
        data_instance_id = data_part["instance_id"]
        instance_id_contained = False
        for instance_id in instance_ids:
            if instance_id == data_instance_id:
                instance_id_contained = True
        
        if instance_id_contained:
            filtered_dataset.append(data_part)

    return filtered_dataset
    

def get_dataset_from_preds(
        dataset_name: str,
        split: str,
        instance_ids: list,
        predictions: dict,
        run_id: str,
        exclude_completed: bool = True
    ):
    """
    Return only instances that have predictions and are in the dataset.
    If instance_ids is provided, only return instances with those IDs.
    If exclude_completed is True, only return instances that have not been run yet.
    """
    # load dataset
    dataset = load_swebench_dataset(dataset_name, split)
    dataset_ids = {i[KEY_INSTANCE_ID] for i in dataset}

    if instance_ids:
        # check that all instance IDs have predictions
        missing_preds = set(instance_ids) - set(predictions.keys())
        if missing_preds:
            print(f"Warning: Missing predictions for {len(missing_preds)} instance IDs.")
    
    # check that all prediction IDs are in the dataset
    prediction_ids = set(predictions.keys())
    if prediction_ids - dataset_ids:
        raise ValueError(
            (
                "Some prediction IDs not found in dataset!"
                f"\nMissing IDs:\n{' '.join(prediction_ids - dataset_ids)}"
            )
        )
    if instance_ids:
        dataset = [i for i in dataset if i[KEY_INSTANCE_ID] in instance_ids]

    # check which instance IDs have already been run
    completed_ids = set()
    for instance in dataset:
        if instance[KEY_INSTANCE_ID] not in prediction_ids:
            # skip instances without predictions
            continue
        prediction = predictions[instance[KEY_INSTANCE_ID]]
        report_file = (
            RUN_EVALUATION_LOG_DIR
            / run_id
            / prediction["model_name_or_path"].replace("/", "__")
            / prediction[KEY_INSTANCE_ID]
            / "report.json"
        )
        if report_file.exists():
            completed_ids.add(instance[KEY_INSTANCE_ID])

    if completed_ids and exclude_completed:
        # filter dataset to only instances that have not been run
        print(f"{len(completed_ids)} instances already run, skipping...")
        dataset = [i for i in dataset if i[KEY_INSTANCE_ID] not in completed_ids]

    empty_patch_ids = {k for k, v in predictions.items() if v["model_patch"] == "" or v["model_patch"] is None}

    # filter dataset to only instances with predictions
    dataset = [i for i in dataset if i[KEY_INSTANCE_ID] in prediction_ids and i[KEY_INSTANCE_ID] not in empty_patch_ids]
    return dataset


def make_run_report(
        predictions: dict,
        full_dataset: list,
        client: docker.DockerClient,
        run_id: str
    ) -> dict:
    """
    Make a final evaluation and run report of the instances that have been run.
    Also reports on images and containers that may still running!

    Args:
        predictions (dict): Predictions dict generated by the model
        full_dataset (list): List of all instances
        client (docker.DockerClient): Docker client
        run_id (str): Run ID
    
    Returns:
        dict: Concise report
    """
    # instantiate sets to store IDs of different outcomes
    completed_ids = set()
    resolved_ids = set()
    error_ids = set()
    unstopped_containers = set()
    unremoved_images = set()
    unresolved_ids = set()
    incomplete_ids = set()
    # get instances with empty patches
    empty_patch_ids = set()

    # iterate through dataset and check if the instance has been run
    for instance in full_dataset:
        instance_id = instance[KEY_INSTANCE_ID]
        if instance_id not in predictions:
            # skip instances without 
            incomplete_ids.add(instance_id)
            continue
        prediction = predictions[instance_id]
        if prediction.get("model_patch", None) in ["", None]:
            empty_patch_ids.add(instance_id)
            continue
        report_file = (
            RUN_EVALUATION_LOG_DIR
            / run_id
            / prediction["model_name_or_path"].replace("/", "__")
            / prediction[KEY_INSTANCE_ID]
            / "report.json"
        )
        if report_file.exists():
            # If report file exists, then the instance has been run
            completed_ids.add(instance_id)
            report = json.loads(report_file.read_text())
            if report[instance_id]["resolved"]:
                # Record if the instance was resolved
                resolved_ids.add(instance_id)
            else:
                unresolved_ids.add(instance_id)
        else:
            # Otherwise, the instance was not run successfully
            error_ids.add(instance_id)

    # get remaining images and containers
    images = list_images(client)
    test_specs = list(map(make_test_spec, full_dataset))
    for spec in test_specs:
        image_name = spec.instance_image_key
        if image_name in images:
            unremoved_images.add(image_name)
    containers = client.containers.list(all=True)
    for container in containers:
        if run_id in container.name:
            unstopped_containers.add(container.name)

    # print final report
    dataset_ids = {i[KEY_INSTANCE_ID] for i in full_dataset}
    print(f"Total instances: {len(full_dataset)}")
    print(f"Instances submitted: {len(set(predictions.keys()) & dataset_ids)}")
    print(f"Instances completed: {len(completed_ids)}")
    print(f"Instances incomplete: {len(incomplete_ids)}")
    print(f"Instances resolved: {len(resolved_ids)}")
    print(f"Instances unresolved: {len(unresolved_ids)}")
    print(f"Instances with empty patches: {len(empty_patch_ids)}")
    print(f"Instances with errors: {len(error_ids)}")
    print(f"Unstopped containers: {len(unstopped_containers)}")
    print(f"Unremoved images: {len(unremoved_images)}")

    # write report to file
    report = {
        "total_instances": len(full_dataset),
        "submitted_instances": len(predictions),
        "completed_instances": len(completed_ids),
        "resolved_instances": len(resolved_ids),
        "unresolved_instances": len(unresolved_ids),
        "empty_patch_instances": len(empty_patch_ids),
        "error_instances": len(error_ids),
        "unstopped_instances": len(unstopped_containers),
        "completed_ids": list(sorted(completed_ids)),
        "incomplete_ids": list(sorted(incomplete_ids)),
        "empty_patch_ids": list(sorted(empty_patch_ids)),
        "submitted_ids": list(sorted(predictions.keys())),
        "resolved_ids": list(sorted(resolved_ids)),
        "unresolved_ids": list(sorted(unresolved_ids)),
        "error_ids": list(sorted(error_ids)),
        "unstopped_containers": list(sorted(unstopped_containers)),
        "unremoved_images": list(sorted(unremoved_images)),
        "schema_version": 2,
    }
    report_file = Path(
        list(predictions.values())[0]["model_name_or_path"].replace("/", "__")
        + f".{run_id}"
        + ".json"
    )
    with open(report_file, "w") as f:
        print(json.dumps(report, indent=4), file=f)
    print(f"Report written to {report_file}")

    concise_report = {
        "total_instances": len(full_dataset),
        "submitted_instances": len(predictions),
        "completed_instances": len(completed_ids),
        "instances_incomplete": len(incomplete_ids),
        "instances_resolved": len(resolved_ids),
        "instances_unresolved": len(unresolved_ids),
    }

    return concise_report


def get_gold_predictions(dataset_name: str, split: str):
    """
    Get gold predictions for the given dataset and split.
    """
    dataset = load_swebench_dataset(dataset_name, split)
    return [
        {
            KEY_INSTANCE_ID: datum[KEY_INSTANCE_ID],
            "model_patch": datum["patch"],
            "model_name_or_path": "gold",
        } for datum in dataset
    ]


async def main_sidecar(
    sidecar_executable_path: str,
    dataset_name: str,
    instance_ids: list,
    max_workers: int,
    split: str,
    run_id: str,
    timeout: int,
    anthropic_api_key: str,
    openrouter_api_key: str,
    test_mode: bool,
    output_log_path: str,
    traj_search_space: int,
    **kwargs,
):
    """
    Runs the sidecar over here and run the instance we are interested in
    This allows us to iterate against a complete flow
    """

    # If there is no traj search space then its pain mcts
    if traj_search_space == 0:
        traj_search_space = None
    assert len(run_id) > 0, "Run ID must be provided and not empty"
    resource.setrlimit(resource.RLIMIT_NOFILE, (4096, 4096))

    # Create prediction path based on top of the run-id
    predictions_path = "predictions/" + run_id
    # Make sure that this path exists
    Path(predictions_path).mkdir(parents=True, exist_ok=True)
    
    dataset = get_dataset_for_instances(
        dataset_name=dataset_name,
        split=split,
        instance_ids=instance_ids,
    )
    print(f"Running {len(dataset)} unevaluated instances...")

    predictions = []
    for dataset_part in dataset:
        # Create predictions over here for each instance
        # we will then load it from the prediction_directory path
        # Now create the temporary git directory
        git_tempdir = checkout_repo(dataset_part)
        # We want to get the git_tempdir and then copy the git-diff to the patch
        # for each change which we perform
        # we only want the test_spec builder over here and then we figure out
        # what to do
        test_spec = make_test_spec(dataset_part)
        # This is our debug environment
        # Do we leave strays running around if we cntrl+c (yes, we will do cleanups later)
        debug_container_details = start_debug_environment(
            test_spec=test_spec,
            client=docker.from_env(),
            run_id=run_id,
        )
        debug_container = debug_container_details[0]
        DEV_DOCKER_CONTAINERS.append(debug_container)
        log_directory = debug_container_details[1]
        # Lambda which executes the terminal command
        terminal_command_runner = lambda command: run_terminal_command(
            test_spec=test_spec,
            instance=dataset_part,
            run_id=run_id,
            model_name_or_path="sidecar",
            command=command,
            git_drname=git_tempdir,
            container=debug_container,
            log_directory=log_directory,
            timeout=timeout,
        )
        # Lambda which executes the test command
        test_command = lambda files: run_instance_for_test_path(
            test_spec=test_spec,
            git_drname=git_tempdir,
            model_name_or_path="sidecar",
            client=docker.from_env(),
            run_id=run_id,
            test_files=files,
            instance=dataset_part,
            container=debug_container,
            timeout=timeout,
        )
        endpoint_url, editor_task = await http_implementation.setup_editor(
            git_dname=git_tempdir,
            test_cmd=test_command,
            terminal_command_runner=terminal_command_runner,
        )
        # sleep here is necessary so we are able to hit the endpoints
        await asyncio.sleep(2)
        if test_mode:
            print("Generating tests and not EDITS")

        print("run_evaluation::endpoint_url", endpoint_url)

        start_time = datetime.now()  # Record the start time
        await sidecar_run(
            sidecar_path=sidecar_executable_path,
            git_drname=git_tempdir,
            endpoint_url=endpoint_url,
            instance=dataset_part,
            run_id=run_id,
            anthropic_api_key=anthropic_api_key,
            openrouter_api_key=openrouter_api_key,
            log_directory=log_directory,
            traj_search_space=traj_search_space,
        )

        end_time = datetime.now()  # Record the end time
        elapsed_time = end_time - start_time
        print(f"Time taken for sidecar run: {elapsed_time}")

        # Stop our debug container over here
        print("Stopping debug container", debug_container.id)
        debug_container.stop()
        print("Removing debug container", debug_container.id)
        debug_container.remove()

        # Cancel the editor task
        try:
            # Wait for the task to complete with a timeout
            editor_task.cancel()
        except asyncio.TimeoutError or asyncio.CancelledError:
            print(f"Task did not complete within {timeout} seconds. Cancelling task...")
            editor_task.cancel()
            try:
                await editor_task
            except asyncio.CancelledError:
                print("Task was successfully cancelled.")

        # Here we want to run the evaluation on top of the mcts tree that was generated
        mcts_tree = os.path.join(log_directory, f"mcts-{run_id}.json")
        # Now we are going to parse it and one by one run the evaluation for each of the
        # finished nodes
        with open(mcts_tree, 'r') as f:
            parsed_mcts_tree = json.load(f)
        
        # Now that we have the tree we need to be smar on top of it
        completed_nodes = [int(index) for index, node in parsed_mcts_tree["index_to_node"].items()
                           if node.get("action") and "AttemptCompletion" in str(node["action"])]

        instance_id = dataset_part['instance_id']
        successful_attempt = False  # Track if any attempt succeeded

        # Now iterate over the completed nodes
        for completed_node in completed_nodes:
            print(f"Evaluating {completed_node}")
            node = parsed_mcts_tree["index_to_node"][str(completed_node)]
            variables = node["user_context"]["variables"]
            # First clear out any changes which exist on the git_tempdir
            print(f"reset git_directory at {git_tempdir}")
            subprocess.check_output(["git", "add", "."], cwd=git_tempdir)
            subprocess.check_output(["git", "stash"], cwd=git_tempdir)
            # Now apply the patch one by one to the files we are interested in
            for variable in variables:
                file_path = variable.get("fs_file_path")
                file_content = variable.get("content")
                # override the file content in tempdir over here
                try:
                    with open(file_path, "w") as f:
                        f.write(file_content)
                except Exception as e:
                    pass
            
            # for variable in variables:
            #     initial_patch = variable.get("initial_patch")
            #     file_content = variable.get("content")
            #     file_path = variable.get("fs_file_path")
                
            #     # The patch logic might be wrong over here... need to check deeper
            #     if initial_patch and file_path:
            #         try:
            #             print(f"applying patch for {file_path}")
            #             # Write the patch to a temporary file
            #             temp_patch_file = "temp_patch.diff"
            #             with open(temp_patch_file, "w") as patch_file:
            #                 patch_file.write(initial_patch)
                        
            #             # Apply the patch to the file
            #             subprocess.check_output(["patch", file_path, temp_patch_file])
            #             print(f"Patch applied successfully to {file_path}")
            #         except subprocess.CalledProcessError as e:
            #             print(f"Failed to apply patch to {file_path}: {e.output.decode()}")
            #         finally:
            #             # Clean up the temporary patch file
            #             if os.path.exists(temp_patch_file):
            #                 os.remove(temp_patch_file)
            
            # Patch applied
            print(f"Finished updating repo for node: {completed_node}")

            # run evaluation now
            predictions = []
            try:
                git_diff_output = subprocess.check_output(
                    ["git", "diff"],
                    cwd=git_tempdir,
                ).decode("utf-8")
                predictions.append({
                    KEY_INSTANCE_ID: dataset_part['instance_id'],
                    KEY_MODEL: "sidecar",
                    KEY_PREDICTION: git_diff_output,
                })
            except subprocess.CalledProcessError as e:
                print(f"Failed to create git diff: {e}")
                continue

            print(f"Running evaluation for {completed_node}")
            predictions = {pred[KEY_INSTANCE_ID]: pred for pred in predictions}

            client = docker.from_env()
            # Load the datasets from the predicitions
            dataset = get_dataset_from_preds(dataset_name, split, instance_ids, predictions, run_id)
            full_dataset = load_swebench_dataset(dataset_name, split, instance_ids)
            existing_images = list_images(client)
            print(f"Running {len(dataset)} unevaluated instances...")
            if not dataset:
                print("No instances to run.")
            else:
                # build environment images + run instances
                # build_env_images(client, dataset, False, max_workers)
                # Sets timeout to 1800 seconds or 30 minutes
                # This is where it gets interesting since we want to poll for some time
                # before getting the predictions over here
                # This is the most important bit
                run_instances(predictions, dataset, "none", False, False, max_workers, run_id, 1_800)

            clean_images(client, existing_images, "none", False)
            concise_report = make_run_report(predictions, full_dataset, client, run_id)
            
            # Check if this attempt was successful
            if concise_report["instances_resolved"] > 0:
                successful_attempt = True
                print(f"✅ Successful solution found for {instance_id} at node {completed_node}")
                break  # Optional: stop after first success
            else:
                print(f"❌ Attempt failed for {instance_id} at node {completed_node}")

        # Get absolute path of MCTS tree file
        mcts_tree_path = os.path.abspath(mcts_tree)
        
        # Collect results in a dictionary
        instance_results = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "instance_id": instance_id,
            "success": successful_attempt,
            "completion_nodes": len(completed_nodes),
            "total_nodes": len(parsed_mcts_tree["index_to_node"]),
            "time_taken": str(elapsed_time),
            "mcts_tree_path": mcts_tree_path,
            "parea_link": get_parea_link(run_id),
        }

        print(f"Instance results: {instance_results}")

        # Compute the absolute path
        absolute_output_log_path = os.path.abspath(output_log_path)

        # Write the JSON output
        with open(absolute_output_log_path, "a") as f:
            json.dump(instance_results, f, indent=2)
            f.write("\n")  # Add newline between JSON objects

        print(f"Instance results written to {absolute_output_log_path}")

        # https://docs.google.com/spreadsheets/d/1W0gxh-NC9Sl01yrlTRPNGvyDQva3_lZPPPMQ2M8IP74/edit?gid=280623479#gid=280623479
        LOG_SHEET_ID = "1W0gxh-NC9Sl01yrlTRPNGvyDQva3_lZPPPMQ2M8IP74"
        SHEET_ID = 280623479
        LOG_SHEET_NAME = "RUNS"

        # Update the instance run status in the spreadsheet
        update_instance_run_status(LOG_SHEET_ID, SHEET_ID, LOG_SHEET_NAME, run_id, instance_id, successful_attempt, instance_results)

def main(
        dataset_name: str,
        split: str,
        instance_ids: list,
        predictions_path: str,
        max_workers: int,
        force_rebuild: bool,
        cache_level: str,
        clean: bool,
        open_file_limit: int,
        run_id: str,
        timeout: int,
    ):
    """
    Run evaluation harness for the given dataset and predictions.
    """
    # set open file limit
    assert len(run_id) > 0, "Run ID must be provided"
    resource.setrlimit(resource.RLIMIT_NOFILE, (open_file_limit, open_file_limit))
    client = docker.from_env()

    # load predictions as map of instance_id to prediction
    if predictions_path == 'gold':
        print("Using gold predictions - ignoring predictions_path")
        predictions = get_gold_predictions(dataset_name, split)
    else:
        if predictions_path.endswith(".json"):
            with open(predictions_path, "r") as f:
                predictions = json.load(f)
        elif predictions_path.endswith(".jsonl"):
            with open(predictions_path, "r") as f:
                predictions = [json.loads(line) for line in f]
        else:
            raise ValueError("Predictions path must be \"gold\", .json, or .jsonl")
    predictions = {pred[KEY_INSTANCE_ID]: pred for pred in predictions}

    # get dataset from predictions
    dataset = get_dataset_from_preds(dataset_name, split, instance_ids, predictions, run_id)
    full_dataset = load_swebench_dataset(dataset_name, split, instance_ids)
    existing_images = list_images(client)
    print(f"Running {len(dataset)} unevaluated instances...")
    if not dataset:
        print("No instances to run.")
    else:
        # build environment images + run instances
        build_env_images(client, dataset, force_rebuild, max_workers)
        run_instances(predictions, dataset, cache_level, clean, force_rebuild, max_workers, run_id, timeout)

    # clean images + make final report
    clean_images(client, existing_images, cache_level, clean)
    make_run_report(predictions, full_dataset, client, run_id)


# Run the following command:
# pip3 install -e .
# and then run this binary from the root dir of this repo as:
# python3 swebench/harness/run_evaluation.py --help
if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--dataset_name", default="princeton-nlp/SWE-bench_Lite", type=str, help="Name of dataset or path to JSON file.")
    parser.add_argument("--split", type=str, default="test", help="Split of the dataset")
    parser.add_argument("--instance_ids", nargs="+", type=str, help="Instance IDs to run (space separated)")
    # Remove predicitons paths for now, we can reintroduce it later on
    # parser.add_argument("--predictions_path", type=str, help="Path to predictions file - if 'gold', uses gold predictions", required=True)
    parser.add_argument("--max_workers", type=int, default=4, help="Maximum number of workers (should be <= 75%% of CPU cores)")
    parser.add_argument("--open_file_limit", type=int, default=4096, help="Open file limit")
    parser.add_argument(
        "--timeout", type=int, default=1_800, help="Timeout (in seconds) for running tests for each instance"
        )
    parser.add_argument(
        "--force_rebuild", type=str2bool, default=False, help="Force rebuild of all images"
    )
    parser.add_argument(
        "--cache_level",
        type=str,
        choices=["none", "base", "env", "instance"],
        help="Cache level - remove images above this level",
        default="env",
    )
    # if clean is true then we remove all images that are above the cache level
    # if clean is false, we only remove images above the cache level if they don't already exist
    parser.add_argument(
        "--clean", type=str2bool, default=False, help="Clean images above cache level"
    )
    parser.add_argument("--run_id", type=str, default=str(int(time.time())), help="Run ID - identifies the run")
    parser.add_argument("--sidecar_executable_path", type=str, help="Path to the sidecar binary")
    parser.add_argument("--test_mode", type=bool, default=False, help="If we should run the test agent or the swebench agent, setting to true runs the test generation agent")
    parser.add_argument("--anthropic_api_key", type=str, default=None, help="Set the anthropic api key which we should be using")
    parser.add_argument("--openrouter_api_key", type=str, default=None, help="Set the open router api key which we should be using")
    parser.add_argument("--output_log_path", type=str, help="Path to the output log file")
    parser.add_argument("--traj_search_space", type=int, default=0, help="How many straight trajectoris we want to generate")

    args = parser.parse_args()

    # block if output_log_path is not provided
    if not args.output_log_path:
        raise ValueError("Output log path must be provided. Usage: --output_log_path <path>")
    
    # block if run_id is not provided
    if not args.run_id:
        raise ValueError("Run ID must be provided. Usage: --run_id <run_id>")
    
    print(f"Run ID: {args.run_id}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Run the sidecar harness in an asyncio event loop
    asyncio.run(main_sidecar(**vars(args)))
    # main_sidecar(**vars(args))
    # main(**vars(args))
