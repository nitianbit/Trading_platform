"""Regression tests for the execution boundary; no broker or database calls."""
import importlib
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from contextlib import contextmanager
from backend.services import trading_mode_service as mode
from backend.services.order_service import place_order_with_auth

ORDER = dict(symbol="NIFTY-DEMO-25000CE", exchange="NFO", action="BUY",
             quantity=25, pricetype="MARKET", product="NRML")


class PaperOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_execution_mode_never_reads_database_or_cache(self):
        self.assertEqual(mode.get_trading_mode_sync(), "sandbox")
        self.assertEqual(await mode.get_trading_mode(object()), "sandbox")

    async def test_live_mode_cannot_be_enabled(self):
        with self.assertRaises(ValueError):
            await mode.set_trading_mode(None, "live")

    async def test_missing_paper_handler_never_calls_live_handler(self):
        async def live():
            self.fail("Live handler must never run")
        with self.assertRaises(RuntimeError):
            await mode.dispatch_by_mode(live, None)

    def test_all_real_broker_order_modules_are_disabled(self):
        for name in ("upstox", "zerodha", "angel", "dhan", "fyers"):
            with self.subTest(broker=name), self.assertRaisesRegex(RuntimeError, "cannot submit orders"):
                importlib.import_module(f"backend.broker.{name}.api.order_api")

    def test_fill_recomputes_stale_unrealized_pnl_on_reduce_close_and_reverse(self):
        from backend.sandbox.position_manager import apply_fill

        @contextmanager
        def transaction():
            yield object()

        for sold, expected_quantity, expected_unrealized in [(15, 10, 50), (25, 0, 0), (50, -25, 0)]:
            position = SimpleNamespace(net_quantity=25, average_price=100.0, margin_blocked=2500.0,
                realized_pnl=0.0, today_realized_pnl=0.0, unrealized_pnl=42.0, pnl=42.0,
                day_buy_quantity=25, day_buy_value=2500.0, day_sell_quantity=0, day_sell_value=0.0)
            with self.subTest(sold=sold), patch("backend.sandbox.position_manager.session_scope", transaction), patch(
                "backend.sandbox.position_manager._get_or_create", return_value=position
            ):
                apply_fill(1, "NIFTY-DEMO-FUT", "NFO", "NRML", "SELL", sold, 105.0)
                self.assertEqual(position.net_quantity, expected_quantity)
                self.assertEqual(position.unrealized_pnl, expected_unrealized)
                self.assertEqual(position.pnl, position.realized_pnl + expected_unrealized)

    def test_order_requires_platform_account_even_with_broker_credentials(self):
        ok, response, status = place_order_with_auth(ORDER.copy(), "token", "zerodha")
        self.assertFalse(ok)
        self.assertEqual(status, 401)

    def test_paper_failure_propagates_without_broker_fallback(self):
        with patch("backend.services.sandbox_service.place_order", side_effect=RuntimeError("database unavailable")):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                place_order_with_auth(ORDER.copy(), "token", "zerodha", user_id=1)


if __name__ == "__main__":
    unittest.main()

