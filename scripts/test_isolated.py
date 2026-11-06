"""Run database regressions in a uniquely owned disposable Postgres database."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import socket
import time
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import create_engine, text, select
from sqlalchemy.engine import make_url
from backend.config import get_settings


def main():
    url = make_url(get_settings().sync_database_url)
    name = "dhk_test_" + secrets.token_hex(8)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        env = dict(os.environ, DATABASE_URL=url.set(database=name, drivername="postgresql+asyncpg").render_as_string(hide_password=False), DHK_TEST_DB_NAME=name)
        env["SETUP_TOKEN"] = secrets.token_hex(32)
        env["REDIS_KEY_PREFIX"] = f"dhk_test:{name}:"
        env["REDIS_URL"] = urlunsplit(urlsplit(get_settings().redis_url)._replace(path="/15"))
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, env=env)
        if result.returncode:
            return result.returncode
        from sqlalchemy.orm import Session
        from backend.models.settings import AppSettings
        from backend.paper.policy import POLICY_KEY, PlatformPolicy
        test_engine = create_engine(url.set(database=name))
        with Session(test_engine) as db:
            row = db.scalar(select(AppSettings).where(AppSettings.key == POLICY_KEY))
            if row is not None:
                db.delete(row)
                db.flush()
            db.add(AppSettings(key=POLICY_KEY, value=PlatformPolicy(public_feed_enabled=False).model_dump_json()))
            db.commit()
        test_engine.dispose()
        with tempfile.TemporaryDirectory(prefix="dhk-http-test-") as directory:
            parts = urlsplit(get_settings().redis_url)
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            host = f"http://127.0.0.1:{port}"
            env.update(REDIS_URL=urlunsplit(parts._replace(path="/15")), BACKEND_PORT=str(port), WEBSOCKET_PORT="8794", ZMQ_PORT="5594", LOG_DIR=directory,
                WEBSOCKET_URL="ws://127.0.0.1:8794", DHK_QA_URL=host, DHK_QA_RECORD=str(Path(directory) / "qa.json"))
            with open(Path(directory) / "server.log", "w+") as output:
                server = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--fd", str(listener.fileno())], cwd=ROOT, env=env, stdout=output, stderr=output, pass_fds=(listener.fileno(),))
                listener.close()
                try:
                    import httpx
                    for attempt in range(80):
                        if server.poll() is not None:
                            output.seek(0)
                            print(output.read()[-5000:])
                            raise RuntimeError("Isolated server failed to start")
                        try:
                            if httpx.get(host + "/health", timeout=1).status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Isolated server did not become ready")
                    result = subprocess.run([sys.executable, "scripts/verify_paper.py"], cwd=ROOT, env=env)
                    if result.returncode or "--browser" not in sys.argv:
                        return result.returncode
                    return subprocess.run(["node", "scripts/test-browser.mjs"], cwd=ROOT / "frontend", env=env).returncode
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait()
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
        from redis import Redis
        parts = urlsplit(get_settings().redis_url)
        client = Redis.from_url(urlunsplit(parts._replace(path="/15")))
        try:
            for prefix in (f"LIMITS:LIMITER/dhk:{name}/", f"DHK_LIMITS:{name}:", f"dhk_test:{name}:"):
                for key in client.scan_iter(match=prefix + "*", count=100):
                    client.delete(key)
        finally:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
