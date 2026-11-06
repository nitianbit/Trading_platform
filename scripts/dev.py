"""Run both local servers. Ctrl+C stops the owned process groups."""
from pathlib import Path
import os
import signal
import subprocess
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
commands = [
    ([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8083"], ROOT),
    (["npm", "run", "dev"], ROOT / "frontend"),
]
children = []
try:
    for index, (command, cwd) in enumerate(commands):
        children.append(subprocess.Popen(command, cwd=cwd, start_new_session=True))
        if index == 0:
            for attempt in range(60):
                if children[0].poll() is not None:
                    raise RuntimeError("The backend failed to start; inspect its output above.")
                try:
                    with urlopen("http://127.0.0.1:8083/health", timeout=0.5) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError):
                    time.sleep(0.25)
            else:
                raise RuntimeError("The backend did not become ready in time.")
    print("DHK Paper: http://127.0.0.1:5183 — Ctrl+C to stop", flush=True)
    while all(child.poll() is None for child in children):
        time.sleep(0.5)
except KeyboardInterrupt:
    pass
finally:
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for child in children:
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()

