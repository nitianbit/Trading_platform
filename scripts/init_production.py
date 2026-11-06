"""Generate private deployment configuration once; preserve existing values."""
from pathlib import Path
import secrets
import sys

root = Path(__file__).resolve().parents[1]
destination = root / "deploy" / ".env.production"
if destination.exists():
    raise SystemExit("Existing deployment configuration preserved.")
if len(sys.argv) != 2 or "." not in sys.argv[1] or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for char in sys.argv[1]):
    raise SystemExit("Usage: python scripts/init_production.py your.domain.example")
values = {"APP_DOMAIN": sys.argv[1], "APP_SECRET_KEY": secrets.token_hex(32),
    "ENCRYPTION_PEPPER": secrets.token_hex(32), "SETUP_TOKEN": secrets.token_hex(32),
    "POSTGRES_PASSWORD": secrets.token_hex(32), "REDIS_PASSWORD": secrets.token_hex(32)}
with destination.open("x") as file:
    destination.chmod(0o600)
    file.write("".join(f'{key}="{value}"\n' for key, value in values.items()))
print("Private deployment configuration generated; no credentials printed.")
