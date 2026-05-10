#!/usr/bin/env python3
"""
Tests for Earnings Trade Analyzer modules.

Covers normal cases and failure cases for all 5 calculators,
scorer, report generator, and FMP client edge cases.
"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch  # noqa: F401 (patch used in TestYahooFinanceClient)

from analyze_earnings_trades import apply_entry_filter
from calculators.gap_size_calculator import calculate_gap
from calculators.ma50_calculator import calculate_ma50_position
from calculators.ma200_calculator import calculate_ma200_position
from calculators.pre_earnings_trend_calculator import calculate_pre_earnings_trend
from calculators.volume_trend_calculator import calculate_volume_trend
from report_generator import generate_json_report, generate_markdown_report
from scorer import COMPONENT_WEIGHTS, calculate_composite_score
from yahoo_finance_client import YahooFinanceClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_prices(n, start=100.0, daily_change=0.0, volume=1000000, start_date="2025-01-01"):
    """Generate synthetic price data (most-recent-first).

    Args:
        n: Number of bars
        start: Starting close price (for most recent bar)
        daily_change: Per-bar drift factor
        volume: Volume for all bars
        start_date: Date string for the most recent bar

    Returns:
        List of price dicts, most-recent-first.
    """
    prices = []
    p = start
    for i in range(n):
        p_day = p * (1 + daily_change * i)
        prices.append(
            {
                "date": f"2025-{(i // 22) + 1:02d}-{(i % 22) + 1:02d}",
                "open": round(p_day * 0.999, 2),
                "high": round(p_day * 1.01, 2),
                "low": round(p_day * 0.99, 2),
                "close": round(p_day, 2),
                "volume": volume,
            }
        )
    return prices


def _make_earnings_prices(
    earnings_date="2025-01-05",
    pre_close=100.0,
    earnings_open=106.0,
    earnings_close=107.0,
    post_open=108.0,
    num_days=250,
    volume=1000000,
):
    """Generate price data with a specific earnings date and gap.

    Places the earnings date at a known position with controlled prices
    around it. Returns most-recent-first data.
    """
    prices = []

    # Build chronological then reverse
    # Place earnings at day 30 (arbitrary, gives us 20+ days before for trend)
    earnings_day_idx = 30

    for i in range(num_days):
        if i < earnings_day_idx - 1:
            # Days before the day before earnings
            base = pre_close * (1 - 0.001 * (earnings_day_idx - 1 - i))
            prices.append(
                {
                    "date": f"2025-{(i // 22) + 1:02d}-{(i % 22) + 1:02d}",
                    "open": round(base * 0.999, 2),
                    "high": round(base * 1.01, 2),
                    "low": round(base * 0.99, 2),
                    "close": round(base, 2),
                    "volume": volume,
                }
            )
        elif i == earnings_day_idx - 1:
            # Day before earnings
            prices.append(
                {
                    "date": f"2025-{(i // 22) + 1:02d}-{(i % 22) + 1:02d}",
                    "open": round(pre_close * 0.999, 2),
                    "high": round(pre_close * 1.01, 2),
                    "low": round(pre_close * 0.99, 2),
                    "close": round(pre_close, 2),
                    "volume": volume,
                }
            )
        elif i == earnings_day_idx:
            # Earnings day
            prices.append(
                {
                    "date": earnings_date,
                    "open": round(earnings_open, 2),
                    "high": round(max(earnings_open, earnings_close) * 1.01, 2),
                    "low": round(min(earnings_open, earnings_close) * 0.99, 2),
                    "close": round(earnings_close, 2),
                    "volume": volume * 3,  # High volume on earnings day
                }
            )
        elif i == earnings_day_idx + 1:
            # Day after earnings
            prices.append(
                {
                    "date": f"2025-{(i // 22) + 1:02d}-{(i % 22) + 1:02d}",
                    "open": round(post_open, 2),
                    "high": round(post_open * 1.01, 2),
                    "low": round(post_open * 0.99, 2),
                    "close": round(post_open * 1.005, 2),
                    "volume": volume * 2,
                }
            )
        else:
            # Days after earnings
            base = post_open * (1 + 0.001 * (i - earnings_day_idx - 1))
            prices.append(
                {
                    "date": f"2025-{(i // 22) + 1:02d}-{(i % 22) + 1:02d}",
                    "open": round(base * 0.999, 2),
                    "high": round(base * 1.01, 2),
                    "low": round(base * 0.99, 2),
                    "close": round(base, 2),
                    "volume": volume,
                }
            )

    # Reverse to most-recent-first
    prices.reverse()
    return prices


# ===========================================================================
# Gap Size Calculator Tests
# ===========================================================================


class TestGapSizeCalculator:
    """Test gap calculation for BMO, AMC, and unknown timings."""

    def _make_simple_prices(self):
        """Build simple 5-bar price data with earnings on bar index 2 (most-recent-first)."""
        return [
            {"date": "2025-01-07", "open": 108.0, "close": 109.0, "volume": 1000000},
            {"date": "2025-01-06", "open": 107.0, "close": 108.0, "volume": 1000000},
            {"date": "2025-01-05", "open": 106.0, "close": 107.0, "volume": 3000000},
            {"date": "2025-01-04", "open": 100.0, "close": 100.0, "volume": 1000000},
            {"date": "2025-01-03", "open": 99.0, "close": 99.5, "volume": 1000000},
        ]

    def test_bmo_gap_positive(self):
        """BMO: gap = open[earnings_date] / close[prev_day] - 1"""
        prices = self._make_simple_prices()
        # Earnings on 2025-01-05 (idx 2), prev_day is 2025-01-04 (idx 3)
        # BMO gap = open[2025-01-05] / close[2025-01-04] - 1 = 106/100 - 1 = 6%
        result = calculate_gap(prices, "2025-01-05", "bmo")
        assert result["gap_pct"] == 6.0
        assert result["gap_type"] == "up"
        assert result["base_price"] == 100.0
        assert result["gap_price"] == 106.0
        assert result["timing_used"] == "bmo"
        assert result["score"] == 70.0  # >= 5%

    def test_amc_gap_positive(self):
        """AMC: gap = open[next_day] / close[earnings_date] - 1"""
        prices = self._make_simple_prices()
        # Earnings on 2025-01-05 (idx 2), next_day is 2025-01-06 (idx 1)
        # AMC gap = open[2025-01-06] / close[2025-01-05] - 1 = 107/107 - 1 = 0%
        result = calculate_gap(prices, "2025-01-05", "amc")
        assert abs(result["gap_pct"]) < 1.0
        assert result["timing_used"] == "amc"

    def test_unknown_gap_uses_amc_logic(self):
        """Unknown timing uses AMC logic."""
        prices = self._make_simple_prices()
        result_amc = calculate_gap(prices, "2025-01-05", "amc")
        result_unknown = calculate_gap(prices, "2025-01-05", "unknown")
        assert result_amc["gap_pct"] == result_unknown["gap_pct"]

    def test_negative_gap(self):
        """Test negative (gap down) calculation."""
        prices = [
            {"date": "2025-01-06", "open": 93.0, "close": 92.0, "volume": 2000000},
            {"date": "2025-01-05", "open": 95.0, "close": 94.0, "volume": 3000000},
            {"date": "2025-01-04", "open": 100.0, "close": 100.0, "volume": 1000000},
        ]
        # BMO gap = 95/100 - 1 = -5%
        result = calculate_gap(prices, "2025-01-05", "bmo")
        assert result["gap_pct"] == -5.0
        assert result["gap_type"] == "down"
        assert result["score"] == 70.0  # |gap| >= 5%

    def test_score_threshold_10pct(self):
        """Gap >= 10% scores 100."""
        prices = [
            {"date": "2025-01-06", "open": 115.0, "close": 116.0, "volume": 1000000},
            {"date": "2025-01-05", "open": 112.0, "close": 113.0, "volume": 3000000},
            {"date": "2025-01-04", "open": 100.0, "close": 100.0, "volume": 1000000},
        ]
        result = calculate_gap(prices, "2025-01-05", "bmo")
        assert result["gap_pct"] == 12.0
        assert result["score"] == 100.0

    def test_score_threshold_7pct(self):
        """Gap >= 7% scores 85."""
        prices = [
            {"date": "2025-01-05", "open": 107.0, "close": 108.0, "volume": 3000000},
            {"date": "2025-01-04", "open": 100.0, "close": 100.0, "volume": 1000000},
        ]
        result = calculate_gap(prices, "2025-01-05", "bmo")
        assert result["gap_pct"] == 7.0
        assert result["score"] == 85.0

    def test_score_threshold_3pct(self):
        """Gap >= 3% scores 55."""
        prices = [
            {"date": "2025-01-05", "open": 103.0, "close": 104.0, "volume": 3000000},
            {"date": "2025-01-04", "open": 100.0, "close": 100.0, "volume": 1000000},
        ]
        result = calculate_gap(prices, "2025-01-05", "bmo")
        assert result["gap_pct"] == 3.0
        assert result["score"] == 55.0

    def test_score_threshold_1pct(self):
        """Gap >= 1% scores 35."""
        prices = [
            {"date": "2025-01-05", "open": 101.0, "close": 102.0, "volume": 3000000},
            {"date": "2025-01-04", "open": 100.0, "close": 100.0, "volume": 1000000},
        ]
        result = calculate_gap(prices, "2025-01-05", "bmo")
        assert result["gap_pct"] == 1.0
        assert result["score"] == 35.0

    def test_score_threshold_below_1pct(self):
        """Gap < 1% scores 15."""
        prices = [
            {"date": "2025-01-05", "open": 100.5, "close": 101.0, "volume": 3000000},
            {"date": "2025-01-04", "open": 100.0, "close": 100.0, "volume": 1000000},
        ]
        result = calculate_gap(prices, "2025-01-05", "bmo")
        assert result["gap_pct"] == 0.5
        assert result["score"] == 15.0

    def test_earnings_date_not_found(self):
        """Missing earnings date returns score 0 with warning."""
        prices = _make_prices(10)
        result = calculate_gap(prices, "2099-12-31", "bmo")
        assert result["score"] == 0.0
        assert "warning" in result


# ===========================================================================
# Pre-Earnings Trend Calculator Tests
# ===========================================================================


class TestPreEarningsTrend:
    """Test 20-day pre-earnings return calculation."""

    def test_positive_trend(self):
        """Stock up 10% over 20 days before earnings."""
        # Build prices where earnings date close = 110, 20 days prior close = 100
        prices = []
        for i in range(50):
            if i == 5:
                prices.append({"date": "2025-01-10", "close": 110.0, "volume": 1000000})
            elif i == 25:
                prices.append({"date": "2025-01-01", "close": 100.0, "volume": 1000000})
            else:
                prices.append(
                    {
                        "date": f"2025-{(i // 22) + 1:02d}-{(i % 22) + 1:02d}",
                        "close": 105.0,
                        "volume": 1000000,
                    }
                )
        result = calculate_pre_earnings_trend(prices, "2025-01-10")
        assert result["return_20d_pct"] == 10.0
        assert result["trend_direction"] == "up"
        assert result["score"] == 85.0  # >= 10%

    def test_negative_trend(self):
        """Stock down 8% over 20 days before earnings."""
        prices = []
        for i in range(50):
            if i == 5:
                prices.append({"date": "2025-01-10", "close": 92.0, "volume": 1000000})
            elif i == 25:
                prices.append({"date": "2025-01-01", "close": 100.0, "volume": 1000000})
            else:
                prices.append(
                    {
                        "date": f"2025-{(i // 22) + 1:02d}-{(i % 22) + 1:02d}",
                        "close": 96.0,
                        "volume": 1000000,
                    }
                )
        result = calculate_pre_earnings_trend(prices, "2025-01-10")
        assert result["return_20d_pct"] == -8.0
        assert result["trend_direction"] == "down"
        assert result["score"] == 15.0  # < -5%

    def test_score_threshold_15pct(self):
        """Return >= 15% scores 100."""
        prices = []
        for i in range(50):
            if i == 5:
                prices.append({"date": "2025-01-10", "close": 115.5, "volume": 1000000})
            elif i == 25:
                prices.append({"date": "2025-01-01", "close": 100.0, "volume": 1000000})
            else:
                prices.append(
                    {
                        "date": f"2025-{(i // 22) + 1:02d}-{(i % 22) + 1:02d}",
                        "close": 107.0,
                        "volume": 1000000,
                    }
                )
        result = calculate_pre_earnings_trend(prices, "2025-01-10")
        assert result["score"] == 100.0

    def test_score_threshold_0pct(self):
        """Return >= 0% but < 5% scores 50."""
        prices = []
        for i in range(50):
            if i == 5:
                prices.append({"date": "2025-01-10", "close": 102.0, "volume": 1000000})
            elif i == 25:
                prices.append({"date": "2025-01-01", "close": 100.0, "volume": 1000000})
            else:
                prices.append(
                    {
                        "date": f"2025-{(i // 22) + 1:02d}-{(i % 22) + 1:02d}",
                        "close": 101.0,
                        "volume": 1000000,
                    }
                )
        result = calculate_pre_earnings_trend(prices, "2025-01-10")
        assert result["score"] == 50.0

    def test_score_threshold_neg5pct(self):
        """Return >= -5% but < 0% scores 30."""
        prices = []
        for i in range(50):
            if i == 5:
                prices.append({"date": "2025-01-10", "close": 97.0, "volume": 1000000})
            elif i == 25:
                prices.append({"date": "2025-01-01", "close": 100.0, "volume": 1000000})
            else:
                prices.append(
                    {
                        "date": f"2025-{(i // 22) + 1:02d}-{(i % 22) + 1:02d}",
                        "close": 98.0,
                        "volume": 1000000,
                    }
                )
        result = calculate_pre_earnings_trend(prices, "2025-01-10")
        assert result["score"] == 30.0

    def test_insufficient_data(self):
        """Less than 20 days before earnings returns warning."""
        prices = [{"date": "2025-01-10", "close": 100.0, "volume": 1000000}]
        for i in range(10):
            prices.append(
                {
                    "date": f"2025-01-{9 - i:02d}",
                    "close": 100.0,
                    "volume": 1000000,
                }
            )
        result = calculate_pre_earnings_trend(prices, "2025-01-10")
        assert result["score"] == 0.0
        assert "warning" in result


# ===========================================================================
# Volume Trend Calculator Tests
# ===========================================================================


class TestVolumeTrend:
    """Test volume ratio calculation."""

    def test_high_ratio(self):
        """20-day avg much higher than 60-day avg -> high score."""
        prices = []
        for i in range(80):
            vol = 2000000 if i < 20 else 500000
            prices.append(
                {
                    "date": f"2025-{(i // 22) + 1:02d}-{(i % 22) + 1:02d}",
                    "close": 100.0,
                    "volume": vol,
                }
            )
        # Place earnings at day 0
        prices[0]["date"] = "2025-01-01"
        result = calculate_volume_trend(prices, "2025-01-01")
        assert result["vol_ratio_20_60"] > 1.5
        assert result["score"] >= 80.0

    def test_low_ratio(self):
        """20-day avg lower than 60-day avg -> low score."""
        prices = []
        for i in range(80):
            vol = 300000 if i < 20 else 1000000
            prices.append(
                {
                    "date": f"2025-{(i // 22) + 1:02d}-{(i % 22) + 1:02d}",
                    "close": 100.0,
                    "volume": vol,
                }
            )
        prices[0]["date"] = "2025-01-01"
        result = calculate_volume_trend(prices, "2025-01-01")
        assert result["vol_ratio_20_60"] < 1.0
        assert result["score"] == 20.0

    def test_score_threshold_2x(self):
        """Ratio >= 2.0 scores 100."""
        prices = []
        for i in range(80):
            vol = 3000000 if i < 20 else 500000
            prices.append(
                {
                    "date": f"2025-{(i // 22) + 1:02d}-{(i % 22) + 1:02d}",
                    "close": 100.0,
                    "volume": vol,
                }
            )
        prices[0]["date"] = "2025-01-01"
        result = calculate_volume_trend(prices, "2025-01-01")
        assert result["vol_ratio_20_60"] >= 2.0
        assert result["score"] == 100.0

    def test_earnings_date_not_found(self):
        """Missing date returns score 0."""
        prices = _make_prices(80)
        result = calculate_volume_trend(prices, "2099-12-31")
        assert result["score"] == 0.0
        assert "warning" in result


# ===========================================================================
# MA200 Calculator Tests
# ===========================================================================


class TestMA200Calculator:
    """Test MA200 position calculation."""

    def test_above_ma200(self):
        """Price well above MA200 -> high score."""
        # All closes at 100, then current close at 120 (20% above)
        prices = [{"close": 120.0}]
        for _ in range(249):
            prices.append({"close": 100.0})
        result = calculate_ma200_position(prices)
        assert result["above_ma200"] is True
        assert result["distance_pct"] > 0
        assert result["score"] >= 55.0

    def test_below_ma200(self):
        """Price below MA200 -> lower score."""
        prices = [{"close": 90.0}]
        for _ in range(249):
            prices.append({"close": 100.0})
        result = calculate_ma200_position(prices)
        assert result["above_ma200"] is False
        assert result["distance_pct"] < 0

    def test_insufficient_data(self):
        """Less than 200 days returns warning and score 0."""
        prices = _make_prices(100)
        result = calculate_ma200_position(prices)
        assert result["score"] == 0.0
        assert "warning" in result

    def test_score_20pct_above(self):
        """20% above MA200 scores 100."""
        # MA200 = avg of 200 closes. If 199 at 100 + 1 at 120, MA ~ 100.1
        # For exact 20% above: need current close = MA200 * 1.2
        prices = [{"close": 120.0}]
        for _ in range(199):
            prices.append({"close": 100.0})
        result = calculate_ma200_position(prices)
        # MA200 = (120 + 199*100) / 200 = 20020/200 = 100.1
        # distance = (120/100.1 - 1)*100 = 19.88%
        assert result["score"] == 85.0  # >= 10%

    def test_score_just_above(self):
        """Just above MA200 (0-5%) scores 55."""
        prices = [{"close": 101.0}]
        for _ in range(199):
            prices.append({"close": 100.0})
        result = calculate_ma200_position(prices)
        # MA200 ~ 100.005, distance ~ 0.99%
        assert result["score"] == 55.0

    def test_score_below_neg5(self):
        """More than 5% below MA200 scores 15."""
        prices = [{"close": 90.0}]
        for _ in range(199):
            prices.append({"close": 100.0})
        result = calculate_ma200_position(prices)
        # MA200 ~ 99.95, distance ~ -9.95%
        assert result["score"] == 15.0


# ===========================================================================
# MA50 Calculator Tests
# ===========================================================================


class TestMA50Calculator:
    """Test MA50 position calculation."""

    def test_above_ma50(self):
        """Price above MA50 -> positive distance."""
        prices = [{"close": 110.0}]
        for _ in range(59):
            prices.append({"close": 100.0})
        result = calculate_ma50_position(prices)
        assert result["above_ma50"] is True
        assert result["distance_pct"] > 0

    def test_below_ma50(self):
        """Price below MA50 -> negative distance."""
        prices = [{"close": 90.0}]
        for _ in range(59):
            prices.append({"close": 100.0})
        result = calculate_ma50_position(prices)
        assert result["above_ma50"] is False
        assert result["distance_pct"] < 0

    def test_insufficient_data(self):
        """Less than 50 days returns warning and score 0."""
        prices = _make_prices(30)
        result = calculate_ma50_position(prices)
        assert result["score"] == 0.0
        assert "warning" in result

    def test_score_10pct_above(self):
        """10% above MA50 scores 100."""
        prices = [{"close": 111.0}]
        for _ in range(49):
            prices.append({"close": 100.0})
        result = calculate_ma50_position(prices)
        # MA50 = (111 + 49*100)/50 = 100.22, distance ~ 10.78%
        assert result["score"] == 100.0

    def test_score_5pct_above(self):
        """5% above MA50 scores 80."""
        prices = [{"close": 105.5}]
        for _ in range(49):
            prices.append({"close": 100.0})
        result = calculate_ma50_position(prices)
        # MA50 = (105.5 + 49*100)/50 = 100.11, distance ~ 5.39%
        assert result["score"] == 80.0

    def test_score_just_above(self):
        """Just above MA50 (0-5%) scores 60."""
        prices = [{"close": 101.0}]
        for _ in range(49):
            prices.append({"close": 100.0})
        result = calculate_ma50_position(prices)
        # MA50 ~ 100.02, distance ~ 0.98%
        assert result["score"] == 60.0

    def test_score_below_neg5(self):
        """More than 5% below MA50 scores 15."""
        prices = [{"close": 92.0}]
        for _ in range(49):
            prices.append({"close": 100.0})
        result = calculate_ma50_position(prices)
        # MA50 ~ 99.84, distance ~ -7.84%
        assert result["score"] == 15.0


# ===========================================================================
# Scorer Tests
# ===========================================================================


class TestScorer:
    """Test composite scoring and grade assignment."""

    def test_all_high_scores_grade_a(self):
        """All scores at 100 -> Grade A."""
        result = calculate_composite_score(100, 100, 100, 100, 100)
        assert result["composite_score"] == 100.0
        assert result["grade"] == "A"
        assert "Strong" in result["grade_description"]

    def test_all_low_scores_grade_d(self):
        """All scores at 15 -> Grade D."""
        result = calculate_composite_score(15, 15, 15, 15, 15)
        assert result["composite_score"] == 15.0
        assert result["grade"] == "D"
        assert "Weak" in result["grade_description"]

    def test_weight_sum_equals_1(self):
        """Verify component weights sum to 1.0."""
        total = sum(COMPONENT_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_grade_b_boundary(self):
        """Score of exactly 70 -> Grade B."""
        # 70 = 0.25*s1 + 0.30*s2 + 0.20*s3 + 0.15*s4 + 0.10*s5
        # Use uniform 70 for all: 70*1.0 = 70
        result = calculate_composite_score(70, 70, 70, 70, 70)
        assert result["composite_score"] == 70.0
        assert result["grade"] == "B"

    def test_grade_c_boundary(self):
        """Score of exactly 55 -> Grade C."""
        result = calculate_composite_score(55, 55, 55, 55, 55)
        assert result["composite_score"] == 55.0
        assert result["grade"] == "C"

    def test_grade_a_boundary(self):
        """Score of exactly 85 -> Grade A."""
        result = calculate_composite_score(85, 85, 85, 85, 85)
        assert result["composite_score"] == 85.0
        assert result["grade"] == "A"

    def test_weakest_and_strongest_components(self):
        """Verify weakest and strongest component identification."""
        result = calculate_composite_score(
            gap_score=90,
            trend_score=40,
            volume_score=60,
            ma200_score=70,
            ma50_score=80,
        )
        assert result["weakest_component"] == "Pre-Earnings Trend"
        assert result["weakest_score"] == 40
        assert result["strongest_component"] == "Gap Size"
        assert result["strongest_score"] == 90

    def test_component_breakdown_present(self):
        """Component breakdown dict is present with all components."""
        result = calculate_composite_score(80, 70, 60, 50, 40)
        assert "component_breakdown" in result
        assert len(result["component_breakdown"]) == 5
        assert "Gap Size" in result["component_breakdown"]
        assert "Pre-Earnings Trend" in result["component_breakdown"]
        assert "Volume Trend" in result["component_breakdown"]
        assert "MA200 Position" in result["component_breakdown"]
        assert "MA50 Position" in result["component_breakdown"]


# ===========================================================================
# Report Generator Tests
# ===========================================================================


class TestReportGenerator:
    """Test JSON and Markdown report generation."""

    def _make_result(self, symbol="AAPL", score=82.5, grade="B", gap_pct=6.3):
        return {
            "symbol": symbol,
            "company_name": f"{symbol} Inc.",
            "earnings_date": "2026-02-15",
            "earnings_timing": "amc",
            "gap_pct": gap_pct,
            "composite_score": score,
            "grade": grade,
            "grade_description": "Good earnings reaction worth monitoring",
            "guidance": "Monitor for follow-through buying.",
            "weakest_component": "Volume Trend",
            "strongest_component": "Gap Size",
            "component_breakdown": {
                "Gap Size": {"score": 85.0, "weight": 0.25, "weighted_score": 21.2},
                "Pre-Earnings Trend": {"score": 70.0, "weight": 0.30, "weighted_score": 21.0},
                "Volume Trend": {"score": 60.0, "weight": 0.20, "weighted_score": 12.0},
                "MA200 Position": {"score": 85.0, "weight": 0.15, "weighted_score": 12.8},
                "MA50 Position": {"score": 80.0, "weight": 0.10, "weighted_score": 8.0},
            },
            "current_price": 197.5,
            "market_cap": 3_000_000_000_000,
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "components": {
                "gap_size": {"gap_pct": gap_pct, "score": 85.0},
                "pre_earnings_trend": {"return_20d_pct": 8.5, "score": 70.0},
                "volume_trend": {"vol_ratio_20_60": 1.3, "score": 60.0},
                "ma200_position": {"distance_pct": 15.0, "score": 85.0},
                "ma50_position": {"distance_pct": 7.0, "score": 80.0},
            },
        }

    def test_json_has_schema_version(self):
        """JSON output must have schema_version '1.0'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._make_result()
            json_path = os.path.join(tmpdir, "test.json")
            metadata = {
                "generated_at": "2026-02-21T10:00:00",
                "generator": "earnings-trade-analyzer",
                "generator_version": "1.0.0",
                "lookback_days": 2,
                "total_screened": 50,
            }
            generate_json_report([result], metadata, json_path)
            with open(json_path) as f:
                data = json.load(f)
            assert data["schema_version"] == "1.0"

    def test_json_has_required_fields(self):
        """JSON output has all required top-level fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._make_result()
            json_path = os.path.join(tmpdir, "test.json")
            metadata = {
                "generated_at": "2026-02-21T10:00:00",
                "generator": "earnings-trade-analyzer",
                "generator_version": "1.0.0",
                "lookback_days": 2,
                "total_screened": 50,
            }
            generate_json_report([result], metadata, json_path)
            with open(json_path) as f:
                data = json.load(f)
            assert "metadata" in data
            assert "results" in data
            assert "summary" in data
            assert "schema_version" in data

    def test_json_result_fields(self):
        """Each result in JSON has required fields including earnings_timing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._make_result()
            json_path = os.path.join(tmpdir, "test.json")
            metadata = {"generated_at": "2026-02-21", "lookback_days": 2, "total_screened": 1}
            generate_json_report([result], metadata, json_path)
            with open(json_path) as f:
                data = json.load(f)
            r = data["results"][0]
            assert r["symbol"] == "AAPL"
            assert r["earnings_timing"] == "amc"
            assert r["gap_pct"] == 6.3
            assert r["composite_score"] == 82.5
            assert r["grade"] == "B"
            assert "components" in r

    def test_json_summary_counts(self):
        """Summary counts grades correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = [
                self._make_result("A1", score=90, grade="A"),
                self._make_result("B1", score=75, grade="B"),
                self._make_result("B2", score=72, grade="B"),
                self._make_result("C1", score=60, grade="C"),
                self._make_result("D1", score=40, grade="D"),
            ]
            json_path = os.path.join(tmpdir, "test.json")
            metadata = {"generated_at": "2026-02-21", "lookback_days": 2, "total_screened": 5}
            generate_json_report(results, metadata, json_path)
            with open(json_path) as f:
                data = json.load(f)
            assert data["summary"]["grade_a"] == 1
            assert data["summary"]["grade_b"] == 2
            assert data["summary"]["grade_c"] == 1
            assert data["summary"]["grade_d"] == 1
            assert data["summary"]["total"] == 5

    def test_markdown_generation(self):
        """Markdown report generates without errors and contains key elements."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._make_result()
            md_path = os.path.join(tmpdir, "test.md")
            metadata = {
                "generated_at": "2026-02-21T10:00:00",
                "lookback_days": 2,
                "total_screened": 1,
            }
            generate_markdown_report([result], metadata, md_path)
            with open(md_path) as f:
                content = f.read()
            assert "Earnings Trade Analyzer Report" in content
            assert "AAPL" in content
            assert "Grade A & B Details" in content

    def test_markdown_sector_distribution(self):
        """Markdown report includes sector distribution table."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = [
                self._make_result("AAPL"),
                self._make_result("MSFT"),
            ]
            results[1]["sector"] = "Software"
            md_path = os.path.join(tmpdir, "test.md")
            metadata = {"generated_at": "2026-02-21", "lookback_days": 2, "total_screened": 2}
            generate_markdown_report(results, metadata, md_path)
            with open(md_path) as f:
                content = f.read()
            assert "Sector Distribution" in content
            assert "Technology" in content
            assert "Software" in content

    def test_json_uses_all_results_for_summary(self):
        """When all_results provided, summary counts from all_results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            all_results = [
                self._make_result(f"S{i}", score=90 - i * 5, grade="A" if i == 0 else "B")
                for i in range(10)
            ]
            top_results = all_results[:3]
            json_path = os.path.join(tmpdir, "test.json")
            metadata = {"generated_at": "2026-02-21", "lookback_days": 2, "total_screened": 10}
            generate_json_report(top_results, metadata, json_path, all_results=all_results)
            with open(json_path) as f:
                data = json.load(f)
            assert data["summary"]["total"] == 10
            assert len(data["results"]) == 3


# ===========================================================================
# Yahoo Finance Client Tests
# ===========================================================================


class TestYahooFinanceClient:
    """Test YahooFinanceClient helpers and stats."""

    def test_extract_ticker_standard(self):
        """Extract ticker from standard EDGAR display_name format."""
        name = "APPLE INC  (AAPL)  (CIK 0000320193)"
        assert YahooFinanceClient._extract_ticker(name) == "AAPL"

    def test_extract_ticker_short(self):
        """Single-letter ticker extracts correctly."""
        name = "SOME CORP  (F)  (CIK 0000037996)"
        assert YahooFinanceClient._extract_ticker(name) == "F"

    def test_extract_ticker_missing(self):
        """No parenthesised uppercase sequence -> None."""
        assert YahooFinanceClient._extract_ticker("No ticker here") is None

    def test_extract_ticker_skips_lowercase(self):
        """Lowercase or mixed-case parenthetical is not a ticker."""
        result = YahooFinanceClient._extract_ticker("Company (Inc.) details")
        assert result is None

    def test_api_stats_structure(self):
        """get_api_stats returns expected keys."""
        client = YahooFinanceClient()
        stats = client.get_api_stats()
        assert "api_calls_made" in stats
        assert "cache_entries" in stats
        assert "data_source" in stats
        assert stats["data_source"] == "sec_edgar_yfinance"

    def test_clear_cache(self):
        """clear_cache empties the cache dict."""
        client = YahooFinanceClient()
        client.cache["foo"] = "bar"
        client.clear_cache()
        assert client.cache == {}

    def test_us_exchanges_non_empty(self):
        """US_EXCHANGES is a non-empty set."""
        assert isinstance(YahooFinanceClient.US_EXCHANGES, set)
        assert len(YahooFinanceClient.US_EXCHANGES) > 0
        assert "NMS" in YahooFinanceClient.US_EXCHANGES  # NASDAQ Global Select
        assert "NYQ" in YahooFinanceClient.US_EXCHANGES  # NYSE

    @patch("yahoo_finance_client.requests.Session")
    def test_get_earnings_calendar_filters_item_202(self, mock_session_cls):
        """Only 8-K filings with item '2.02' are returned."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.headers = {}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hits": {
                "total": {"value": 2},
                "hits": [
                    {
                        "_source": {
                            "items": ["2.02", "9.01"],
                            "file_date": "2025-01-05",
                            "display_names": ["APPLE INC  (AAPL)  (CIK 0000320193)"],
                        }
                    },
                    {
                        "_source": {
                            "items": ["1.01"],  # not an earnings report
                            "file_date": "2025-01-05",
                            "display_names": ["OTHER CORP  (OTHR)  (CIK 0000111111)"],
                        }
                    },
                ],
            }
        }
        mock_session.get.return_value = mock_resp

        client = YahooFinanceClient()
        results = client.get_earnings_calendar("2025-01-05", "2025-01-05")

        assert len(results) == 1
        assert results[0]["symbol"] == "AAPL"
        assert results[0]["date"] == "2025-01-05"
        assert results[0]["time"] == "unknown"

    @patch("yahoo_finance_client.requests.Session")
    def test_get_earnings_calendar_deduplicates(self, mock_session_cls):
        """Same ticker appearing in multiple filings is returned once."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_session.headers = {}

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hits": {
                "total": {"value": 2},
                "hits": [
                    {
                        "_source": {
                            "items": ["2.02"],
                            "file_date": "2025-01-05",
                            "display_names": ["AAPL CORP  (AAPL)  (CIK 0000000001)"],
                        }
                    },
                    {
                        "_source": {
                            "items": ["2.02"],
                            "file_date": "2025-01-05",
                            "display_names": ["AAPL CORP  (AAPL)  (CIK 0000000001)"],
                        }
                    },
                ],
            }
        }
        mock_session.get.return_value = mock_resp

        client = YahooFinanceClient()
        results = client.get_earnings_calendar("2025-01-05", "2025-01-05")

        assert len(results) == 1

    @patch("yahoo_finance_client.yf.Ticker")
    def test_get_historical_prices_most_recent_first(self, mock_ticker_cls):
        """get_historical_prices returns rows in most-recent-first order."""
        import pandas as pd

        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker

        dates = pd.to_datetime(["2025-01-03", "2025-01-06", "2025-01-07"])
        hist = pd.DataFrame(
            {
                "Open": [100.0, 102.0, 104.0],
                "High": [101.0, 103.0, 105.0],
                "Low": [99.0, 101.0, 103.0],
                "Close": [100.5, 102.5, 104.5],
                "Volume": [1_000_000, 1_100_000, 1_200_000],
            },
            index=dates,
        )
        mock_ticker.history.return_value = hist

        client = YahooFinanceClient()
        result = client.get_historical_prices("AAPL", days=3)

        assert result is not None
        rows = result["historical"]
        assert rows[0]["date"] == "2025-01-07"  # most recent first
        assert rows[-1]["date"] == "2025-01-03"
        assert rows[0]["close"] == 104.5

    @patch("yahoo_finance_client.yf.Ticker")
    def test_get_historical_prices_empty_returns_none(self, mock_ticker_cls):
        """Empty DataFrame from yfinance -> None."""
        import pandas as pd

        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = pd.DataFrame()

        client = YahooFinanceClient()
        result = client.get_historical_prices("FAKE", days=250)
        assert result is None

    @patch("yahoo_finance_client.yf.Ticker")
    def test_get_historical_prices_cached(self, mock_ticker_cls):
        """Second call with same args uses cache, not yfinance."""
        import pandas as pd

        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker

        dates = pd.to_datetime(["2025-01-03"])
        hist = pd.DataFrame(
            {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.5], "Volume": [1_000_000]},
            index=dates,
        )
        mock_ticker.history.return_value = hist

        client = YahooFinanceClient()
        client.get_historical_prices("SPY", days=1)
        client.get_historical_prices("SPY", days=1)  # second call

        # Ticker.history called only once (cache hit on second)
        assert mock_ticker.history.call_count == 1

    @patch("yahoo_finance_client.yf.Ticker")
    def test_get_company_profiles_from_quotes_extracts_data(self, mock_ticker_cls):
        """Profile extraction fetches data via Ticker.info (EDGAR entries have empty _yf_quote)."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.info = {
            "marketCap": 3_000_000_000_000,
            "exchange": "NMS",
            "longName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "currentPrice": 195.0,
        }

        client = YahooFinanceClient()
        entries = [
            {
                "symbol": "AAPL",
                "date": "2025-01-05",
                "time": "unknown",
                "_yf_quote": {},
            }
        ]
        profiles = client.get_company_profiles_from_quotes(entries)
        assert "AAPL" in profiles
        p = profiles["AAPL"]
        assert p["mktCap"] == 3_000_000_000_000
        assert p["exchangeShortName"] == "NMS"
        assert p["companyName"] == "Apple Inc."
        assert p["sector"] == "Technology"
        assert p["price"] == 195.0


# ===========================================================================
# Gap Boundary Cases
# ===========================================================================


class TestGapBoundary:
    """Test gap calculation edge cases: Friday BMO, Monday AMC, insufficient data."""

    def test_friday_bmo(self):
        """Friday BMO: gap = open[Friday] / close[Thursday]."""
        prices = [
            {"date": "2025-01-10", "open": 112.0, "close": 113.0, "volume": 2000000},  # Friday
            {"date": "2025-01-09", "open": 100.0, "close": 100.0, "volume": 1000000},  # Thursday
        ]
        # Most-recent-first: idx 0 = Friday, idx 1 = Thursday
        result = calculate_gap(prices, "2025-01-10", "bmo")
        # gap = 112/100 - 1 = 12%
        assert result["gap_pct"] == 12.0
        assert result["gap_type"] == "up"
        assert result["score"] == 100.0

    def test_monday_amc(self):
        """Monday AMC: gap = open[Tuesday] / close[Monday]."""
        prices = [
            {"date": "2025-01-14", "open": 108.0, "close": 109.0, "volume": 2000000},  # Tuesday
            {"date": "2025-01-13", "open": 100.0, "close": 100.0, "volume": 3000000},  # Monday
        ]
        # AMC: gap = open[next_day] / close[earnings_date]
        # next_day idx = 0 (Tuesday), earnings_date idx = 1 (Monday)
        result = calculate_gap(prices, "2025-01-13", "amc")
        # gap = 108/100 - 1 = 8%
        assert result["gap_pct"] == 8.0
        assert result["gap_type"] == "up"
        assert result["score"] == 85.0  # >= 7%

    def test_insufficient_data_no_prev_day(self):
        """BMO with no previous day returns warning."""
        prices = [
            {"date": "2025-01-10", "open": 112.0, "close": 113.0, "volume": 1000000},
        ]
        result = calculate_gap(prices, "2025-01-10", "bmo")
        assert result["score"] == 0.0
        assert "warning" in result

    def test_insufficient_data_no_next_day(self):
        """AMC with no next day returns warning."""
        prices = [
            {"date": "2025-01-10", "open": 100.0, "close": 100.0, "volume": 1000000},
        ]
        result = calculate_gap(prices, "2025-01-10", "amc")
        assert result["score"] == 0.0
        assert "warning" in result

    def test_pre_earnings_trend_insufficient_data_below_20(self):
        """Pre-earnings trend with < 20 days before earnings -> score 0 + warning."""
        prices = []
        for i in range(15):
            prices.append(
                {
                    "date": f"2025-01-{15 - i:02d}",
                    "close": 100.0,
                    "volume": 1000000,
                }
            )
        result = calculate_pre_earnings_trend(prices, "2025-01-15")
        assert result["score"] == 0.0
        assert "warning" in result


# ===========================================================================
# Entry Filter Tests (Fix #2)
# ===========================================================================


class TestEntryFilter:
    """Test entry quality filter rules from 517-trade backtest."""

    def _make_result(self, price=50.0, gap_pct=5.0, score=75.0):
        return {
            "current_price": price,
            "gap_pct": gap_pct,
            "composite_score": score,
        }

    def test_price_above_30_passes(self):
        """Price >= $30 passes the filter."""
        results = [self._make_result(price=50.0)]
        filtered = apply_entry_filter(results)
        assert len(filtered) == 1

    def test_price_below_10_excluded(self):
        """Price < $10 excluded (below $30 threshold)."""
        results = [self._make_result(price=8.0)]
        filtered = apply_entry_filter(results)
        assert len(filtered) == 0

    def test_price_15_excluded(self):
        """Price $15 excluded ($10-$30 low price band)."""
        results = [self._make_result(price=15.0)]
        filtered = apply_entry_filter(results)
        assert len(filtered) == 0

    def test_price_29_excluded(self):
        """Price $29 excluded (just below $30 threshold)."""
        results = [self._make_result(price=29.0)]
        filtered = apply_entry_filter(results)
        assert len(filtered) == 0

    def test_price_30_passes(self):
        """Price exactly $30 passes."""
        results = [self._make_result(price=30.0)]
        filtered = apply_entry_filter(results)
        assert len(filtered) == 1

    def test_high_gap_high_score_excluded(self):
        """Gap >= 10% AND score >= 85 excluded (paradox pattern)."""
        results = [self._make_result(price=100.0, gap_pct=12.0, score=90.0)]
        filtered = apply_entry_filter(results)
        assert len(filtered) == 0

    def test_high_gap_low_score_passes(self):
        """Gap >= 10% but score < 85 passes."""
        results = [self._make_result(price=100.0, gap_pct=12.0, score=80.0)]
        filtered = apply_entry_filter(results)
        assert len(filtered) == 1

    def test_low_gap_high_score_passes(self):
        """Gap < 10% with score >= 85 passes."""
        results = [self._make_result(price=100.0, gap_pct=8.0, score=90.0)]
        filtered = apply_entry_filter(results)
        assert len(filtered) == 1

    def test_negative_gap_excluded_by_abs(self):
        """Negative gap >= 10% AND score >= 85 also excluded."""
        results = [self._make_result(price=100.0, gap_pct=-11.0, score=88.0)]
        filtered = apply_entry_filter(results)
        assert len(filtered) == 0

    def test_mixed_results(self):
        """Mixed batch: only valid entries survive."""
        results = [
            self._make_result(price=100.0, gap_pct=5.0, score=80.0),  # Pass
            self._make_result(price=15.0, gap_pct=5.0, score=80.0),  # Fail: price < $30
            self._make_result(price=100.0, gap_pct=12.0, score=90.0),  # Fail: gap+score
            self._make_result(price=50.0, gap_pct=3.0, score=75.0),  # Pass
        ]
        filtered = apply_entry_filter(results)
        assert len(filtered) == 2
