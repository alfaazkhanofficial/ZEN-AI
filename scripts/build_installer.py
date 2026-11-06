#!/usr/bin/env python3
"""Build the Zen installer: freeze backend -> build UI -> package with electron-builder.
Usage:  python scripts/build_installer.py [--skip-freeze]
Output: release/  (NSIS .exe on Windows, .dmg on macOS, AppImage on Linux)
"""
import argparse, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NPM = shutil.which("npm") or "npm"
NPX = shutil.which("npx") or "npx"


def run(cmd):
    print("→", " ".join(map(str, cmd)))
    subprocess.check_call(cmd, cwd=ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-freeze", action="store_true", help="reuse existing backend_dist")
    a = ap.parse_args()
    frozen = ROOT / "backend_dist" / "zen-backend"
    if not a.skip_freeze or not frozen.exists():
        run([sys.executable, "scripts/freeze_backend.py"])
    run([NPM, "install"])
    run([NPM, "run", "build"])
    target = {"win32": "--win", "darwin": "--mac"}.get(sys.platform, "--linux")
    run([NPX, "electron-builder", target, "--publish", "never"])
    print("\n✔ Installer ready in ./release")


if __name__ == "__main__":
    main()
