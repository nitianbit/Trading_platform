"""Smoke-test production images over local TLS with owned disposable resources."""
import io
import json
from pathlib import Path
import secrets
import subprocess
import tarfile
import tempfile
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--load",action="store_true")
    parser.add_argument("--seconds",type=int,default=30)
    parser.add_argument("--load-output",type=Path,default=ROOT/".local/load-results.json")
    args=parser.parse_args()
    from source_manifest import source_fingerprint, verify_image
    expected = source_fingerprint()
    for image in ("dhk-paper-backend:local", "dhk-paper-web:local"):
        verify_image(image, expected)
    project = "dhk-deploy-test-" + secrets.token_hex(5)
    with tempfile.TemporaryDirectory(prefix=project) as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        (directory / "deploy").mkdir()
        source = directory / "compose.yml"
        source.write_text((ROOT / "compose.production.yml").read_text())
        values = {"APP_DOMAIN": "localhost", "APP_SECRET_KEY": secrets.token_hex(32),
            "ENCRYPTION_PEPPER": secrets.token_hex(32), "SETUP_TOKEN": secrets.token_hex(32),
            "POSTGRES_PASSWORD": secrets.token_hex(32), "REDIS_PASSWORD": secrets.token_hex(32)}
        environment = directory / "deploy" / ".env.production"
        environment.write_text("".join(f'{key}="{value}"\n' for key, value in values.items()))
        environment.chmod(0o600)
        prefix = ["docker", "compose", "-p", project, "--env-file", str(environment), "-f", str(source)]
        rendered = subprocess.run(prefix + ["config", "--format", "json"], cwd=directory, check=True, capture_output=True, text=True)
        config = json.loads(rendered.stdout)
        for service, image in (("backend", "dhk-paper-backend:local"), ("web", "dhk-paper-web:local")):
            config["services"][service].pop("build", None)
            config["services"][service]["image"] = image
        config["services"]["web"]["ports"] = [{"host_ip": "127.0.0.1", "target": 443, "published": "0", "protocol": "tcp"}]
        assert not config["services"]["db"].get("ports") and not config["services"]["redis"].get("ports") and not config["services"]["backend"].get("ports")
        source.write_text(json.dumps(config))
        source.chmod(0o600)
        try:
            subprocess.run(prefix + ["up", "-d", "--wait", "db", "redis"], cwd=directory, check=True, capture_output=True)
            # A known row makes an empty/schema-only restore check insufficient.
            subprocess.run(prefix + ["exec","-T","db","psql","-U","dhkpaper","-d","dhkpaper","-v","ON_ERROR_STOP=1","-c","CREATE TABLE backup_probe(id INTEGER PRIMARY KEY, marker TEXT NOT NULL); INSERT INTO backup_probe VALUES (1,'restore-this-row'),(2,'and-this-row');"],cwd=directory,check=True,capture_output=True)
            # A backup of DB A must never authorize schema changes in DB B.
            subprocess.run(prefix+["exec","-T","db","createdb","-U","dhkpaper","dhk_wrong_target"],cwd=directory,check=True,capture_output=True)
            original_url=config["services"]["backend"]["environment"]["DATABASE_URL"]
            config["services"]["backend"]["environment"]["DATABASE_URL"]=original_url.rsplit("/",1)[0]+"/dhk_wrong_target"
            source.write_text(json.dumps(config))
            import sys
            refused=subprocess.run([sys.executable,str(ROOT/"scripts/migrate_database.py"),"--project-name",project,"--compose-file",str(source),"--env-file",str(environment),"--backup-dir",str(directory/"wrong-backup")],cwd=ROOT,capture_output=True,text=True)
            assert refused.returncode and "database identities differ" in refused.stderr
            untouched=subprocess.check_output(prefix+["exec","-T","db","psql","-U","dhkpaper","-d","dhk_wrong_target","-tAc","SELECT count(*) FROM pg_tables WHERE schemaname='public'"],cwd=directory,text=True)
            assert untouched.strip()=="0"
            config["services"]["backend"]["environment"]["DATABASE_URL"]=original_url
            source.write_text(json.dumps(config))
            import sys
            subprocess.run([sys.executable,str(ROOT/"scripts/migrate_database.py"),"--project-name",project,"--compose-file",str(source),"--env-file",str(environment),"--backup-dir",str(directory/"backups")],cwd=ROOT,check=True)
            receipts=list((directory/"backups").glob("*.json"))
            assert len(receipts)==1
            receipt=json.loads(receipts[0].read_text())
            assert receipt["verified"] and receipt["tables"]["backup_probe"]["rows"]==2
            subprocess.run(prefix + ["up", "-d", "--wait", "--wait-timeout", "90"], cwd=directory, check=True, capture_output=True)
            port = subprocess.check_output(prefix + ["port", "web", "443"], cwd=directory, text=True).strip().rsplit(":", 1)[1]
            host = "https://localhost:" + port
            for attempt in range(60):
                try:
                    if httpx.get(host + "/health", verify=False, timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("Production smoke-test gateway did not become ready")
            certificate = directory / "root.crt"
            subprocess.run(prefix + ["cp", "web:/data/caddy/pki/authorities/local/root.crt", str(certificate)], cwd=directory, check=True, capture_output=True)
            with httpx.Client(base_url=host, verify=str(certificate), timeout=20) as client:
                health = client.get("/health")
                assert health.status_code == 200 and all(health.json()["checks"].values())
                for path in ("/docs", "/redoc", "/openapi.json"):
                    assert client.get(path).status_code == 404
                page = client.get("/dashboard")
                assert page.status_code == 200 and "DHK Paper" in page.text
                assert "'unsafe-inline'" not in page.headers["content-security-policy"].split("script-src", 1)[1].split(";", 1)[0]
                assert "max-age=" in page.headers["strict-transport-security"]
                account = dict(username="qa_deploy_admin", email="qa-deploy@example.com", password=secrets.token_urlsafe(24))
                assert client.post("/auth/setup", json=account).status_code == 403
                assert client.post("/auth/setup", json={**account, "setup_token": values["SETUP_TOKEN"]}).status_code == 200
                login = client.post("/auth/login", json={"username": account["username"], "password": account["password"]})
                assert login.status_code == 200 and "secure" in login.headers["set-cookie"].lower() and "httponly" in login.headers["set-cookie"].lower()
                assert client.get("/web/paper/admin").status_code == 200
                streaming = client.get("/api/websocket/config").json()
                assert streaming["websocket_url"] == "wss://localhost/stream"
                from websockets.sync.client import connect
                import ssl
                key = client.get("/web/apikey").json()["api_key"]
                with connect(host.replace("https://", "wss://") + "/stream", ssl=ssl.create_default_context(cafile=str(certificate)), open_timeout=5) as ws:
                    ws.send(json.dumps({"action":"authenticate", "api_key":key}))
                    assert json.loads(ws.recv(timeout=5))["status"] == "success"
                    ws.send(json.dumps({"action":"subscribe", "symbols":[{"symbol":"NIFTY-DEMO-FUT", "exchange":"NFO"}], "mode":"LTP"}))
                    assert json.loads(ws.recv(timeout=5))["status"] == "success"
                    tick = json.loads(ws.recv(timeout=5))
                    assert tick["type"] == "market_data" and tick["data"]["data_source"] == "synthetic_demo"

                archive = client.get("/source.tar.gz")
                assert archive.status_code == 200
                with tarfile.open(fileobj=io.BytesIO(archive.content), mode="r:gz") as source_archive:
                    names = source_archive.getnames()
                    assert "./backend/security.py" in names and "./License.md" in names and "./.env.example" in names
                    assert not any(part == ".env" or (part.startswith(".env.") and part != ".env.example") or part in (".local", ".claude", ".codex", ".venv", "node_modules") for name in names for part in Path(name).parts)
                for index in range(6):
                    response = client.post("/auth/login", json={"username": "qa_proxy_limit", "password": "wrong-password"}, headers={"X-Forwarded-For": f"198.51.100.{index + 1}"})
                    assert response.status_code == (401 if index < 5 else 429)
            if args.load:
                from load_probe import run
                run(prefix,config,source,host,certificate,args.seconds,args.load_output)
            if source_fingerprint()!=expected:
                raise RuntimeError("Source changed during deployment verification")
            print("PASS: production images, local TLS verification, secure login, protected setup, authenticated WSS ticks, hidden docs, private services, trusted proxy limits and secret-free source archive")
        finally:
            subprocess.run(prefix + ["down", "--volumes", "--remove-orphans"], cwd=directory, check=True, capture_output=True)


if __name__ == "__main__":
    main()
