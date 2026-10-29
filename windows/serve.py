"""Windows-compatible WSGI entry point, also usable on Linux."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description='Postamt mit Waitress starten')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port muss zwischen 1 und 65535 liegen')
    from dotenv import load_dotenv
    from waitress import serve
    from postamt import create_app

    os.chdir(ROOT)
    load_dotenv(ROOT / '.env', override=False)
    app = create_app()
    print(f'Postamt startet auf {args.host}:{args.port}', flush=True)
    serve(app, host=args.host, port=args.port, threads=4, max_request_body_size=25 * 1024 * 1024)


if __name__ == '__main__':
    main()
