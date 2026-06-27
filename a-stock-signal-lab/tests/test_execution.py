import unittest

from fenjue.execution import (
    CostModel,
    MarketState,
    assess_fill,
    first_barrier_outcome,
    resolve_1030_price,
    score_new_entry,
)


class ExecutionModelTests(unittest.TestCase):
    def setUp(self):
        self.cost = CostModel(
            commission_bps=3,
            min_commission_fen=500,
            sell_stamp_duty_bps=5,
            transfer_fee_bps=1,
            default_slippage_bps=2,
        )

    def test_limit_up_buy_without_queue_evidence_is_unknown(self):
        result = assess_fill(
            side="buy",
            market=MarketState(
                quality="C", suspended=False, price_limit_state="limit_up",
                ask_liquidity_qty=0, bid_liquidity_qty=10000,
                conservative_price_x10000=100000,
            ),
        )
        self.assertEqual(result.fill_status, "unknown")
        self.assertEqual(result.reason_code, "LIMIT_UP_BUY_QUEUE_UNKNOWN")

    def test_limit_down_sell_without_bid_is_unknown(self):
        result = assess_fill(
            side="sell",
            market=MarketState(
                quality="B", suspended=False, price_limit_state="limit_down",
                ask_liquidity_qty=10000, bid_liquidity_qty=0,
                conservative_price_x10000=90000,
            ),
        )
        self.assertEqual(result.fill_status, "unknown")
        self.assertEqual(result.reason_code, "LIMIT_DOWN_SELL_QUEUE_UNKNOWN")

    def test_same_bar_take_profit_and_stop_loss_is_ambiguous(self):
        bars = [
            {"time_ms": 1, "high_price_x10000": 103000, "low_price_x10000": 97000}
        ]
        outcome = first_barrier_outcome(
            bars, take_profit_price_x10000=103000,
            stop_price_x10000=97000, data_quality="C",
        )
        self.assertEqual(outcome.status, "ambiguous")

    def test_missing_1030_trade_beyond_five_minutes_is_unscorable(self):
        bars = [{"time_ms": 10_000, "close_price_x10000": 103000}]
        self.assertIsNone(resolve_1030_price(bars, target_ms=400_001))

    def test_costs_reverse_a_gross_three_percent_hit(self):
        result = score_new_entry(
            entry_price_x10000=100000,
            exit_price_x10000=103050,
            quantity_qty=1000,
            cost_model=self.cost,
        )
        self.assertGreater(result.gross_return_pct_points, 3.0)
        self.assertLess(result.net_return_pct_points, 3.0)
        self.assertFalse(result.hit_net_3pct)

    def test_normal_market_uses_conservative_price(self):
        result = assess_fill(
            side="buy",
            market=MarketState(
                quality="C", suspended=False, price_limit_state="normal",
                ask_liquidity_qty=1000, bid_liquidity_qty=1000,
                conservative_price_x10000=100100,
            ),
        )
        self.assertEqual(result.fill_status, "fillable")
        self.assertEqual(result.conservative_fill_price_x10000, 100100)


if __name__ == "__main__":
    unittest.main()
