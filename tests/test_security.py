"""Security invariants without network or owner-account access."""
import unittest
from unittest.mock import patch, Mock
from datetime import timedelta
from backend.security import create_access_token, decode_access_token, hash_api_key


class SecurityTests(unittest.TestCase):
    def test_jwt_signature_and_expiry_are_required(self):
        token = create_access_token({"sub": "42", "jti": "test"})
        self.assertEqual(decode_access_token(token)["sub"], "42")
        head, payload, signature = token.split(".")
        self.assertIsNone(decode_access_token(head + "." + payload + "." + ("A" if signature[0] != "A" else "B") + signature[1:]))
        self.assertIsNone(decode_access_token(create_access_token({"sub": "42"}, timedelta(seconds=-1))))
        self.assertEqual(hash_api_key("test-key"), hash_api_key("test-key"))
        self.assertNotEqual(hash_api_key("test-key"), hash_api_key("other-key"))

    def test_stale_feed_cannot_price_an_order(self):
        from backend.sandbox.quote_helper import get_ltp
        cache = Mock()
        cache.is_data_fresh.return_value = False
        cache.get_ltp_value.return_value = 25000.0
        with patch("backend.sandbox.quote_helper.get_market_data_cache", return_value=cache):
            self.assertIsNone(get_ltp(1, "NIFTY-DEMO-FUT", "NFO"))
            cache.get_ltp_value.assert_not_called()

    def test_insecure_production_configuration_is_rejected(self):
        from backend.config import Settings
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            Settings(production=True, cookie_secure=False)

    def test_missing_reset_configuration_never_wipes_accounts(self):
        from datetime import datetime
        from backend.sandbox import scheduler
        sunday = datetime(2026, 11, 8, 12, tzinfo=scheduler.IST)
        with patch.object(scheduler, "_ist_now", return_value=sunday), patch.object(scheduler, "_read_cfg", side_effect=lambda key, default: default), patch.object(scheduler, "_read_last_run", return_value="2026-11-08"), patch.object(scheduler.weekly_reset, "wipe_all_users") as wipe:
            scheduler._tick()
            wipe.assert_not_called()
