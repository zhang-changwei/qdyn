# Not use now!

import os
import threading
from flask import Flask, render_template, request, jsonify, send_file
from workflow_manager import WorkflowManager
from config import JOBS_DIR

app = Flask(__name__)

# 创建工作目录
os.makedirs(JOBS_DIR, exist_ok=True)

# 工作流管理器实例
workflow_manager = WorkflowManager()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    # 获取上传文件和参数
    poscar_file = request.files['poscar']
    parameters = {
        # 'work_path': request.form.get('work_path', '~/doc/job/'),
        'temperature': request.form.get('temperature', 300),
        'wavecar_steps': request.form.get('wavecar_steps', 500),
        'simulation_method': request.form.get('simulation_method', 'DISH'),
        'INIBAND': request.form.get('INIBAND', 0),
        'simulation_time': request.form.get('simulation_time', 1000)
    }
    
    # 创建唯一任务ID
    job_id = str(len(os.listdir(JOBS_DIR)) + 1).zfill(6)
    
    # 在后台启动工作流
    threading.Thread(
        target=workflow_manager.start_workflow,
        args=(job_id, poscar_file, parameters)
    ).start()
    
    return jsonify({
        'job_id': job_id,
        'status_url': f'/status/{job_id}'
    })

@app.route('/status/<job_id>')
def job_status(job_id):
    status = workflow_manager.get_job_status(job_id)
    return render_template('status.html', job_id=job_id, status=status)

@app.route('/status_data/<job_id>')
def status_data(job_id):
    return jsonify(workflow_manager.get_job_status(job_id))

@app.route('/download/<job_id>/<step>')
def download_results(job_id, step):
    step_dir = os.path.join(JOBS_DIR, job_id, f"step{step}")
    result_file = os.path.join(step_dir, 'results.tar.gz')
    
    if not os.path.exists(result_file):
        return jsonify({'error': 'Result not available'}), 404
    
    return send_file(result_file, as_attachment=True)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000, threaded=True)
