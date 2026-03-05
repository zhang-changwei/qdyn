import argparse
import logging


def main():
    print("Hello from qdyn!")


def serve():
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run('src.job_manager:app', host='0.0.0.0', port=8000, reload=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='QDYN')
    parser.add_argument('--server', action='store_true', help='Start the job-manager server')
    args = parser.parse_args()

    if args.server:
        serve()
    else:
        main()
