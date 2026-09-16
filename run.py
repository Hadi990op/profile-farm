#!/usr/bin/env python3
"""Single-entrypoint runner: mobile-launcher on PORT+1, then profile panel on PORT."""
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent.resolve()
port = int(os.environ.get("PORT", "9090"))

mobile = subprocess.Popen(
    [sys.executable, str(BASE / "mobile-launcher" / "server.py"), str(port + 1)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
os.environ["MOBILE_LAUNCHER_URL"] = f"http://127.0.0.1:{port + 1}"

sys.path.insert(0, str(BASE / "profile-launcher"))
os.chdir(BASE / "profile-launcher")
import server  # noqa: E402  (profile-launcher/server.py)

try:
    server.app.run(host="0.0.0.0", port=port, debug=False)
finally:
    mobile.terminate()
