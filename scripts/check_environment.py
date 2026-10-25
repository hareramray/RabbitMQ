"""Read-only prerequisite diagnostics. Run from any directory."""
import importlib.metadata
import shutil
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    print(f"Course: {ROOT}")
    for package in ["pika", "Django", "celery", "aio-pika", "jupyterlab", "nbformat"]:
        try:
            print(f"{package}: {importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            print(f"{package}: MISSING — install requirements.lock")
    print(f"Docker: {shutil.which('docker') or 'NOT FOUND — install/start Docker Desktop with Linux containers'}")
    for port, purpose in [(5672, "RabbitMQ AMQP"), (15672, "RabbitMQ management"), (8000, "Django API")]:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                print(f"{purpose}: port {port} reachable")
        except OSError:
            print(f"{purpose}: port {port} not reachable")


if __name__ == "__main__":
    main()
