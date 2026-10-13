"""Exercise real Uvicorn shutdown without a database or external network."""

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.request import urlopen

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Checks Linux process-group shutdown")
SOURCE = Path(__file__).resolve().parents[1] / "src"


def is_running(pid):
    status = Path(f"/proc/{pid}/status")
    try:
        return "State:\tZ" not in status.read_text()
    except FileNotFoundError:
        return False


@pytest.mark.parametrize("failure", ["none", "startup", "shutdown"])
def test_shutdown_reaps_rate_limiter(tmp_path, failure):
    # Only replace the database; import the real server and limiter under Uvicorn.
    (tmp_path / "db.py").write_text('''
import json
import multiprocessing
import os
from pathlib import Path

async def init_pool():
    Path("children.json").write_text(json.dumps([p.pid for p in multiprocessing.active_children()]))
    if os.environ["DB_FAILURE"] == "startup":
        raise RuntimeError("test database startup failure")

async def close_pool():
    if os.environ["DB_FAILURE"] == "shutdown":
        raise RuntimeError("test database shutdown failure")
''')
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(tmp_path), str(SOURCE)]),
           "ENABLE_RATE_LIMIT": "true", "DB_FAILURE": failure}
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "0"],
            cwd=tmp_path, env=env, start_new_session=True, stdout=log, stderr=log,
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                log.seek(0)
                output = log.read()
                port = re.search(r"Uvicorn running on http://127\.0\.0\.1:(\d+)", output)
                if port or process.poll() is not None:
                    break
                time.sleep(0.05)
            else:
                pytest.fail(f"Uvicorn startup timed out:\n{output}")

            children = json.loads((tmp_path / "children.json").read_text())
            assert len(children) == 1, "The real rate limiter must start one Manager"
            if failure == "startup":
                assert process.wait(timeout=5) != 0
                assert "test database startup failure" in output
            else:
                assert port, output
                with urlopen(f"http://127.0.0.1:{port[1]}/healthz", timeout=2) as response:
                    assert response.status == 200
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
                log.seek(0)
                output = log.read()
                if failure == "shutdown":
                    assert "test database shutdown failure" in output
                else:
                    assert "Application shutdown complete" in output

            deadline = time.monotonic() + 1
            while any(is_running(pid) for pid in children) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not any(is_running(pid) for pid in children), "Rate-limit Manager survived shutdown"
        finally:
            # Own only this test's process group, including an orphan on regression.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
