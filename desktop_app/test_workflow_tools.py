import unittest

from desktop_app.main import MarketSignalApp


class WorkflowToolsTests(unittest.TestCase):
    def test_rank_watchlist_symbols_prioritizes_movers(self):
        metrics = {
            "BTCUSDT": {"change": 6.2, "quote_volume": 240_000_000, "price": 58500},
            "ETHUSDT": {"change": 1.1, "quote_volume": 120_000_000, "price": 2800},
            "SOLUSDT": {"change": 8.8, "quote_volume": 400_000_000, "price": 155},
        }

        ranked = MarketSignalApp.rank_watchlist_symbols(["BTCUSDT", "ETHUSDT", "SOLUSDT"], metrics)

        self.assertEqual(ranked[0][0], "SOLUSDT")
        self.assertEqual(ranked[1][0], "BTCUSDT")
        self.assertEqual(ranked[2][0], "ETHUSDT")

    def test_rank_watchlist_symbols_handles_missing_metrics(self):
        metrics = {"BTCUSDT": {"change": 4.5, "quote_volume": 90_000_000, "price": 44000}}

        ranked = MarketSignalApp.rank_watchlist_symbols(["BTCUSDT", "ETHUSDT"], metrics)

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0][0], "BTCUSDT")

    def test_update_available_logic(self):
        self.assertTrue(MarketSignalApp.is_update_available("v1.0.15", "v1.0.16"))
        self.assertFalse(MarketSignalApp.is_update_available("v1.0.15", "v1.0.15"))
        self.assertFalse(MarketSignalApp.is_update_available("v1.0.15", "v1.0.14"))


if __name__ == "__main__":
    unittest.main()
