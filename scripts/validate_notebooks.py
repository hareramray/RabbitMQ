"""Validate notebook structure and compile every Python cell (including top-level await)."""
import ast
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parents[1]


def main():
    paths = sorted((ROOT / "notebooks").glob("*.ipynb"))
    assert len(paths) == 19, f"Expected 19 notebooks, found {len(paths)}"
    code_cells = 0
    for path in paths:
        notebook = nbformat.read(path, as_version=4)
        nbformat.validate(notebook)
        assert notebook.metadata.kernelspec.language == "python", path
        for index, cell in enumerate(notebook.cells):
            if cell.cell_type == "code":
                assert cell.execution_count is None and not cell.outputs, f"Saved outputs in {path}"
                compile(cell.source, f"{path.name}:cell{index}", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                code_cells += 1
        print(f"OK {path.name}: {len(notebook.cells)} cells")
    print(f"Validated {len(paths)} notebooks and compiled {code_cells} code cells. Broker execution is separate.")


if __name__ == "__main__":
    main()
