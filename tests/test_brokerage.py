"""Brokerage conservation and atomic settlement through the production paper ledger."""
import os
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from sqlalchemy import select, func, delete


class SplitTests(unittest.TestCase):
    def test_exact_paise_split_and_fractional_rounding_conserve_every_charge(self):
        from backend.sandbox.brokerage import split_paise
        self.assertEqual(split_paise(1, 1), (100, 4, 3, 1))
        self.assertEqual(split_paise(100, 1), (10000, 400, 300, 100))
        for price in (0.0025, 0.05, 0.1, 0.5, 1.125, 100.05, 95000):
            for qty in (1, 25, 1000):
                _, fee, broker, admin = split_paise(price, qty)
                self.assertEqual(fee, broker+admin)
                self.assertGreaterEqual(admin, 0)
        for price in (float("inf"), float("nan"), -1, 1e100):
            with self.assertRaises(ValueError):
                split_paise(price, 1)


@unittest.skipUnless(os.environ.get("DHK_TEST_DB_NAME"), "Run scripts/test_isolated.py")
class BrokerageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.config import get_settings
        from sqlalchemy.engine import make_url
        assert make_url(get_settings().database_url).database == os.environ["DHK_TEST_DB_NAME"]
        assert os.environ["DHK_TEST_DB_NAME"].startswith("dhk_test_")
        from backend.models import Base
        from backend.sandbox._db import get_engine
        from backend.paper.hierarchy import migrate_hierarchy
        Base.metadata.create_all(get_engine())
        migrate_hierarchy(get_engine())
        from backend.paper.market import seed_symbols
        seed_symbols()

    def setUp(self):
        clock = patch("backend.sandbox.order_validation.is_after_squareoff", return_value=False)
        clock.start(); self.addCleanup(clock.stop)
        from backend.models.user import User
        from backend.models.settings import AppSettings
        from backend.paper.policy import POLICY_KEY
        from backend.sandbox._db import session_scope
        suffix = secrets.token_hex(5)
        def account(name, role, broker_id=None):
            return User(username=name+suffix, email=name+suffix+"@example.com", password_hash="test-only", role=role, broker_id=broker_id)
        with session_scope() as db:
            db.execute(delete(AppSettings).where(AppSettings.key == POLICY_KEY))
            owner, broker, other = account("fee_owner", "super_admin"), account("fee_broker", "broker"), account("fee_other", "broker")
            db.add_all([owner, broker, other]); db.flush()
            user = account("fee_user", "user", broker.id)
            db.add(user); db.flush()
            self.owner, self.broker, self.other, self.uid = owner.id, broker.id, other.id, user.id
            self.child_ids = [self.uid]

    def tearDown(self):
        from backend.models.user import User
        from backend.models.sandbox import SandboxBrokerage, SandboxTrade, SandboxOrder, SandboxPosition, SandboxFund, SandboxDailyPnL
        from backend.sandbox._db import session_scope
        with session_scope() as db:
            for model in (SandboxBrokerage, SandboxTrade, SandboxOrder, SandboxPosition, SandboxFund, SandboxDailyPnL):
                db.execute(delete(model).where(model.user_id.in_(self.child_ids)))
            db.execute(delete(User).where(User.id.in_(self.child_ids)))
            db.execute(delete(User).where(User.id.in_([self.owner, self.broker, self.other])))

    def order(self, *, qty=1, price=1, side="BUY", future=False):
        from backend.sandbox.order_manager import create_order
        return create_order(user_id=self.uid, symbol="NIFTY-DEMO-FUT" if future else "RELIANCE-DEMO",
            exchange="NFO" if future else "NSE", action=side, quantity=qty, pricetype="LIMIT",
            product="NRML" if future else "MIS", price=price, reference_price=price)

    def cash(self):
        from backend.sandbox.fund_manager import get_funds_snapshot
        return get_funds_snapshot(self.uid)

    def charges(self):
        from backend.models.sandbox import SandboxBrokerage
        from backend.sandbox._db import session_scope
        with session_scope() as db:
            return db.execute(select(func.count(),func.coalesce(func.sum(SandboxBrokerage.fee_paise),0),
                func.coalesce(func.sum(SandboxBrokerage.broker_paise),0),func.coalesce(func.sum(SandboxBrokerage.admin_paise),0))
                .where(SandboxBrokerage.user_id==self.uid)).one()

    def capital(self, amount):
        from backend.sandbox.fund_manager import ensure_fund_row
        from backend.sandbox._db import session_scope
        with session_scope() as db:
            fund = ensure_fund_row(db, self.uid)
            fund.starting_capital = fund.available = amount

    def test_one_rupee_buy_and_sell_charge_four_paise_each_and_credit_three_one(self):
        from backend.sandbox.order_manager import fill, list_trades, trade_to_dict
        fill(self.uid, self.order().orderid, 1)
        fill(self.uid, self.order(side="SELL").orderid, 1)
        self.assertEqual(self.charges(), (2, 8, 6, 2))
        self.assertEqual(self.cash()["brokerage_paid"], .08)
        self.assertEqual(self.cash()["m2mrealized"], -.08)
        self.assertEqual(self.cash()["availablecash"], 9999999.92)
        self.assertEqual(self.cash()["utiliseddebits"], 0)
        for trade in list_trades(self.uid, all_history=True):
            row = trade_to_dict(trade)
            self.assertEqual((row["trade_value"],row["brokerage"],row["broker_credit"],row["admin_credit"]), (1,.04,.03,.01))

    def test_partial_fills_charge_only_executed_value_and_cancel_is_free(self):
        from backend.sandbox.order_manager import fill, cancel_order
        order = self.order(qty=50, price=100, future=True)
        fill(self.uid, order.orderid, 100, 25)
        self.assertEqual(self.charges(), (1,10000,7500,2500))
        cancel_order(self.uid, order.orderid)
        self.assertEqual(self.charges(), (1,10000,7500,2500))
        pending = self.order(qty=25, price=100, future=True)
        cancel_order(self.uid, pending.orderid)
        self.assertEqual(self.charges(), (1,10000,7500,2500))

    def test_duplicate_fill_race_cannot_charge_or_credit_twice(self):
        from backend.sandbox.order_manager import fill
        order = self.order()
        barrier = Barrier(2)
        def run(_):
            barrier.wait(); return fill(self.uid, order.orderid, 1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        self.assertEqual(sum(trade is not None for _,trade in results),1)
        self.assertEqual(self.charges(),(1,4,3,1))

    def test_insufficient_fee_funds_reject_at_placement_and_at_fill_without_credits(self):
        from backend.sandbox.order_manager import fill, get_order, cancel_order
        self.capital(100)
        rejected = self.order(price=100)
        self.assertEqual(rejected.status,"rejected")
        self.assertEqual(self.charges(),(0,0,0,0))
        self.assertEqual(self.cash()["availablecash"],100)
        self.capital(104)
        first = self.order(price=100)
        competing = self.order(price=3)
        self.assertEqual(fill(self.uid,first.orderid,100),(None,None))
        self.assertEqual(get_order(self.uid,first.orderid).status,"rejected")
        self.assertEqual(self.charges(),(0,0,0,0))
        cancel_order(self.uid,competing.orderid)
        self.assertEqual(self.cash()["availablecash"],104)

    def test_immediate_order_failure_rolls_back_admission_and_fill_together(self):
        from backend.services.sandbox_service import place_order
        from backend.sandbox.order_manager import list_orders
        before = self.cash()
        with patch("backend.services.sandbox_service.get_ltp_with_fallback", return_value=100), patch(
            "backend.sandbox.brokerage.record_charge", side_effect=RuntimeError("injected ledger failure")
        ):
            with self.assertRaises(RuntimeError):
                place_order(self.uid, dict(symbol="NIFTY-DEMO-FUT", exchange="NFO", action="BUY",
                    quantity=25, pricetype="MARKET", product="NRML"))
        self.assertEqual(list_orders(self.uid, all_history=True), [])
        self.assertEqual(self.cash(), before)
        self.assertEqual(self.charges(), (0, 0, 0, 0))

    def test_credit_failure_rolls_back_the_entire_fill(self):
        from backend.sandbox.order_manager import fill, get_order
        from backend.models.sandbox import SandboxTrade, SandboxPosition
        from backend.sandbox._db import session_scope
        order=self.order(); before=self.cash()
        with patch("backend.sandbox.brokerage.record_charge",side_effect=RuntimeError("injected ledger failure")):
            with self.assertRaises(RuntimeError): fill(self.uid,order.orderid,1)
        self.assertEqual(get_order(self.uid,order.orderid).filled_quantity,0)
        self.assertEqual(self.cash(),before)
        self.assertEqual(self.charges(),(0,0,0,0))
        with session_scope() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SandboxTrade).where(SandboxTrade.user_id==self.uid)),0)
            self.assertEqual(db.scalar(select(func.count()).select_from(SandboxPosition).where(SandboxPosition.user_id==self.uid)),0)

    def test_earnings_survive_a_paper_book_reset_without_retroactive_changes(self):
        from backend.sandbox.order_manager import fill
        from backend.sandbox.weekly_reset import reset_user
        fill(self.uid,self.order().orderid,1)
        reset_user(self.uid)
        self.assertEqual(self.charges(),(1,4,3,1))
        self.assertEqual(self.cash()["brokerage_paid"],0)
        self.assertEqual(self.cash()["availablecash"],10000000)

    def test_concurrent_users_credit_the_same_broker_and_admin_without_lost_earnings(self):
        from backend.models.user import User
        from backend.models.sandbox import SandboxBrokerage
        from backend.sandbox._db import session_scope
        from backend.sandbox.order_manager import create_order, fill
        with session_scope() as db:
            suffix = secrets.token_hex(5)
            other = User(username="fee_second_"+suffix,email="second-"+suffix+"@example.com",password_hash="test",role="user",broker_id=self.broker)
            db.add(other); db.flush(); other_id=other.id
            self.child_ids.append(other_id)
        first=self.order()
        second=create_order(user_id=other_id,symbol="RELIANCE-DEMO",exchange="NSE",action="BUY",quantity=1,pricetype="LIMIT",product="MIS",price=1,reference_price=1)
        barrier=Barrier(2)
        def run(pair):
            barrier.wait(); return fill(pair[0],pair[1],1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run,[(self.uid,first.orderid),(other_id,second.orderid)]))
        self.assertTrue(all(trade is not None for _,trade in results))
        with session_scope() as db:
            totals=db.execute(select(func.sum(SandboxBrokerage.fee_paise),func.sum(SandboxBrokerage.broker_paise),func.sum(SandboxBrokerage.admin_paise)).where(SandboxBrokerage.broker_id==self.broker)).one()
            self.assertEqual(totals,(8,6,2))
            self.assertEqual(db.scalar(select(func.count()).select_from(SandboxBrokerage).where(SandboxBrokerage.broker_id==self.other)),0)

    def test_closing_a_losing_position_is_allowed_even_when_cash_becomes_negative(self):
        from backend.sandbox.order_manager import fill
        from backend.models.sandbox import SandboxPosition
        from backend.sandbox._db import session_scope
        self.capital(104)
        self.assertIsNotNone(fill(self.uid,self.order(qty=25,price=1,side="SELL",future=True).orderid,1)[1])
        close=self.order(qty=25,price=1000,side="BUY",future=True)
        self.assertEqual(close.status,"open")
        self.assertIsNotNone(fill(self.uid,close.orderid,1000)[1])
        self.assertEqual(self.cash()["utiliseddebits"],0)
        self.assertLess(self.cash()["availablecash"],0)
        with session_scope() as db:
            self.assertEqual(db.scalar(select(SandboxPosition.net_quantity).where(SandboxPosition.user_id==self.uid)),0)

    def test_delivery_admission_and_settlement_are_disabled_without_mutating_cash(self):
        from backend.sandbox.order_manager import create_order, fill
        from backend.sandbox.t1_settle import settle_cnc_to_holdings
        from backend.sandbox._db import session_scope
        from backend.models.sandbox import SandboxPosition, SandboxHolding
        before = self.cash()
        order = create_order(user_id=self.uid, symbol="RELIANCE-DEMO", exchange="NSE", action="BUY", quantity=10,
            pricetype="LIMIT", product="CNC", price=100, reference_price=100)
        self.assertEqual(order.status, "rejected")
        self.assertIn("CNC", order.rejection_reason)
        self.assertIsNone(fill(self.uid, order.orderid, 100)[1])
        self.assertEqual(settle_cnc_to_holdings(), 0)
        self.assertEqual(self.cash(), before)
        self.assertEqual(self.charges(), (0, 0, 0, 0))
        with session_scope() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(SandboxPosition).where(SandboxPosition.user_id == self.uid)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(SandboxHolding).where(SandboxHolding.user_id == self.uid)), 0)

    def test_unsupported_mis_cannot_open_or_reserve_margin(self):
        from backend.sandbox.order_manager import create_order
        for symbol, exchange, qty, price in [("USDINR-DEMO-FUT", "MSE", 1000, 85), ("GIFT-NIFTY-DEMO-FUT", "GIFT", 25, 25000), ("US500-DEMO", "GLOBAL", 1, 6000)]:
            with self.subTest(exchange=exchange):
                order = create_order(user_id=self.uid, symbol=symbol, exchange=exchange, action="BUY", quantity=qty,
                    pricetype="LIMIT", product="MIS", price=price, reference_price=price)
                self.assertEqual(order.status, "rejected")
                self.assertIn("MIS is unavailable", order.rejection_reason)
                self.assertEqual(order.margin_blocked, 0)

    def test_existing_delivery_position_can_only_reduce_and_stays_in_positions(self):
        from backend.sandbox.order_manager import create_order, fill
        from backend.sandbox._db import session_scope
        from backend.models.sandbox import SandboxPosition
        from backend.sandbox.t1_settle import settle_cnc_to_holdings
        from datetime import datetime, timezone, timedelta
        with session_scope() as db:
            db.add(SandboxPosition(user_id=self.uid, symbol="RELIANCE-DEMO", exchange="NSE", product="CNC",
                net_quantity=10, average_price=100, margin_blocked=0, updated_at=datetime.now(timezone.utc)-timedelta(days=2)))
        self.assertEqual(settle_cnc_to_holdings(), 0)
        close = create_order(user_id=self.uid, symbol="RELIANCE-DEMO", exchange="NSE", action="SELL", quantity=4,
            pricetype="LIMIT", product="CNC", price=100, reference_price=100)
        self.assertIsNotNone(fill(self.uid, close.orderid, 100)[1])
        self.assertEqual(self.charges(), (1,1600,1200,400))
        with session_scope() as db:
            self.assertEqual(db.scalar(select(SandboxPosition.net_quantity).where(SandboxPosition.user_id==self.uid)),6)
        excessive = create_order(user_id=self.uid, symbol="RELIANCE-DEMO", exchange="NSE", action="SELL", quantity=7,
            pricetype="LIMIT", product="CNC", price=100, reference_price=100)
        self.assertEqual(excessive.status,"rejected")

    def test_currency_order_and_trade_reporting_preserve_execution_precision(self):
        from backend.sandbox.order_manager import create_order, fill, get_order, to_dict, list_trades, trade_to_dict
        order = create_order(user_id=self.uid, symbol="USDINR-DEMO-FUT", exchange="MSE", action="BUY", quantity=1000,
            pricetype="LIMIT", product="NRML", price=85.0125, reference_price=85.0125)
        self.assertIsNotNone(fill(self.uid,order.orderid,85.0125)[1])
        payload = to_dict(get_order(self.uid,order.orderid))
        self.assertEqual(payload["price"],85.0125)
        self.assertEqual(payload["average_price"],85.0125)
        trade = trade_to_dict(list_trades(self.uid)[0])
        self.assertEqual(trade["average_price"],85.0125)
        self.assertEqual(trade["trade_value"],85012.5)
        self.assertAlmostEqual(trade["average_price"]*trade["quantity"],trade["trade_value"])

    def test_after_cutoff_reduction_cannot_reverse_the_position(self):
        from backend.sandbox.order_manager import fill
        from backend.services.sandbox_service import place_order
        self.assertIsNotNone(fill(self.uid,self.order(qty=10,price=100).orderid,100)[1])
        request=dict(symbol="RELIANCE-DEMO",exchange="NSE",action="SELL",quantity=11,pricetype="MARKET",product="MIS")
        with patch("backend.sandbox.order_validation.is_after_squareoff",return_value=True), patch("backend.services.sandbox_service.get_ltp_with_fallback",return_value=100):
            ok, response, status = place_order(self.uid,request)
            self.assertFalse(ok); self.assertEqual(status,400)
            ok, response, status = place_order(self.uid,{**request,"quantity":4})
            self.assertTrue(ok,response)
        self.assertEqual(self.charges(),(2,5600,4200,1400))

    def test_weighted_partial_closes_post_money_without_creating_rounding_cash(self):
        from backend.sandbox.order_manager import fill
        from backend.sandbox._db import session_scope
        from backend.models.sandbox import SandboxFund
        for _ in range(4):
            for qty,price,side in [(25,100,"BUY"),(50,100.05,"BUY"),(25,100.10,"SELL"),(25,100.10,"SELL"),(25,100.10,"SELL")]:
                self.assertIsNotNone(fill(self.uid,self.order(qty=qty,price=price,side=side,future=True).orderid,price)[1])
        with session_scope() as db:
            fund=db.scalar(select(SandboxFund).where(SandboxFund.user_id==self.uid))
            self.assertAlmostEqual(fund.available+fund.used_margin,fund.starting_capital+fund.realized_pnl,places=2)
            self.assertAlmostEqual(fund.realized_pnl+fund.brokerage_paise/100,20,places=2)
