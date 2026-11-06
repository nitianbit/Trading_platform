"""Create private local configuration once; preserve existing configuration."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
env = root / ".env"
if env.exists():
    print("Existing .env preserved.")
else:
    password = secrets.token_hex(24)
    values = {
        "SETUP_TOKEN": secrets.token_hex(32),
        "APP_SECRET_KEY": secrets.token_hex(32),
        "ENCRYPTION_PEPPER": secrets.token_hex(32),
        "POSTGRES_USER": "dhkpaper",
        "POSTGRES_PASSWORD": password,
        "POSTGRES_DB": "dhkpaper",
        "DATABASE_URL": f"postgresql+asyncpg://dhkpaper:{password}@127.0.0.1:55483/dhkpaper",
        "REDIS_URL": "redis://127.0.0.1:56383/0",
        "BACKEND_PORT": "8083",
        "FRONTEND_URL": "http://127.0.0.1:5183",
        "CORS_ORIGINS": "http://127.0.0.1:5183,http://localhost:5183",
        "WEBSOCKET_PORT": "8783",
        "WEBSOCKET_URL": "ws://127.0.0.1:8783",
        "ZMQ_PORT": "5583",
        "VALID_BROKERS": "demo",
        "FLASK_DEBUG": "false",
    }
    env.write_text("".join(f'{key}="{value}"\n' for key, value in values.items()))
    env.chmod(0o600)
    print("Created private .env for DHK Paper. No broker credentials are needed.")
