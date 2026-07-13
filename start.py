#!/usr/bin/env python3
"""
DNS-Benchmarker Web — Backend Launcher
Run this with: python start.py
Or with admin: Run terminal as Administrator, then python start.py (Windows)
               sudo python start.py (Linux/macOS)
"""
import sys
import os
import subprocess

# ── Ensure we're always in the same directory as this script ─────────────────
# This fixes "ModuleNotFoundError: No module named 'dns'" when start.py is
# launched from a different working directory (e.g. double-click on Windows).
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

# ── Dependency check with helpful install message ─────────────────────────────
REQUIRED = {
    "fastapi":        "fastapi",
    "uvicorn":        "uvicorn",
    "dns.asyncresolver": "dnspython",
}

missing = []
for module, package in REQUIRED.items():
    try:
        __import__(module)
    except ImportError:
        missing.append(package)

if missing:
    print("\n  ✗ Missing dependencies detected:")
    for pkg in missing:
        print(f"      {pkg}")
    print(f"\n  Install them with:")
    print(f"      pip install {' '.join(missing)}")
    print(f"\n  Or if using the hermes/uv venv shown in your error:")
    print(f"      {sys.executable} -m pip install {' '.join(missing)}\n")
    sys.exit(1)

import uvicorn

if __name__ == "__main__":
    print("\n  ┌─────────────────────────────────────────┐")
    print("  │   DNS-Benchmarker Web — Backend v1.0    │")
    print("  └─────────────────────────────────────────┘")
    print(f"\n  Python:   {sys.executable}")
    print(f"  WorkDir:  {script_dir}")
    print(f"\n  API:      http://localhost:8765")
    print(f"  Docs:     http://localhost:8765/docs")
    print(f"  Frontend: open ../frontend/index.html in your browser\n")

    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8765,
        reload=False,
        log_level="info",
    )
