import unittest

from fenjue.timing import (
    StockBehaviorProfile,
    classify_auction_gap,
    evaluate_entry_window,
    profile_stock_behavior,
)


class TimingTests(unittest.TestCase):
    def test_auction_gap_bands_are_hypotheses_not_buy_signals(self):
        self.assertEqual(classify_auction_gap(2.0), "CONSTRUCTIVE_GAP")
        self.assertEqual(classify_auction_gap(5.0), "FADE_RISK_GAP")
        self.assertEqual(classify_auction_gap(9.0), "HIGH_OPEN_CONFIRMATION_REQUIRED")

    def test_stock_behavior_requires_enough_stock_specific_samples(self):
        profile = profile_stock_behavior(
            [{"faded": True, "v_recovered": False}] * 8,
            minimum_samples=20,
        )
        self.assertEqual(profile.status, "UNVERIFIED")

    def test_fade_prone_stock_is_rejected_at_0940_after_mid_gap(self):
        profile = StockBehaviorProfile("FADE", 0.7, 0.1, 30, "VERIFIED")
        result = evaluate_entry_window(
            "09:40", profile, auction_gap_pct_points=5.0,
            stabilized=False, wash_and_reclaim=False, market_regime="NEUTRAL",
        )
        self.assertFalse(result.eligible)
        self.assertIn("STOCK_SPECIFIC_FADE_RISK", result.reason_codes)

    def test_1030_requires_observed_stabilization(self):
        profile = StockBehaviorProfile("V_RECOVERY", 0.1, 0.7, 30, "VERIFIED")
        result = evaluate_entry_window(
            "10:30", profile, auction_gap_pct_points=2.0,
            stabilized=False, wash_and_reclaim=False, market_regime="NEUTRAL",
        )
        self.assertFalse(result.eligible)
        self.assertIn("TEN_THIRTY_NOT_STABILIZED", result.reason_codes)

    def test_1430_rejects_new_risk_in_retreat(self):
        profile = StockBehaviorProfile("MIXED", 0.3, 0.3, 30, "VERIFIED")
        result = evaluate_entry_window(
            "14:30", profile, auction_gap_pct_points=2.0,
            stabilized=True, wash_and_reclaim=False, market_regime="RETREAT",
        )
        self.assertFalse(result.eligible)
        self.assertIn("MARKET_RETREAT", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
