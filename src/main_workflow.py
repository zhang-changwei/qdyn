import shutil
from pathlib import Path
import requests

SCHEDULER_IP = '192.168'

async def main_workflow(
    working_dir: str,
    scheduler_ip: str,
):

    # NVT
    nvt_dir = Path(working_dir) / 'nvt'
    nvt_dir.mkdir(parents=True, exist_ok=True)

    prepare_nvt_input(nvt_dir)

    resp = requests.post(f'http://{scheduler_ip}/submit', json={
        'command': 'run_nvt.sh',
        'working_dir': str(nvt_dir),
    })
    job_id = resp.text