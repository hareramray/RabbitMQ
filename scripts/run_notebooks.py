"""Execute selected labs against a RUNNING stack, preserving clean originals.

Example: python scripts/run_notebooks.py --pattern '0[1-6]_*.ipynb'
Optional disruption drills are intentionally disabled in default notebook cells.
"""
import argparse
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", default="*.ipynb")
    args = parser.parse_args()
    notebooks = sorted((ROOT / "notebooks").glob(args.pattern))
    if not notebooks:
        parser.error("No notebooks match the pattern")
    output = ROOT / "artifacts" / "executed"
    output.mkdir(parents=True, exist_ok=True)
    for path in notebooks:
        print(f"Executing {path.name}", flush=True)
        notebook = nbformat.read(path, as_version=4)
        try:
            NotebookClient(notebook, timeout=180, kernel_name="python3", resources={"metadata": {"path": str(ROOT)}}).execute()
        finally:
            nbformat.write(notebook, output / path.name)
    print(f"Executed copies saved to {output}")


if __name__ == "__main__":
    main()
