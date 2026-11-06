"""Hold a database-session lease for the lifetime of one application runtime."""
from contextlib import contextmanager
import psycopg
from sqlalchemy.engine import make_url
from backend.config import get_settings


@contextmanager
def single_runtime():
    url = make_url(get_settings().database_url).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False), autocommit=True) as connection:
        if not connection.execute("SELECT pg_try_advisory_lock(2083, 1)").fetchone()[0]:
            raise RuntimeError("Another DHK runtime owns this database; use one worker")
        yield
