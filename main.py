import argparse
import logging
import os
from pathlib import Path
import subprocess
import time
import yaml
from typing import List

CPUSET = '0,1'
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "2")

def sh2(cmd: List[str], **kwargs):
    return subprocess.run(['taskset', '-c', CPUSET, *cmd], **kwargs)


def main():
    print("Hello from qdyn!")


def start_mongod(config_path):
    import socket
    from pymongo import MongoClient

    try:
        subprocess.run(['mongod', '--version'], check=True, stdout=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("mongod not found. Please install MongoDB and ensure 'mongod' is in your PATH.")
        return
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    MONGO_PORT = s.getsockname()[1]
    s.close()

    config_path = (
        config_path or os.environ.get("QDYN_CONFIG") or "config/qdyn.yaml"
    )
    assert Path(config_path).is_file(), f"Config file not found: {config_path}"
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    MONGO_DIR = Path(config['basic'].get('mongo_dir', 'mongo/')).expanduser().resolve()
    MONGO_DBPATH = MONGO_DIR / 'data'
    MONGO_LOG = MONGO_DIR / 'log' / 'mongod.log'
    MONGO_PIDFILE = MONGO_DIR / 'mongod.pid'
    JF_PROJECT_NAME = config['basic'].get('jf_project_name', 'jf_qdyn')
    MONGO_URI = f'mongodb://127.0.0.1:{MONGO_PORT}/{JF_PROJECT_NAME}'

    print("MONGO_URI:", MONGO_URI)

    for d in [MONGO_DBPATH, MONGO_LOG.parent, MONGO_PIDFILE.parent]:
        d.mkdir(parents=True, exist_ok=True)

    # close any existing mongod instance using the same dbpath
    subprocess.run(['mongod', '--shutdown', '--dbpath', str(MONGO_DBPATH)])

    # start mongod
    try:
        sh2([
            'mongod',
            '--bind_ip', '127.0.0.1',
            '--port', str(MONGO_PORT),
            '--dbpath', str(MONGO_DBPATH),
            '--logpath', str(MONGO_LOG),
            '--pidfilepath', str(MONGO_PIDFILE),
            '--fork',
            '--setParameter', 'diagnosticDataCollectionEnabled=false',
        ], check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Failed to start mongod. Check the log file at {MONGO_LOG} "
            "or rerun without '--fork' for more details."
        ) from e

    # wait for mongod to be ready
    for i in range(50):
        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=200)
            client.admin.command('ping')
            client.close()
            print("mongod is ready.")
            return
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("Failed to start mongod within 5 seconds.")


def start_jf(config_path):
    from datetime import date

    config_path = (
        config_path or os.environ.get("QDYN_CONFIG") or "config/qdyn.yaml"
    )
    assert Path(config_path).is_file(), f"Config file not found: {config_path}"
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    jf_project_path = Path(config['basic'].get('jf_project_path', 'config/jf_qdyn.yaml')) \
                        .expanduser().resolve()
    jf_project_name = config['basic'].get('jf_project_name', 'jf_qdyn')
    os.environ['JFREMOTE_PROJECTS_FOLDER'] = str(jf_project_path.parent)
    os.environ['JFREMOTE_PROJECT'] = jf_project_name

    assert jf_project_path.is_file(), f"JF project config not found: {jf_project_path}"

    # Initalize
    today = date.today().isoformat()
    subprocess.run(['jf', 'admin', 'reset', today, '--yes'])
    subprocess.run(['jf', 'runner', 'reset', '--yes', '--break-lock'])

    # start jf
    sh2(['jf', 'runner', 'start', '--single'])

    # wait for jf to be ready
    for i in range(40):
        result = subprocess.run(['jf', 'runner', 'status'], capture_output=True, text=True)
        if 'running' in result.stdout:
            print("jf runner is ready.")
            return
        time.sleep(0.5)
    else:
        raise RuntimeError("Failed to start jf runner within 20 seconds.")



def serve(config_path):
    import sys
    import uvicorn
    from qdyn.app import app
    app.state.config_path = config_path
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    uvicorn.run(app, host='0.0.0.0', port=8000)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='QDYN')
    parser.add_argument('--mongod', action='store_true', 
                        help='Start a local mongod instance')
    parser.add_argument('--jf', action='store_true', 
                        help='Start a local JF instance')
    parser.add_argument('--server', action='store_true', 
                        help='Start the job-manager server')
    parser.add_argument('--config', default=None, metavar='PATH',
                        help='Path to qdyn.yaml (default: $QDYN_CONFIG or ./qdyn.yaml)')
    args = parser.parse_args()

    if args.server:
        serve(args.config)
    elif args.mongod:
        start_mongod(args.config)
    elif args.jf:
        start_jf(args.config)
    else:
        main()
