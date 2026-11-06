"""Prepare local owner/demo access without resetting existing accounts."""
from pathlib import Path
import json
import os
import secrets

import httpx

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
from backend.config import get_settings
LOCAL = ROOT / ".local"
RECORD = LOCAL / "owner-access.json"
NOTE = LOCAL / "owner-access.md"


def save(accounts):
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    LOCAL.chmod(0o700)
    with os.fdopen(os.open(RECORD, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as file:
        json.dump(accounts, file)
    RECORD.chmod(0o600)


def login(client, account):
    response = client.post("/auth/login", json={key: account[key] for key in ("username", "password")})
    response.raise_for_status()
    response = client.get("/auth/me")
    response.raise_for_status()
    return response.json()


def main():
    with httpx.Client(base_url="http://127.0.0.1:8083", timeout=20) as admin:
        response = admin.get("/auth/check-setup")
        response.raise_for_status()
        needs_setup = response.json()["needs_setup"]
        if RECORD.exists():
            accounts = json.loads(RECORD.read_text())
        elif needs_setup:
            accounts = {
                "admin": dict(username="dhk", email="dhk@example.com", password=secrets.token_urlsafe(24)),
                "customer": dict(username="dhk_demo", email="dhk-demo@example.com", password=secrets.token_urlsafe(24)),
            }
            save(accounts)
        else:
            raise SystemExit("Existing accounts have no owner-access record. No credentials were changed.")
        if needs_setup:
            admin.post("/auth/setup", json={**accounts["admin"], "setup_token": get_settings().setup_token}).raise_for_status()
        assert login(admin, accounts["admin"])["is_admin"] is True
        response = admin.get("/web/paper/users")
        response.raise_for_status()
        if not any(row["username"] == accounts["customer"]["username"] for row in response.json()):
            raise SystemExit("Demo user is absent. Activate a broker and create its user invitation from the web app; no account was created by this helper.")
        with httpx.Client(base_url="http://127.0.0.1:8083", timeout=20) as customer:
            me = login(customer, accounts["customer"])
            assert me["is_admin"] is False and me["paper_only"] is True
            customer.get("/web/dashboard").raise_for_status()
            assert customer.get("/web/paper/admin").status_code == 403
            customer.post("/auth/logout").raise_for_status()
        overview = admin.get("/web/paper/admin")
        overview.raise_for_status()
        assert any(row["username"] == "dhk_demo" for row in overview.json()["accounts"])
        admin.post("/auth/logout").raise_for_status()
    note = "# DHK Paper local access\n\nAdmin: http://127.0.0.1:5183/admin\nTrading desk: http://127.0.0.1:5183/dashboard\nBackend docs: http://127.0.0.1:8083/docs\n\n"
    for label, account in accounts.items():
        note += f"## {label.title()}\n\nUsername: `{account['username']}`\nPassword: `{account['password']}`\n\n"
    note += "Local paper demo with synthetic prices and virtual INR. These logins are separate from Alpha. Keep this file private.\n"
    with os.fdopen(os.open(NOTE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as file:
        file.write(note)
    NOTE.chmod(0o600)
    print(f"Admin and demo customer verified. Private access details: {NOTE}")


if __name__ == "__main__":
    main()
