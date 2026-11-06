"""Delete only the QA accounts recorded by verify_paper.py, preserving user accounts."""
from pathlib import Path
import sys
import json
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import get_settings
from backend.database import Base
import backend.models
import backend.models.sandbox
import backend.models.audit
from backend.models.user import User

record = ROOT / ".local" / "qa.json"
if not record.exists():
    raise SystemExit("No owned QA accounts to remove.")
owned = json.loads(record.read_text())
names = [row["username"] for row in owned["customers"]] + [row["username"] for row in owned.get("brokers", [])] + [owned["admin"]["username"]]
assert all(name.startswith(("qa_admin_", "qa_customer_", "qa_capacity_", "qa_quota_", "qa_broker_")) for name in names)
engine = create_engine(get_settings().sync_database_url)
with Session(engine) as db:
    ids = list(db.scalars(select(User.id).where(User.username.in_(names))))
    for table in reversed(Base.metadata.sorted_tables):
        if table.name == "users":
            for role in ("user", "broker", "super_admin"):
                db.execute(delete(table).where(table.c.id.in_(ids), table.c.role == role))
        elif "user_id" in table.c:
            db.execute(delete(table).where(table.c.user_id.in_(ids)))
        elif table.name == "login_attempts":
            db.execute(delete(table).where(table.c.username.in_(names)))
    db.commit()
engine.dispose()
record.unlink()
print("Owned QA accounts and books removed. User-created accounts preserved.")

