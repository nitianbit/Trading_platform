"""The operator migration command: verify a matching backup before any DDL."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deployment_target import add_target_arguments, compose_prefix, target_arguments, IDENTITY_SQL


def main():
    parser = argparse.ArgumentParser()
    add_target_arguments(parser)
    parser.add_argument("--backup-dir",type=Path,default=ROOT/".local/backups")
    parser.add_argument("--inside-container",action="store_true",help=argparse.SUPPRESS)
    parser.add_argument("--expected-database",help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside_container:
        if not args.expected_database:
            parser.error("Internal migration requires the identity of a restore-verified backup")
        expected = json.loads(args.expected_database)
    else:
        with tempfile.TemporaryDirectory(prefix="dhk-migration-") as temp:
            receipt = Path(temp)/"receipt.json"
            subprocess.run([sys.executable,str(ROOT/"scripts/database_backup.py"),*target_arguments(args),"--verify","--output-dir",str(args.backup_dir),"--receipt-file",str(receipt)],cwd=ROOT,check=True)
            evidence = json.loads(receipt.read_text())
            if evidence.get("verified") is not True:
                raise RuntimeError("A restore-verified backup is required")
            expected = evidence["database"]
        if not args.local:
            subprocess.run(compose_prefix(args)+["run","--rm","--no-deps","backend","python","scripts/migrate_database.py","--inside-container","--expected-database",json.dumps(expected)],cwd=ROOT,check=True)
            return
    from backend.sandbox._db import get_engine
    from sqlalchemy import text, select
    engine = get_engine()
    with engine.connect() as connection:
        actual = connection.scalar(text(IDENTITY_SQL))
    if actual != expected:
        raise RuntimeError("Backup and migration database identities differ; no schema changes were made")
    from backend.models import Base
    from backend.utils.schema_migrations import run_startup_migrations
    from backend.security import migrate_api_keys
    from backend.paper.readiness import check_legacy_exposure, SCHEMA_KEY, SCHEMA_VERSION
    from backend.models.settings import AppSettings
    from sqlalchemy.orm import Session
    Base.metadata.create_all(engine)
    run_startup_migrations(); migrate_api_keys(engine)
    with Session(engine) as db:
        check_legacy_exposure(db)
        row=db.scalar(select(AppSettings).where(AppSettings.key==SCHEMA_KEY))
        if row is None: db.add(AppSettings(key=SCHEMA_KEY,value=SCHEMA_VERSION))
        else: row.value=SCHEMA_VERSION
        db.commit()
    print("Database identity, restore verification, migration and launch preflight passed.")


if __name__ == "__main__": main()
