"""Private backup with content verification against the same exported snapshot."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import os
import re
import secrets
import subprocess
from deployment_target import ROOT, add_target_arguments, compose_prefix, sql, Snapshot, fingerprints, IDENTITY_SQL


def main():
    parser = argparse.ArgumentParser()
    add_target_arguments(parser)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".local/backups")
    parser.add_argument("--receipt-file", type=Path)
    args = parser.parse_args()
    prefix = compose_prefix(args); service = "database" if args.local else "db"
    directory = args.output_dir.resolve(); directory.mkdir(parents=True,mode=0o700,exist_ok=True); directory.chmod(0o700)
    destination = directory / (datetime.now(timezone.utc).strftime("dhkpaper-%Y%m%dT%H%M%SZ-") + secrets.token_hex(4) + ".dump")
    fd = os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,"wb") as output, Snapshot(prefix,service) as snapshot:
            snapshot_id = snapshot.last
            if not re.fullmatch(r"[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+",snapshot_id):
                raise RuntimeError("Invalid PostgreSQL snapshot identity")
            identity = json.loads(snapshot.request(IDENTITY_SQL + ";"))
            expected = fingerprints(snapshot.request) if args.verify else None
            subprocess.run(prefix + ["exec","-T",service,"pg_dump","-U","dhkpaper","-d","dhkpaper","-Fc","--snapshot="+snapshot_id],cwd=ROOT,stdout=output,check=True,timeout=600)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    if args.verify:
        scratch = "dhk_restore_" + secrets.token_hex(8)
        sql(prefix,service,f'CREATE DATABASE "{scratch}"',"postgres")
        try:
            with destination.open("rb") as source:
                subprocess.run(prefix+["exec","-T",service,"pg_restore","-U","dhkpaper","-d",scratch,"--no-owner","--exit-on-error"],cwd=ROOT,stdin=source,check=True,timeout=600)
            actual = fingerprints(lambda query:sql(prefix,service,"SET TIME ZONE 'UTC'; " + query,scratch))
            if actual != expected:
                raise RuntimeError("Restore content differs from the backup snapshot (table, row count or row checksum)")
            print("Backup restored: every table's row count and row checksums match the exported source snapshot.")
        finally:
            sql(prefix,service,f'DROP DATABASE "{scratch}" WITH (FORCE)',"postgres")
    receipt = {"database":identity,"verified":args.verify,"tables":expected,"backup":str(destination)}
    receipt_paths = [destination.with_suffix(".json")]
    if args.receipt_file and args.receipt_file != receipt_paths[0]:
        receipt_paths.append(args.receipt_file)
    for receipt_path in receipt_paths:
        with os.fdopen(os.open(receipt_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),"w") as output:
            json.dump(receipt,output)
    print("Private backup created: " + str(destination))


if __name__ == "__main__":
    main()
