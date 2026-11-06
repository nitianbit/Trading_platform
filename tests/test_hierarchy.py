"""Permanent account ownership and upgrade behavior in a disposable PostgreSQL DB."""
import os
import secrets
import unittest
from sqlalchemy import select, text, create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session


@unittest.skipUnless(os.environ.get("DHK_TEST_DB_NAME"), "Run scripts/test_isolated.py")
class HierarchyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.config import get_settings
        from sqlalchemy.engine import make_url
        assert make_url(get_settings().database_url).database == os.environ["DHK_TEST_DB_NAME"]
        assert os.environ["DHK_TEST_DB_NAME"].startswith("dhk_test_")
        from backend.models import Base
        from backend.sandbox._db import get_engine
        from backend.paper.hierarchy import migrate_hierarchy
        cls.engine = get_engine()
        Base.metadata.create_all(cls.engine)
        migrate_hierarchy(cls.engine)
        migrate_hierarchy(cls.engine)

    def test_new_users_require_a_broker_and_ownership_cannot_change(self):
        from backend.models.user import User
        suffix = secrets.token_hex(5)
        def account(name, **fields):
            return User(username=name+suffix, email=name+suffix+"@example.com", password_hash="test-only-not-a-password", **fields)
        with Session(self.engine) as db:
            first, second = account("broker_a", role="broker"), account("broker_b", role="broker")
            db.add_all([first, second]); db.commit()
            child = account("user", role="user", broker_id=first.id)
            db.add(child); db.commit()
            ids = first.id, second.id, child.id
        try:
            for statement, values in [
                ("UPDATE users SET broker_id=:other WHERE id=:id", {"other": ids[1], "id": ids[2]}),
                ("UPDATE users SET broker_id=NULL WHERE id=:id", {"id": ids[2]}),
                ("UPDATE users SET role='super_admin' WHERE id=:id", {"id": ids[2]}),
                ("DELETE FROM users WHERE id=:id", {"id": ids[0]}),
            ]:
                with self.subTest(sql=statement), self.assertRaises(DBAPIError), self.engine.begin() as db:
                    db.execute(text(statement), values)
            with self.assertRaises(DBAPIError), Session(self.engine) as db:
                db.add(account("unowned", role="user")); db.commit()
            with Session(self.engine) as db:
                self.assertEqual(db.get(User, ids[2]).broker_id, ids[0])
                self.assertEqual(db.get(User, ids[2]).role, "user")
        finally:
            with self.engine.begin() as db:
                db.execute(text("DELETE FROM users WHERE id=:id"), {"id": ids[2]})
                db.execute(text("DELETE FROM users WHERE id IN (:a,:b)"), {"a": ids[0], "b": ids[1]})

    def test_upgrade_preserves_legacy_accounts_and_allows_only_one_assignment(self):
        from backend.config import get_settings
        from backend.paper.hierarchy import migrate_hierarchy
        name = "hierarchy_" + secrets.token_hex(8)
        with self.engine.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{name}"'))
        legacy = create_engine(get_settings().sync_database_url, connect_args={"options": f"-csearch_path={name}"})
        try:
            with legacy.begin() as db:
                db.execute(text("CREATE TABLE users(id SERIAL PRIMARY KEY, username VARCHAR(80) UNIQUE NOT NULL, email VARCHAR(120) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL, is_admin BOOLEAN NOT NULL, created_at TIMESTAMPTZ DEFAULT now())"))
                db.execute(text("INSERT INTO users(username,email,password_hash,is_admin) VALUES ('owner','owner@example.com','preserve-owner',TRUE),('legacy','legacy@example.com','preserve-user',FALSE)"))
            migrate_hierarchy(legacy)
            migrate_hierarchy(legacy)
            with legacy.begin() as db:
                rows = db.execute(text("SELECT id,role,password_hash,broker_id FROM users ORDER BY id")).all()
                self.assertEqual(rows, [(1, "super_admin", "preserve-owner", None), (2, "user", "preserve-user", None)])
                from backend.sandbox.brokerage import quote_charge
                with Session(legacy) as session:
                    with self.assertRaisesRegex(ValueError, "Assign this user"):
                        quote_charge(session, 2, 1, 1)
                parent = db.scalar(text("INSERT INTO users(username,email,password_hash,role) VALUES ('broker','broker@example.com','test','broker') RETURNING id"))
                db.execute(text("UPDATE users SET broker_id=:parent WHERE id=2"), {"parent": parent})
            with self.assertRaises(DBAPIError), legacy.begin() as db:
                db.execute(text("UPDATE users SET broker_id=NULL WHERE id=2"))
        finally:
            legacy.dispose()
            with self.engine.begin() as db:
                db.execute(text(f'DROP SCHEMA "{name}" CASCADE'))

    def test_invitation_expiry_consumption_and_broker_state_are_rechecked(self):
        import asyncio
        from datetime import datetime, timedelta, timezone
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy.pool import NullPool
        from backend.config import get_settings
        from backend.models.user import User
        from backend.models.invitation import AccountInvitation
        from backend.paper.hierarchy import invitation_hash, invitation_account
        suffix = secrets.token_hex(5)
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        with Session(self.engine) as db:
            broker = User(username="expiry_broker_"+suffix, email="expiry-broker-"+suffix+"@example.com", password_hash="test", role="broker")
            db.add(broker); db.flush()
            child = User(username="expiry_user_"+suffix, email="expiry-user-"+suffix+"@example.com", password_hash="test", role="user", broker_id=broker.id, password_set=False)
            db.add(child); db.flush()
            bid, uid = broker.id, child.id
            db.add(AccountInvitation(user_id=uid, token_hash=invitation_hash(token), expires_at=now+timedelta(hours=1)))
            db.commit()
        async def scenario():
            engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    invite, user = await invitation_account(session, token)
                    self.assertEqual(user.id, uid)
                    # Reuse the same request session: a prior preview must not cache broker permission.
                    with Session(self.engine) as db:
                        db.get(User, bid).is_active = False; db.commit()
                    self.assertEqual(await invitation_account(session, token, lock=True), (None, None))
                    await session.rollback()
                    with Session(self.engine) as db:
                        db.get(User, bid).is_active = True
                        db.get(AccountInvitation, uid).expires_at = now-timedelta(seconds=1)
                        db.commit()
                    self.assertEqual(await invitation_account(session, token), (None, None))
                    await session.rollback()
                    with Session(self.engine) as db:
                        row = db.get(AccountInvitation, uid)
                        row.expires_at = now+timedelta(hours=1); row.accepted_at = now
                        db.commit()
                    self.assertEqual(await invitation_account(session, token), (None, None))
                    self.assertEqual(await invitation_account(session, secrets.token_urlsafe(32)), (None, None))
            finally:
                await engine.dispose()
        try:
            asyncio.run(scenario())
        finally:
            with Session(self.engine) as db:
                db.delete(db.get(AccountInvitation, uid)); db.flush()
                db.delete(db.get(User, uid)); db.flush()
                db.delete(db.get(User, bid)); db.commit()
