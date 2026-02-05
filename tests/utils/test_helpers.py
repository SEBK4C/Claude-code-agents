"""
Tests for the helper utilities module.

This module tests all helper functions including:
- Currency formatting
- Percentage formatting
- Date/time formatting
- P&L calculations
- Risk/reward calculations
- Trade summary formatting
- Text utilities
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

import pytest

from utils.helpers import (
    calculate_pnl,
    calculate_pnl_percent,
    calculate_risk_reward,
    escape_markdown,
    format_currency,
    format_date,
    format_datetime,
    format_percentage,
    format_trade_summary,
    truncate_text,
)


class TestFormatCurrency:
    """Tests for format_currency function."""

    def test_basic_usd_formatting(self):
        """Test basic USD formatting."""
        result = format_currency(1234.56, "USD")
        assert result == "$1,234.56"

    def test_zero_amount(self):
        """Test formatting of zero."""
        result = format_currency(0, "USD")
        assert result == "$0.00"

    def test_negative_amount(self):
        """Test formatting of negative amounts."""
        result = format_currency(-500.00, "USD")
        assert result == "-$500.00"

    def test_with_positive_sign(self):
        """Test formatting with explicit positive sign."""
        result = format_currency(100.50, "USD", include_sign=True)
        assert result == "+$100.50"

    def test_euro_symbol(self):
        """Test EUR currency formatting."""
        result = format_currency(1000, "EUR")
        assert "\u20ac" in result  # Euro symbol

    def test_gbp_symbol(self):
        """Test GBP currency formatting."""
        result = format_currency(1000, "GBP")
        assert "\u00a3" in result  # Pound symbol

    def test_unknown_currency_uses_code(self):
        """Test that unknown currencies use the code as symbol."""
        result = format_currency(1000, "XYZ")
        assert "XYZ" in result

    def test_decimal_input(self):
        """Test Decimal input handling."""
        result = format_currency(Decimal("1234.567"), "USD")
        assert result == "$1,234.57"

    def test_large_number_thousands_separator(self):
        """Test thousands separator for large numbers."""
        result = format_currency(1000000.00, "USD")
        assert result == "$1,000,000.00"


class TestFormatPercentage:
    """Tests for format_percentage function."""

    def test_positive_percentage_with_sign(self):
        """Test positive percentage with sign."""
        result = format_percentage(5.25)
        assert result == "+5.25%"

    def test_negative_percentage(self):
        """Test negative percentage formatting."""
        result = format_percentage(-3.50)
        assert result == "-3.50%"

    def test_zero_percentage(self):
        """Test zero percentage."""
        result = format_percentage(0)
        assert result == "0.00%"

    def test_without_sign(self):
        """Test formatting without sign."""
        result = format_percentage(5.25, include_sign=False)
        assert result == "5.25%"

    def test_custom_decimal_places(self):
        """Test custom decimal places."""
        result = format_percentage(5.2567, decimal_places=4)
        assert result == "+5.2567%"

    def test_decimal_input(self):
        """Test Decimal input handling."""
        result = format_percentage(Decimal("10.5"))
        assert result == "+10.50%"


class TestFormatDatetime:
    """Tests for format_datetime function."""

    def test_basic_datetime(self):
        """Test basic datetime formatting."""
        dt = datetime(2024, 1, 15, 14, 30, 0)
        result = format_datetime(dt)
        assert result == "Jan 15, 2024 14:30"

    def test_with_seconds(self):
        """Test datetime formatting with seconds."""
        dt = datetime(2024, 1, 15, 14, 30, 45)
        result = format_datetime(dt, include_seconds=True)
        assert result == "Jan 15, 2024 14:30:45"

    def test_none_returns_na(self):
        """Test that None returns N/A."""
        result = format_datetime(None)
        assert result == "N/A"


class TestFormatDate:
    """Tests for format_date function."""

    def test_basic_date(self):
        """Test basic date formatting."""
        dt = datetime(2024, 1, 15)
        result = format_date(dt)
        assert result == "Jan 15, 2024"

    def test_none_returns_na(self):
        """Test that None returns N/A."""
        result = format_date(None)
        assert result == "N/A"


class TestCalculatePnl:
    """Tests for calculate_pnl function."""

    def test_long_winning_trade(self):
        """Test P&L for a winning long trade."""
        result = calculate_pnl(
            entry_price=100,
            exit_price=110,
            direction="long",
            lot_size=1,
        )
        assert result == Decimal("10")

    def test_long_losing_trade(self):
        """Test P&L for a losing long trade."""
        result = calculate_pnl(
            entry_price=100,
            exit_price=90,
            direction="long",
            lot_size=1,
        )
        assert result == Decimal("-10")

    def test_short_winning_trade(self):
        """Test P&L for a winning short trade."""
        result = calculate_pnl(
            entry_price=100,
            exit_price=90,
            direction="short",
            lot_size=1,
        )
        assert result == Decimal("10")

    def test_short_losing_trade(self):
        """Test P&L for a losing short trade."""
        result = calculate_pnl(
            entry_price=100,
            exit_price=110,
            direction="short",
            lot_size=1,
        )
        assert result == Decimal("-10")

    def test_with_lot_size(self):
        """Test P&L scales with lot size."""
        result = calculate_pnl(
            entry_price=100,
            exit_price=110,
            direction="long",
            lot_size=2,
        )
        assert result == Decimal("20")

    def test_with_point_value(self):
        """Test P&L with custom point value."""
        result = calculate_pnl(
            entry_price=100,
            exit_price=110,
            direction="long",
            lot_size=1,
            point_value=25,
        )
        assert result == Decimal("250")

    def test_case_insensitive_direction(self):
        """Test direction is case insensitive."""
        result = calculate_pnl(100, 110, "LONG", 1)
        assert result == Decimal("10")

    def test_invalid_direction_raises(self):
        """Test invalid direction raises ValueError."""
        with pytest.raises(ValueError, match="Invalid direction"):
            calculate_pnl(100, 110, "sideways", 1)


class TestCalculatePnlPercent:
    """Tests for calculate_pnl_percent function."""

    def test_long_winning_percentage(self):
        """Test percentage for winning long trade."""
        result = calculate_pnl_percent(100, 110, "long")
        assert result == Decimal("10.0000")

    def test_long_losing_percentage(self):
        """Test percentage for losing long trade."""
        result = calculate_pnl_percent(100, 90, "long")
        assert result == Decimal("-10.0000")

    def test_short_winning_percentage(self):
        """Test percentage for winning short trade."""
        result = calculate_pnl_percent(100, 90, "short")
        assert result == Decimal("10.0000")

    def test_short_losing_percentage(self):
        """Test percentage for losing short trade."""
        result = calculate_pnl_percent(100, 110, "short")
        assert result == Decimal("-10.0000")

    def test_zero_entry_returns_zero(self):
        """Test that zero entry price returns 0%."""
        result = calculate_pnl_percent(0, 100, "long")
        assert result == Decimal("0")

    def test_invalid_direction_raises(self):
        """Test invalid direction raises ValueError."""
        with pytest.raises(ValueError, match="Invalid direction"):
            calculate_pnl_percent(100, 110, "up")


class TestCalculateRiskReward:
    """Tests for calculate_risk_reward function."""

    def test_long_1_to_2_ratio(self):
        """Test 1:2 risk/reward for long trade."""
        result = calculate_risk_reward(
            entry_price=100,
            sl_price=90,
            tp_price=120,
            direction="long",
        )
        assert result == Decimal("2.00")

    def test_short_1_to_2_ratio(self):
        """Test 1:2 risk/reward for short trade."""
        result = calculate_risk_reward(
            entry_price=100,
            sl_price=110,
            tp_price=80,
            direction="short",
        )
        assert result == Decimal("2.00")

    def test_fractional_ratio(self):
        """Test fractional risk/reward ratio."""
        result = calculate_risk_reward(
            entry_price=100,
            sl_price=95,
            tp_price=107.5,
            direction="long",
        )
        assert result == Decimal("1.50")

    def test_zero_risk_returns_none(self):
        """Test that zero risk returns None."""
        result = calculate_risk_reward(
            entry_price=100,
            sl_price=100,
            tp_price=110,
            direction="long",
        )
        assert result is None

    def test_negative_risk_returns_none(self):
        """Test that negative risk (invalid SL) returns None."""
        # Long trade with SL above entry
        result = calculate_risk_reward(
            entry_price=100,
            sl_price=110,
            tp_price=120,
            direction="long",
        )
        assert result is None

    def test_invalid_direction_raises(self):
        """Test invalid direction raises ValueError."""
        with pytest.raises(ValueError, match="Invalid direction"):
            calculate_risk_reward(100, 90, 110, "both")


class TestFormatTradeSummary:
    """Tests for format_trade_summary function."""

    class MockDirection(str, Enum):
        LONG = "long"
        SHORT = "short"

    class MockStatus(str, Enum):
        OPEN = "open"
        CLOSED = "closed"

    @dataclass
    class MockTrade:
        instrument: str = "EURUSD"
        direction: "TestFormatTradeSummary.MockDirection" = None
        status: "TestFormatTradeSummary.MockStatus" = None
        entry_price: Decimal = Decimal("1.10000")
        exit_price: Optional[Decimal] = None
        sl_price: Optional[Decimal] = None
        tp_price: Optional[Decimal] = None
        lot_size: Decimal = Decimal("0.10")
        pnl: Optional[Decimal] = None
        pnl_percent: Optional[Decimal] = None
        opened_at: Optional[datetime] = None
        closed_at: Optional[datetime] = None
        strategy: Optional[str] = None
        notes: Optional[str] = None

        def __post_init__(self):
            if self.direction is None:
                self.direction = TestFormatTradeSummary.MockDirection.LONG
            if self.status is None:
                self.status = TestFormatTradeSummary.MockStatus.OPEN

    def test_basic_trade_summary(self):
        """Test basic trade summary formatting."""
        trade = self.MockTrade()
        result = format_trade_summary(trade)

        assert "EURUSD" in result
        assert "LONG" in result
        assert "1.10000" in result

    def test_closed_trade_with_pnl(self):
        """Test closed trade shows P&L."""
        trade = self.MockTrade(
            pnl=Decimal("150.00"),
            pnl_percent=Decimal("1.5"),
        )
        result = format_trade_summary(trade)

        assert "P&L:" in result
        assert "150" in result

    def test_includes_sl_tp(self):
        """Test that SL and TP are included when present."""
        trade = self.MockTrade(
            sl_price=Decimal("1.09500"),
            tp_price=Decimal("1.11000"),
        )
        result = format_trade_summary(trade)

        assert "SL:" in result
        assert "TP:" in result

    def test_includes_timestamps(self):
        """Test that timestamps are formatted correctly."""
        trade = self.MockTrade(
            opened_at=datetime(2024, 1, 15, 10, 30),
        )
        result = format_trade_summary(trade)

        assert "Opened:" in result
        assert "Jan 15, 2024" in result

    def test_includes_notes(self):
        """Test that notes are included."""
        trade = self.MockTrade(notes="Test trade entry")
        result = format_trade_summary(trade)

        assert "Notes:" in result
        assert "Test trade entry" in result


class TestTruncateText:
    """Tests for truncate_text function."""

    def test_short_text_unchanged(self):
        """Test that short text is returned unchanged."""
        result = truncate_text("Hello", max_length=10)
        assert result == "Hello"

    def test_long_text_truncated(self):
        """Test that long text is truncated with ellipsis."""
        result = truncate_text("Hello World", max_length=8)
        assert result == "Hello..."

    def test_exact_length_unchanged(self):
        """Test that text at exact limit is unchanged."""
        result = truncate_text("Hello", max_length=5)
        assert result == "Hello"

    def test_empty_string(self):
        """Test empty string handling."""
        result = truncate_text("", max_length=10)
        assert result == ""

    def test_custom_suffix(self):
        """Test custom truncation suffix."""
        result = truncate_text("Hello World", max_length=9, suffix="[...]")
        assert result == "Hell[...]"

    def test_very_short_max_length(self):
        """Test handling when max_length is less than suffix length."""
        result = truncate_text("Hello World", max_length=2)
        assert result == ".."


class TestEscapeMarkdown:
    """Tests for escape_markdown function."""

    def test_underscore_escaped(self):
        """Test underscore is escaped."""
        result = escape_markdown("hello_world")
        assert result == "hello\\_world"

    def test_asterisk_escaped(self):
        """Test asterisk is escaped."""
        result = escape_markdown("*bold*")
        assert result == "\\*bold\\*"

    def test_brackets_escaped(self):
        """Test brackets are escaped."""
        result = escape_markdown("[link](url)")
        assert "\\[" in result
        assert "\\]" in result

    def test_empty_string(self):
        """Test empty string handling."""
        result = escape_markdown("")
        assert result == ""

    def test_plain_text_unchanged(self):
        """Test plain alphanumeric text is mostly unchanged."""
        result = escape_markdown("Hello World 123")
        # Space and letters/numbers are not escaped
        assert "Hello" in result
        assert "123" in result

    def test_multiple_special_chars(self):
        """Test multiple special characters are escaped."""
        result = escape_markdown("Test: *bold* and _italic_")
        assert "\\*" in result
        assert "\\_" in result
