"""Migration preflight against a private schema in the disposable test DB."""
import os
import secrets
import unittest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


@unittest.skipUnless(os.environ.get("DHK_TEST_DB_NAME"), "Run scripts/test_isolated.py")
class ReadinessTests(unittest.TestCase):
    def test_preflight_requires_broker_for_exposure_and_rejects_delivery_inventory(self):
        from backend.config import get_settings
        from sqlalchemy.engine import make_url
        assert make_url(get_settings().database_url).database == os.environ["DHK_TEST_DB_NAME"]
        assert os.environ["DHK_TEST_DB_NAME"].startswith("dhk_test_")
        from backend.models import Base
        from backend.models.user import User
        from backend.models.sandbox import SandboxPosition, SandboxHolding
        from backend.paper.hierarchy import migrate_hierarchy
        from backend.paper.readiness import check_legacy_exposure, require_migrated
        from backend.sandbox.brokerage import quote_charge
        admin = create_engine(get_settings().sync_database_url)
        name = "preflight_" + secrets.token_hex(8)
        with admin.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{name}"'))
        engine = create_engine(get_settings().sync_database_url, connect_args={"options": "-csearch_path=" + name})
        try:
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                for uid, role in [(1,"super_admin"),(2,"user"),(3,"broker")]:
                    db.add(User(id=uid,username="preflight_"+str(uid),email=str(uid)+"@example.com",password_hash="test-only",role=role))
                db.commit()
            migrate_hierarchy(engine)
            with self.assertRaisesRegex(RuntimeError,"migrate_database"):
                require_migrated(engine)
            with Session(engine) as db:
                check_legacy_exposure(db)  # An unassigned flat account can log in for assignment.
                db.add(SandboxPosition(user_id=2,symbol="RELIANCE-DEMO",exchange="NSE",product="MIS",net_quantity=10,average_price=100))
                db.commit()
                with self.assertRaisesRegex(RuntimeError,"assign legacy"):
                    check_legacy_exposure(db)
                with self.assertRaisesRegex(ValueError,"Assign this user"):
                    quote_charge(db,2,100,10)
                db.get(User,2).broker_id=3
                db.commit()
                check_legacy_exposure(db)
                self.assertEqual(quote_charge(db,2,100,10).fee_paise,4000)
                position = db.query(SandboxPosition).filter_by(user_id=2).one()
                position.exchange = "GIFT"; position.symbol = "GIFTNIFTY-DEMO-FUT"; db.commit()
                with self.assertRaisesRegex(RuntimeError,"unsupported MIS"):
                    check_legacy_exposure(db)
                position.net_quantity = 0; db.commit()

                db.add(SandboxHolding(user_id=2,symbol="RELIANCE-DEMO",exchange="NSE",quantity=10,average_price=100))
                db.commit()
                with self.assertRaisesRegex(RuntimeError,"delivery holdings"):
                    check_legacy_exposure(db)
        finally:
            engine.dispose()
            with admin.begin() as db:
                db.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
            admin.dispose()
