import argparse
import logging


def main():
    print("Hello from qdyn!")


def serve(config_path):
    import uvicorn
    from src.job_manager import app
    app.state.config_path = config_path
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host='0.0.0.0', port=8000)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='QDYN')
    parser.add_argument('--server', action='store_true', help='Start the job-manager server')
    parser.add_argument('--config', default=None, metavar='PATH',
                        help='Path to qdyn.yaml (default: $QDYN_CONFIG or ./qdyn.yaml)')
    args = parser.parse_args()

    if args.server:
        serve(args.config)
    else:
        main()
