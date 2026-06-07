#!/bin/python3

import argparse
import json
import logging
import os
import pydantic
import sys
import yaml

import numpy as np
from qdyn.database import qdyndb
from qdyn.main_workflow import MainWorkflow
from qdyn.input import InputT
from qdyn.auth.security import configure as configure_auth
from qdyn.app import (submit_task, list_tasks, list_task_jobs, get_job_output)

manager: MainWorkflow | None = None

class NumpyEncoder(json.JSONEncoder):
    def default(self, o):
        # 处理 numpy 数组
        if isinstance(o, np.ndarray):
            return o.tolist()
        # 处理 numpy 的整数标量 (如 np.int32, np.int64)
        if isinstance(o, np.integer):
            return int(o)
        # 处理 numpy 的浮点数标量 (如 np.float32, np.float64)
        if isinstance(o, np.floating):
            return float(o)
        # 处理 numpy 的布尔值
        if isinstance(o, np.bool_):
            return bool(o)
            
        # 其他类型交由默认处理
        return super(NumpyEncoder, self).default(o)


def main(
    task: str, 
    task_id: str = '',
    job_uuid: str = '',
    input_path: str = '',
    output_path: str = 'output.yaml',
    config_path: str | None = None,
    submit_args: str = '',
):
    global manager
    config_path = (
        config_path or os.environ.get("QDYN_CONFIG") or "config/qdyn.yaml"
    )
    manager = MainWorkflow(config_path)

    auth_cfg = manager.config.get("auth", {})

    # --- auth & DB init ---
    db_path = manager.config['basic'].get("user_db_path", "data/qdyn_users.db")
    qdyndb.init_db(db_path)

    secret_key = auth_cfg.get("secret_key", "")
    expire_hours = auth_cfg.get("token_expire_hours", 24)
    generated_key = configure_auth(secret_key, expire_hours)

    # persist auto-generated key back to config file if it was empty
    if not auth_cfg.get("secret_key"):
        manager.config.setdefault("auth", {})["secret_key"] = generated_key
        with open(config_path, "r") as f:
            raw = f.read()
            raw = raw.replace('secret_key: ""', f'secret_key: "{generated_key}"')
            raw = raw.replace("secret_key: ''", f'secret_key: "{generated_key}"')
        with open(config_path, "w") as f:
            f.write(raw)
        logging.info("Auto-generated auth secret_key and saved to config.")

    # restore task_ids and job_ids from DB
    restored = manager.restore_from_db(qdyndb.get_db())
    logging.info(f"Restored {restored} tasks from database.")
    
    # --- init complete, run workflow ---
    if task == 'submit':
        with open(input_path, 'r') as f:
            raw = yaml.safe_load(f)
        input_data = InputT(**raw)
        with open(submit_args, 'r') as f:
            raw = yaml.safe_load(f)
        method = raw.get('method', 'namd')
        stru = raw.get('stru', '')
        stru_format = raw.get('stru_format', 'vasp')
        resume = raw.get('resume', False)
        prev_task_id = raw.get('prev_task_id', '')
        if stru:
            with open(stru, 'r') as f:
                stru = f.read()

        task_id = submit_task(input_data, method, stru, stru_format, resume, prev_task_id, 'admin')
        print(f"Task submitted with ID: {task_id}")

    elif task == 'list_tasks':
        tasks = list_tasks('admin')
        print("Tasks: \n{}".format("\n".join(tasks)))

    elif task == 'list_task_jobs':
        jobs = list_task_jobs(task_id, 'admin')
        print(f"Jobs for task {task_id}: \n"
              f"{json.dumps(jobs, indent=2)}")
        
    elif task == 'get_job_output':
        output = get_job_output(task_id, job_uuid, 'admin')
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2, cls=NumpyEncoder)
        logging.info(f"Job output saved to {output_path}")

    else:
        raise NotImplementedError(f"Unknown task: {task}")
    
    # --- cleanup ---
    qdyndb.close_db()

def main_cli():
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description="QDyn CLI")
    parser.add_argument("-C", "--config", type=str, metavar='CONFIG_PATH',
                        help=("Path to qdyn.yaml configuration file\n"
                              "The program will search for the config file in the following order:\n"
                              "1. Command-line argument\n"
                              "2. Environment variable QDYN_CONFIG\n"
                              "3. Default path ./config/qdyn.yaml\n"
                              "Usage: -C path/to/qdyn.yaml"))
    parser.add_argument("-S", "--submit", nargs=2, type=str, default="default", 
                        metavar=('INPUT_PATH', 'ARGS_PATH'),
                        help=("Submit a task.\n"
                              "Usage: -S path/to/input.yaml path/to/submit_args.yaml"))
    parser.add_argument("-T", "--tasks", action="store_true", 
                        help=("List all tasks\n"
                              "Usage: -T"))
    parser.add_argument("-J", "--jobs", type=str, default="default", metavar='TASK_ID',
                        help=("List jobs for a task\n"
                              "Usage: -J TASK_ID"))
    parser.add_argument("-O", "--output", nargs=3, metavar=('TASK_ID', 'JOB_UUID', 'OUTPUT_PATH'),
                        help=("Get job output\n"
                              "Usage: -O TASK_ID JOB_UUID path/to/output.yaml"))
    args = parser.parse_args()

    if args.submit:
        input_data, submit_args = args.submit
        logging.info(f"User request: submit task with input file {args.submit}")
        if args.submit == "default":
            raise ValueError("Please provide an input file for submission, e.g. -S path/to/input.yaml")
        main('submit', input_path=input_data, submit_args=submit_args, config_path=args.config)

    elif args.tasks:
        logging.info("User request: list tasks")
        main('list_tasks', config_path=args.config)

    elif args.jobs:
        logging.info(f"User request: list jobs for task {args.jobs}")
        if args.jobs == "default":
            raise ValueError("Please provide a task ID to list jobs, e.g. -J TASK_ID")
        main('list_task_jobs', task_id=args.jobs, config_path=args.config)

    elif args.output:
        task_id, job_uuid, output_path = args.output
        logging.info(f"User request: get output for job {job_uuid} in task {task_id}\n"
                     f"and save to {output_path}")
        main('get_job_output', 
             task_id=task_id, 
             job_uuid=job_uuid, 
             output_path=output_path, 
             config_path=args.config)
        
    else:
        logging.info("User request: no specific action, exiting.")

if __name__ == "__main__":
    main_cli()
