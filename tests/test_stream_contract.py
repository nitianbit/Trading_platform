import unittest
from backend.services.market_data_cache import MarketDataCache


class QuoteContractTests(unittest.TestCase):
    def test_quote_cache_preserves_explicit_bid_ask_without_inventing_missing_values(self):
        cache = MarketDataCache(); cache._redis_enabled = False
        raw = dict(ltp=85.0125, bid=85.01, ask=85.015)
        self.assertTrue(cache.process_market_data(dict(symbol="USDINR-DEMO-FUT",exchange="MSE",mode=2,data=raw)))
        quote = cache.get_quote("USDINR-DEMO-FUT","MSE")
        self.assertEqual(quote["bid"],85.01); self.assertEqual(quote["ask"],85.015)
        cache.process_market_data(dict(symbol="NO-BID",exchange="NSE",mode=2,data={"ltp":1}))
        self.assertNotIn("bid",cache.get_quote("NO-BID","NSE"))
