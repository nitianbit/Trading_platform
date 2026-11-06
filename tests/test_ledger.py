"""Production ledger paths against PostgreSQL, never the owner's database."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from sqlalchemy import select, func, delete


@unittest.skipUnless(os.environ.get("DHK_TEST_DB_NAME"), "Run scripts/test_isolated.py for database tests")
class LedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.config import get_settings
        from sqlalchemy.engine import make_url
        name = os.environ["DHK_TEST_DB_NAME"]
        assert name.startswith("dhk_test_") and make_url(get_settings().database_url).database == name
        from backend.models import Base
        from backend.models.sandbox import SandboxFund
        from backend.sandbox._db import get_engine
        Base.metadata.create_all(get_engine())
        from backend.paper.market import seed_symbols
        seed_symbols()
        from backend.models.user import User
        from backend.sandbox._db import session_scope
        with session_scope() as db:
            assert db.get(User, 1) is None
            db.add(User(id=1, username="ledger_fixture", email="ledger-fixture@example.com", password_hash="test-only", role="broker"))

    @classmethod
    def tearDownClass(cls):
        from backend.models.user import User
        from backend.sandbox._db import session_scope
        with session_scope() as db:
            row = db.get(User, 1)
            assert row.username == "ledger_fixture"
            db.delete(row)

    def setUp(self):
        from backend.models.sandbox import SandboxOrder, SandboxPosition, SandboxTrade, SandboxFund
        from backend.sandbox._db import session_scope
        from backend.models.settings import AppSettings
        from backend.paper.policy import POLICY_KEY
        with session_scope() as db:
            db.execute(delete(AppSettings).where(AppSettings.key == POLICY_KEY))
            for model in (SandboxTrade, SandboxOrder, SandboxPosition, SandboxFund):
                db.execute(delete(model))
        self.quote = patch("backend.services.sandbox_service.get_ltp_with_fallback", return_value=25000.0)
        self.quote.start()
        self.addCleanup(self.quote.stop)

    def place(self, **changes):
        from backend.services.sandbox_service import place_order
        ok, data, status = place_order(1, {**dict(symbol="NIFTY-DEMO-FUT", exchange="NFO", product="NRML", pricetype="MARKET", action="BUY", quantity=25), **changes})
        self.assertTrue(ok, data)
        self.assertEqual(status, 200)
        return data["orderid"]

    def pending(self, **changes):
        return self.place(**{**dict(pricetype="LIMIT", price=20000), **changes})

    def snapshot(self):
        from backend.sandbox.fund_manager import get_funds_snapshot
        return get_funds_snapshot(1)

    def assert_book(self):
        from backend.models.sandbox import SandboxFund, SandboxPosition, SandboxOrder
        from backend.sandbox._db import session_scope
        with session_scope() as db:
            fund = db.scalar(select(SandboxFund).where(SandboxFund.user_id == 1))
            expected = sum(db.scalars(select(SandboxPosition.margin_blocked).where(SandboxPosition.user_id == 1, SandboxPosition.net_quantity != 0)))
            expected += sum(db.scalars(select(SandboxOrder.margin_blocked).where(SandboxOrder.user_id == 1, SandboxOrder.status.in_(["open", "trigger_pending"]))))
            self.assertAlmostEqual(fund.used_margin, expected, places=2)
            self.assertAlmostEqual(fund.available + fund.used_margin, fund.starting_capital + fund.realized_pnl, places=2)

    def test_reconcile_then_cancel_cannot_create_cash(self):
        from backend.sandbox import fund_manager
        from backend.services.sandbox_service import cancel_order
        before = self.snapshot()
        for _ in range(3):
            oid = self.pending()
            consistent, _, _ = fund_manager.reconcile_margin(1)
            self.assertTrue(consistent)
            self.assertTrue(cancel_order(1, oid)[0])
            self.assert_book()
        self.assertEqual(self.snapshot(), before)

    def test_release_cannot_credit_more_than_reserved(self):
        from backend.sandbox import fund_manager
        before = self.snapshot()
        fund_manager.block_margin(1, 100)
        fund_manager.release_margin(1, 500)
        self.assertEqual(self.snapshot(), before)

    def test_modify_preserves_omitted_fields_and_rejects_invalid_changes(self):
        from backend.services.sandbox_service import modify_order
        from backend.sandbox.order_manager import get_order
        oid = self.pending()
        self.assertTrue(modify_order(1, dict(orderid=oid, quantity=50))[0])
        self.assertEqual(get_order(1, oid).price, 20000)
        self.assert_book()
        for changes in (dict(quantity=-25), dict(quantity=1), dict(price=20000.03), dict(pricetype="BOGUS"), dict(price=float("nan")), dict(quantity=40000, price=30000)):
            with self.subTest(changes=changes):
                before = self.snapshot()
                self.assertFalse(modify_order(1, dict(orderid=oid, **changes))[0])
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(get_order(1, oid).quantity, 50)

    def test_pending_opening_order_later_closes_without_orphan_margin(self):
        from backend.sandbox.execution_engine import _try_fill_order
        from backend.sandbox.order_manager import get_order
        oid = self.pending(action="SELL", price=30000)
        self.place()
        self.assertTrue(_try_fill_order(get_order(1, oid), 31000))
        self.assertEqual(self.snapshot()["utiliseddebits"], 0)
        self.assert_book()

    def test_pending_reducing_order_later_opens_with_margin(self):
        from backend.sandbox.execution_engine import _try_fill_order
        from backend.sandbox.order_manager import get_order
        self.place()
        oid = self.pending(action="SELL", price=30000)
        self.place(action="SELL")
        self.assertTrue(_try_fill_order(get_order(1, oid), 31000))
        self.assertGreater(self.snapshot()["utiliseddebits"], 0)
        self.assert_book()

    def test_duplicate_and_cancel_fill_races_preserve_one_transition(self):
        from backend.sandbox import order_manager
        from backend.models.sandbox import SandboxTrade
        from backend.sandbox._db import session_scope
        for cancel in (False, True):
            for attempt in range(10):
                oid = self.pending()
                barrier = Barrier(2)
                def run(index):
                    barrier.wait()
                    if cancel and index == 0:
                        return order_manager.cancel_order(1, oid)
                    return order_manager.fill(1, oid, 20000)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    list(pool.map(run, range(2)))
                with session_scope() as db:
                    trades = db.scalar(select(func.count()).select_from(SandboxTrade).where(SandboxTrade.orderid == oid))
                    self.assertLessEqual(trades, 1)
                    if not cancel:
                        self.assertEqual(trades, 1)
                self.assert_book()

    def test_expired_contract_rejected_and_demo_metadata_refreshed(self):
        from datetime import date, timedelta
        from backend.models.symbol import SymToken
        from backend.sandbox._db import session_scope
        from backend.services.sandbox_service import place_order
        from backend.paper.market import seed_symbols
        with session_scope() as db:
            symbol = db.scalar(select(SymToken).where(SymToken.symbol == "NIFTY-DEMO-FUT"))
            previous = symbol.expiry
            symbol.expiry = (date.today() - timedelta(days=1)).isoformat()
        try:
            result = place_order(1, dict(symbol="NIFTY-DEMO-FUT", exchange="NFO", action="BUY", quantity=25, pricetype="MARKET", product="NRML"))
            self.assertFalse(result[0])
            seed_symbols()
            with session_scope() as db:
                symbol = db.scalar(select(SymToken).where(SymToken.symbol == "NIFTY-DEMO-FUT"))
                self.assertGreater(date.fromisoformat(symbol.expiry), date.today())
        finally:
            with session_scope() as db:
                db.scalar(select(SymToken).where(SymToken.symbol == "NIFTY-DEMO-FUT")).expiry = previous

    def test_fill_rollback_and_partial_reservation(self):
        from backend.sandbox import order_manager, position_manager
        oid = self.pending(quantity=50)
        before = self.snapshot()
        with patch.object(position_manager, "apply_fill", side_effect=RuntimeError("injected transaction failure")):
            with self.assertRaises(RuntimeError):
                order_manager.fill(1, oid, 20000)
        self.assertEqual(order_manager.get_order(1, oid).filled_quantity, 0)
        self.assertEqual(self.snapshot(), before)
        self.assert_book()
        order_manager.fill(1, oid, 20000, 25)
        self.assertEqual(order_manager.get_order(1, oid).filled_quantity, 25)
        self.assert_book()
        order_manager.fill(1, oid, 20000)
        self.assert_book()

    def test_engine_rechecks_modified_order_and_fill_funds(self):
        from backend.sandbox import order_manager
        from backend.sandbox.execution_engine import _try_fill_order
        oid = self.pending()
        stale = order_manager.get_order(1, oid)
        order_manager.modify_order(1, oid, price=1000)
        self.assertFalse(_try_fill_order(stale, 15000))
        self.assertEqual(order_manager.get_order(1, oid).status, "open")
        order_manager.cancel_order(1, oid)
        self.place()
        oid = self.pending(action="SELL", price=100000000)
        self.place(action="SELL")
        self.assertFalse(_try_fill_order(order_manager.get_order(1, oid), 100000001))
        self.assertEqual(order_manager.get_order(1, oid).status, "rejected")
        self.assertEqual(self.snapshot()["utiliseddebits"], 0)
        self.assert_book()

    def test_legacy_key_migration_preserves_keys_and_is_idempotent(self):
        from argon2 import PasswordHasher
        from backend.config import get_settings
        from backend.models.user import User
        from backend.models.auth import ApiKey
        from backend.security import migrate_api_keys, hash_api_key, encrypt_value, decrypt_value
        from backend.sandbox._db import session_scope, get_engine
        key = "test-only-key-not-an-owner-credential"
        with session_scope() as db:
            user = User(username="qa_migration", email="qa-migration@example.com", password_hash="not-a-login-hash", role="broker")
            db.add(user)
            db.flush()
            uid = user.id
            db.add(ApiKey(user_id=uid, api_key_hash=PasswordHasher().hash(key + get_settings().encryption_pepper), api_key_encrypted=encrypt_value(key)))
        try:
            migrate_api_keys(get_engine())
            migrate_api_keys(get_engine())
            with session_scope() as db:
                row = db.scalar(select(ApiKey).where(ApiKey.api_key_hash == hash_api_key(key)))
                self.assertEqual(row.user_id, uid)
                self.assertEqual(decrypt_value(row.api_key_encrypted), key)
        finally:
            with session_scope() as db:
                db.execute(delete(ApiKey).where(ApiKey.user_id == uid))
                db.execute(delete(User).where(User.id == uid))

    def test_only_one_runtime_can_own_the_database(self):
        from backend.paper.runtime import single_runtime
        with single_runtime():
            with self.assertRaises(RuntimeError):
                with single_runtime():
                    self.fail("second runtime acquired the same database")
        with single_runtime():
            pass

    def test_concurrent_placements_cannot_overspend(self):
        from backend.services.sandbox_service import place_order
        from backend.sandbox.order_manager import list_cancellable_orders, cancel_order
        barrier = Barrier(10)
        def place(index):
            barrier.wait()
            return place_order(1, dict(symbol="NIFTY-DEMO-FUT", exchange="NFO", product="NRML", pricetype="LIMIT", action="BUY", quantity=100, price=20000))
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(place, range(10)))
        self.assertEqual(sum(result[0] for result in results), 5)
        self.assertEqual(self.snapshot()["availablecash"], 0)
        self.assert_book()
        for order in list_cancellable_orders(1):
            cancel_order(1, order.orderid)
        self.assertEqual(self.snapshot()["availablecash"], 10000000)
        self.assert_book()

    def test_nonfinite_and_oversized_inputs_do_not_poison_order_history(self):
        from backend.services.sandbox_service import place_order
        from backend.sandbox.order_manager import list_orders
        for changes in ({"price": float("nan")}, {"trigger_price": float("inf")}, {"quantity": 10**40}):
            result = place_order(1, {**dict(symbol="NIFTY-DEMO-FUT", exchange="NFO", product="NRML", pricetype="LIMIT", action="BUY", quantity=25, price=20000), **changes})
            self.assertFalse(result[0])
        self.assertEqual(list_orders(1, all_history=True), [])

    def test_ledger_reuses_its_connection_for_validation_and_margin(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.config import get_settings
        from backend.sandbox import order_manager
        engine = create_engine(get_settings().sync_database_url, pool_size=1, max_overflow=0, pool_timeout=0.2)
        factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
        try:
            with patch("backend.sandbox._db._session_factory", factory):
                oid = self.pending()
                order_manager.modify_order(1, oid, quantity=50)
                order_manager.fill(1, oid, 20000)
                self.assert_book()
        finally:
            engine.dispose()

    def disable_nse(self):
        from backend.models.settings import AppSettings
        from backend.paper.policy import POLICY_KEY, PlatformPolicy
        from backend.sandbox._db import session_scope
        with session_scope() as db:
            db.add(AppSettings(key=POLICY_KEY, value=PlatformPolicy(disabled_groups=["NSE Futures"]).model_dump_json()))

    def test_disabled_market_blocks_openings_and_reversals_but_allows_exits(self):
        from backend.services.sandbox_service import place_order
        self.place()
        self.disable_nse()
        template = dict(symbol="NIFTY-DEMO-FUT", exchange="NFO", product="NRML", pricetype="MARKET", action="BUY", quantity=25)
        for changes in ({}, {"action": "SELL", "quantity": 50}):
            self.assertFalse(place_order(1, {**template, **changes})[0])
            self.assert_book()
        self.place(action="SELL")
        self.assertEqual(self.snapshot()["utiliseddebits"], 0)
        self.assert_book()

    def test_disabled_market_rechecks_pending_orders_before_fill_and_modification(self):
        from backend.sandbox import order_manager
        oid = self.pending()
        self.disable_nse()
        with self.assertRaises(order_manager.OrderValidationError):
            order_manager.modify_order(1, oid, quantity=50)
        self.assertEqual(order_manager.fill(1, oid, 20000), (None, None))
        self.assertEqual(order_manager.get_order(1, oid).status, "rejected")
        self.assertEqual(self.snapshot()["utiliseddebits"], 0)
        self.assert_book()

    def test_partially_filled_exit_can_be_modified_after_market_disabled(self):
        from backend.sandbox import order_manager
        self.place(quantity=50)
        oid = self.pending(action="SELL", quantity=50, price=30000)
        order_manager.fill(1, oid, 30000, 25)
        self.disable_nse()
        order_manager.modify_order(1, oid, price=31000)
        order_manager.fill(1, oid, 31000)
        self.assertEqual(self.snapshot()["utiliseddebits"], 0)
        self.assert_book()
