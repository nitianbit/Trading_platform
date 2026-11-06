"""One explicit Compose target shared by backup and migration commands."""
from pathlib import Path
import json
import select
import subprocess

ROOT = Path(__file__).resolve().parents[1]
IDENTITY_SQL = "SELECT json_build_object('database',current_database(),'oid',(SELECT oid::bigint FROM pg_database WHERE datname=current_database()),'cluster',(SELECT system_identifier::text FROM pg_control_system()))"


def add_target_arguments(parser):
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--project-name")
    parser.add_argument("--compose-file")
    parser.add_argument("--env-file")


def target_arguments(args):
    values = ["--local"] if args.local else []
    for name in ("project_name", "compose_file", "env_file"):
        if getattr(args, name, None):
            values.extend(["--" + name.replace("_", "-"), getattr(args, name)])
    return values


def compose_prefix(args):
    prefix = ["docker", "compose"]
    project = args.project_name or ("dhk-paper" if args.local else None)
    if project:
        prefix.extend(["-p", project])
    environment = args.env_file or (None if args.local else str(ROOT / "deploy/.env.production"))
    if environment:
        prefix.extend(["--env-file", str(Path(environment).resolve())])
    source = args.compose_file or str(ROOT / ("compose.paper.yml" if args.local else "compose.production.yml"))
    return prefix + ["-f", str(Path(source).resolve())]


def psql_command(prefix, service, database="dhkpaper"):
    return prefix + ["exec", "-T", service, "psql", "-X", "-qAt", "-U", "dhkpaper", "-d", database, "-v", "ON_ERROR_STOP=1"]


def sql(prefix, service, statement, database="dhkpaper"):
    result = subprocess.run(psql_command(prefix,service,database) + ["-c",statement], cwd=ROOT, check=True, capture_output=True, text=True, timeout=120)
    return result.stdout.strip()


class Snapshot:
    """Keep an exported read snapshot alive until pg_dump has finished."""
    def __init__(self, prefix, service):
        self.command = psql_command(prefix,service)

    def __enter__(self):
        self.process = subprocess.Popen(self.command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.request("SET TIME ZONE 'UTC'; BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();")
            return self
        except BaseException:
            self.__exit__(None,None,None)
            raise

    def request(self, statement):
        self.process.stdin.write(statement + "\n"); self.process.stdin.flush()
        if not select.select([self.process.stdout],[],[],120)[0]:
            raise TimeoutError("Database snapshot query timed out")
        line = self.process.stdout.readline().strip()
        if not line:
            raise RuntimeError("Database snapshot query failed; no migration was performed")
        self.last = line
        return line

    def __exit__(self, *_):
        if self.process.poll() is None:
            try:
                self.process.stdin.write("ROLLBACK;\n"); self.process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate(); self.process.wait(timeout=10)
        self.process.stdout.close(); self.process.stderr.close()


def table_list(reader):
    return json.loads(reader("SELECT coalesce(json_agg(tablename ORDER BY tablename),'[]') FROM pg_tables WHERE schemaname='public';"))


def table_fingerprint(statement):
    # Numeric aggregates keep memory bounded and are insensitive to row order.
    # These checks detect restore/data drift; they are not an authentication MAC.
    quoted = '"' + statement.replace('"','""') + '"'
    digest = "md5(to_jsonb(t)::text)"
    return ("SELECT json_build_object('rows',count(*),'sum1',coalesce(sum(('x'||substr(" + digest + ",1,16))::bit(64)::bigint::numeric),0)::text,'sum2',coalesce(sum(('x'||substr(" + digest + ",17,16))::bit(64)::bigint::numeric),0)::text) FROM public." + quoted + " t;")


def fingerprints(reader):
    return {name:json.loads(reader(table_fingerprint(name))) for name in table_list(reader)}
