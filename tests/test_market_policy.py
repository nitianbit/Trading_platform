"""Policy and public-feed boundary regressions, without external network calls."""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from backend.paper.catalog import INSTRUMENTS, instrument_key
from backend.paper.policy import PlatformPolicy, PolicyUpdate
from backend.paper.public_prices import parse_quote, snapshot


class MarketPolicyTests(unittest.TestCase):
    def test_policy_rejects_invalid_limits_and_unknown_identities(self):
        for changes in ({"max_customers": -1}, {"max_customers": True}, {"max_customers": 1.5},
                        {"disabled_groups": ["not-an-exchange"]}, {"disabled_instruments": ["unknown"]},
                        {"disabled_reference_assets": ["CRUDE"]}, {"public_feed_enabled": "yes"}, {"unknown": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                PlatformPolicy(**changes)
        self.assertIsNone(PlatformPolicy().max_customers)
        self.assertEqual(PlatformPolicy(max_customers=0).max_customers, 0)

    def test_http_policy_requires_every_field_and_a_nonnegative_revision(self):
        full = {**PlatformPolicy().model_dump(), "revision": 0}
        self.assertEqual(PolicyUpdate(**full).revision, 0)
        for key in full:
            with self.subTest(missing=key), self.assertRaises(ValidationError):
                PolicyUpdate(**{k:v for k,v in full.items() if k != key})
        for revision in (-1, True, "0"):
            with self.assertRaises(ValidationError):
                PolicyUpdate(**{**full, "revision": revision})

    def test_group_and_instrument_switches_are_independent(self):
        gold = next(row for row in INSTRUMENTS if row["symbol"] == "GOLD-DEMO-FUT")
        silver = next(row for row in INSTRUMENTS if row["symbol"] == "SILVER-DEMO-FUT")
        policy = PlatformPolicy(disabled_instruments=[instrument_key(gold)])
        self.assertFalse(policy.instrument_enabled(gold))
        self.assertTrue(policy.instrument_enabled(silver))
        policy.disabled_groups = ["MCX"]
        self.assertFalse(policy.instrument_enabled(silver))

    def test_public_quote_requires_identity_currency_finite_price_and_utc_time(self):
        now = datetime.now(timezone.utc).timestamp()
        payload = {"symbol": "XAU", "currency": "USD", "price": 4000, "updatedAt": datetime.fromtimestamp(now, timezone.utc).isoformat()}
        self.assertEqual(parse_quote(payload, "XAU", now)["price"], 4000)
        for changes in ({"symbol": "XAG"}, {"currency": "INR"}, {"price": True}, {"price": -1},
                        {"price": float("nan")}, {"price": float("inf")}, {"updatedAt": None},
                        {"updatedAt": "2026-11-05T10:00:00"}, {"updatedAt": "2099-01-01T00:00:00Z"}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                parse_quote({**payload, **changes}, "XAU", now)

    def test_stale_failed_disabled_and_hidden_public_quotes_never_look_live(self):
        quote = dict(price=4000, timestamp=1000, received_at=1000, updated_at="1970-01-01T00:16:40+00:00", error=False)
        with patch("backend.paper.public_prices._quotes", {"XAU": quote}):
            def gold(policy=PlatformPolicy(), now=1001):
                return next(row for row in snapshot(policy, now=now)["assets"] if row["symbol"] == "XAU")
            self.assertEqual(gold()["status"], "live")
            self.assertIsNone(gold(now=1091)["price"])
            self.assertEqual(gold(now=1091)["status"], "stale")
            quote["error"] = True
            self.assertEqual(gold()["status"], "unavailable")
            self.assertIsNone(gold()["price"])
            self.assertEqual(gold(PlatformPolicy(public_feed_enabled=False))["status"], "disabled")
            self.assertNotIn("XAU", [row["symbol"] for row in snapshot(PlatformPolicy(disabled_reference_assets=["XAU"]), now=1001)["assets"]])
