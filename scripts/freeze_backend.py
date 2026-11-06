#!/usr/bin/env python3
"""Freeze the Python backend into a standalone executable folder with PyInstaller.
Output: backend_dist/zen-backend/  (executable: zen-backend / zen-backend.exe)
Usage:  python scripts/freeze_backend.py
"""
import shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd):
    print("→", " ".join(map(str, cmd)))
    subprocess.check_call(cmd, cwd=ROOT)


def main():
    try:
        run([sys.executable, "-m", "pip", "install", "-r", "backend/requirements.txt"])
    except subprocess.CalledProcessError:
        try:
            import PyInstaller  # noqa: F401
            print("! pip install failed (managed environment?) - continuing with installed packages. Tip: use a venv.")
        except ImportError:
            sys.exit("Install failed and PyInstaller is missing. Create a venv and run: pip install -r backend/requirements.txt")
    for d in ("backend_dist", "build/pyi"):
        shutil.rmtree(ROOT / d, ignore_errors=True)
    run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "zen-backend",
        "--distpath", "backend_dist", "--workpath", "build/pyi", "--specpath", "build/pyi",
        "--collect-all", "certifi", "--collect-submodules", "uvicorn", "--collect-submodules", "anyio",
        "--collect-data", "docx", "--collect-data", "pptx", "--collect-all", "reportlab", "--collect-submodules", "openpyxl",
        "--collect-submodules", "pypdf", "--hidden-import", "h11", "--hidden-import", "pydantic", "--hidden-import", "lxml._elementpath",
        "backend/server.py",
    ])
    exe = ROOT / "backend_dist" / "zen-backend" / ("zen-backend.exe" if sys.platform == "win32" else "zen-backend")
    if not exe.exists():
        sys.exit(f"Freeze failed: {exe} not found")
    print(f"\n✔ Backend frozen: {exe}")


if __name__ == "__main__":
    main()
