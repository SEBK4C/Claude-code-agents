"""
Tests for the validation utilities module.

This module tests all validation functions including:
- Price validation
- Lot size validation
- Instrument validation
- Account name validation
- Currency validation
- Time format validation
- Direction validation
- Stop-loss and take-profit validation
"""

from decimal import Decimal

import pytest

from utils.validation import (
    KNOWN_INSTRUMENTS,
    SUPPORTED_CURRENCIES,
    ValidationResult,
    validate_account_name,
    validate_currency,
    validate_direction,
    validate_instrument,
    validate_lot_size,
    validate_price,
    validate_sl_tp,
    validate_time_format,
)


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_valid_result(self):
        """Test creating a valid result."""
        result = ValidationResult(is_valid=True, value=Decimal("100.00"), error=None)
        assert result.is_valid is True
        assert result.value == Decimal("100.00")
        assert result.error is None

    def test_invalid_result(self):
        """Test creating an invalid result."""
        result = ValidationResult(is_valid=False, value=None, error="Invalid input")
        assert result.is_valid is False
        assert result.value is None
        assert result.error == "Invalid input"


class TestValidatePrice:
    """Tests for validate_price function."""

    def test_valid_price(self):
        """Test valid price input."""
        result = validate_price("123.45")
        assert result.is_valid is True
        assert result.value == Decimal("123.45")
        assert result.error is None

    def test_empty_price(self):
        """Test empty price input."""
        result = validate_price("")
        assert result.is_valid is False
        assert result.error is not None
        assert "empty" in result.error.lower()

    def test_negative_price(self):
        """Test negative price is rejected."""
        result = validate_price("-100.00")
        assert result.is_valid is False
        assert "greater than zero" in result.error.lower()

    def test_zero_price(self):
        """Test zero price is rejected."""
        result = validate_price("0")
        assert result.is_valid is False
        assert "greater than zero" in result.error.lower()

    def test_comma_decimal_separator(self):
        """Test comma as decimal separator is accepted."""
        result = validate_price("123,45")
        assert result.is_valid is True
        assert result.value == Decimal("123.45")

    def test_invalid_format(self):
        """Test invalid price format."""
        result = validate_price("abc")
        assert result.is_valid is False
        assert "invalid" in result.error.lower()

    def test_whitespace_trimmed(self):
        """Test whitespace is trimmed."""
        result = validate_price("  100.00  ")
        assert result.is_valid is True
        assert result.value == Decimal("100.00")


class TestValidateLotSize:
    """Tests for validate_lot_size function."""

    def test_valid_lot_size(self):
        """Test valid lot size."""
        result = validate_lot_size("0.10")
        assert result.is_valid is True
        assert result.value == Decimal("0.10")

    def test_minimum_lot_size(self):
        """Test minimum lot size (0.01)."""
        result = validate_lot_size("0.01")
        assert result.is_valid is True
        assert result.value == Decimal("0.01")

    def test_below_minimum(self):
        """Test lot size below minimum is rejected."""
        result = validate_lot_size("0.001")
        assert result.is_valid is False
        assert "at least" in result.error.lower()

    def test_above_maximum(self):
        """Test lot size above maximum is rejected."""
        result = validate_lot_size("1001")
        assert result.is_valid is False
        assert "exceed" in result.error.lower()

    def test_empty_lot_size(self):
        """Test empty lot size."""
        result = validate_lot_size("")
        assert result.is_valid is False
        assert "empty" in result.error.lower()

    def test_invalid_format(self):
        """Test invalid lot size format."""
        result = validate_lot_size("large")
        assert result.is_valid is False
        assert "invalid" in result.error.lower()

    def test_custom_min_max(self):
        """Test custom min and max values."""
        result = validate_lot_size(
            "0.5",
            min_lot=Decimal("1"),
            max_lot=Decimal("10"),
        )
        assert result.is_valid is False
        assert "at least 1" in result.error.lower()


class TestValidateInstrument:
    """Tests for validate_instrument function."""

    def test_known_instrument_dax(self):
        """Test DAX is recognized."""
        result = validate_instrument("DAX")
        assert result.is_valid is True
        assert result.value == "DAX"

    def test_known_instrument_nasdaq(self):
        """Test NASDAQ is recognized."""
        result = validate_instrument("nasdaq")
        assert result.is_valid is True
        assert result.value == "NASDAQ"

    def test_forex_pair_with_slash(self):
        """Test forex pair with slash is normalized."""
        result = validate_instrument("EUR/USD")
        assert result.is_valid is True
        assert result.value == "EURUSD"

    def test_custom_instrument_allowed(self):
        """Test custom instrument is allowed by default."""
        result = validate_instrument("CUSTOM123")
        assert result.is_valid is True
        assert result.value == "CUSTOM123"

    def test_custom_instrument_rejected_when_disabled(self):
        """Test custom instrument rejected when disabled."""
        result = validate_instrument("UNKNOWNSYMBOL", allow_custom=False)
        assert result.is_valid is False
        assert "unknown" in result.error.lower()

    def test_empty_instrument(self):
        """Test empty instrument."""
        result = validate_instrument("")
        assert result.is_valid is False
        assert "empty" in result.error.lower()

    def test_too_short_instrument(self):
        """Test too short instrument name."""
        result = validate_instrument("X")
        assert result.is_valid is False

    def test_too_long_instrument(self):
        """Test too long instrument name."""
        result = validate_instrument("A" * 25)
        assert result.is_valid is False


class TestValidateAccountName:
    """Tests for validate_account_name function."""

    def test_valid_account_name(self):
        """Test valid account name."""
        result = validate_account_name("Main Account")
        assert result.is_valid is True
        assert result.value == "Main Account"

    def test_too_short_name(self):
        """Test name below 3 characters."""
        result = validate_account_name("AB")
        assert result.is_valid is False
        assert "at least 3" in result.error.lower()

    def test_too_long_name(self):
        """Test name above 50 characters."""
        result = validate_account_name("A" * 51)
        assert result.is_valid is False
        assert "50" in result.error.lower()

    def test_empty_name(self):
        """Test empty account name."""
        result = validate_account_name("")
        assert result.is_valid is False
        assert "empty" in result.error.lower()

    def test_name_with_numbers(self):
        """Test name with numbers is allowed."""
        result = validate_account_name("Account 123")
        assert result.is_valid is True

    def test_name_with_hyphen_underscore(self):
        """Test name with hyphens and underscores."""
        result = validate_account_name("My-Account_2024")
        assert result.is_valid is True

    def test_invalid_characters_rejected(self):
        """Test special characters are rejected."""
        result = validate_account_name("Account@#$!")
        assert result.is_valid is False
        assert "only contain" in result.error.lower()

    def test_whitespace_trimmed(self):
        """Test whitespace is trimmed."""
        result = validate_account_name("  Test Account  ")
        assert result.is_valid is True
        assert result.value == "Test Account"


class TestValidateCurrency:
    """Tests for validate_currency function."""

    def test_valid_usd(self):
        """Test USD is valid."""
        result = validate_currency("USD")
        assert result.is_valid is True
        assert result.value == "USD"

    def test_valid_eur(self):
        """Test EUR is valid."""
        result = validate_currency("eur")
        assert result.is_valid is True
        assert result.value == "EUR"

    def test_valid_gbp(self):
        """Test GBP is valid."""
        result = validate_currency("GBP")
        assert result.is_valid is True

    def test_unsupported_currency(self):
        """Test unsupported currency is rejected."""
        result = validate_currency("XYZ")
        assert result.is_valid is False
        assert "unsupported" in result.error.lower()

    def test_empty_currency(self):
        """Test empty currency."""
        result = validate_currency("")
        assert result.is_valid is False
        assert "empty" in result.error.lower()

    def test_all_supported_currencies(self):
        """Test all currencies in SUPPORTED_CURRENCIES are valid."""
        for currency in SUPPORTED_CURRENCIES:
            result = validate_currency(currency)
            assert result.is_valid is True, f"Currency {currency} should be valid"


class TestValidateTimeFormat:
    """Tests for validate_time_format function."""

    def test_valid_time_24h(self):
        """Test valid 24-hour time."""
        result = validate_time_format("14:30")
        assert result.is_valid is True
        assert result.value == "14:30"

    def test_valid_time_single_digit_hour(self):
        """Test single digit hour is normalized."""
        result = validate_time_format("9:30")
        assert result.is_valid is True
        assert result.value == "09:30"

    def test_midnight(self):
        """Test midnight is valid."""
        result = validate_time_format("00:00")
        assert result.is_valid is True
        assert result.value == "00:00"

    def test_end_of_day(self):
        """Test 23:59 is valid."""
        result = validate_time_format("23:59")
        assert result.is_valid is True

    def test_invalid_hour_24(self):
        """Test hour 24 is invalid."""
        result = validate_time_format("24:00")
        assert result.is_valid is False
        assert "hour" in result.error.lower()

    def test_invalid_minutes_60(self):
        """Test 60 minutes is invalid."""
        result = validate_time_format("12:60")
        assert result.is_valid is False
        assert "minute" in result.error.lower()

    def test_invalid_format_no_colon(self):
        """Test invalid format without colon."""
        result = validate_time_format("1430")
        assert result.is_valid is False
        assert "format" in result.error.lower()

    def test_empty_time(self):
        """Test empty time."""
        result = validate_time_format("")
        assert result.is_valid is False
        assert "empty" in result.error.lower()


class TestValidateDirection:
    """Tests for validate_direction function."""

    def test_long_uppercase(self):
        """Test LONG in uppercase."""
        result = validate_direction("LONG")
        assert result.is_valid is True
        assert result.value == "LONG"

    def test_long_lowercase(self):
        """Test long in lowercase."""
        result = validate_direction("long")
        assert result.is_valid is True
        assert result.value == "LONG"

    def test_short_uppercase(self):
        """Test SHORT in uppercase."""
        result = validate_direction("SHORT")
        assert result.is_valid is True
        assert result.value == "SHORT"

    def test_short_lowercase(self):
        """Test short in lowercase."""
        result = validate_direction("short")
        assert result.is_valid is True
        assert result.value == "SHORT"

    def test_invalid_direction(self):
        """Test invalid direction."""
        result = validate_direction("sideways")
        assert result.is_valid is False
        assert "LONG" in result.error
        assert "SHORT" in result.error

    def test_empty_direction(self):
        """Test empty direction."""
        result = validate_direction("")
        assert result.is_valid is False
        assert "empty" in result.error.lower()


class TestValidateSlTp:
    """Tests for validate_sl_tp function."""

    def test_valid_long_sl_tp(self):
        """Test valid SL/TP for long trade."""
        result = validate_sl_tp(
            entry_price="100",
            sl_price="95",
            tp_price="110",
            direction="LONG",
        )
        assert result.is_valid is True
        sl, tp = result.value
        assert sl == Decimal("95")
        assert tp == Decimal("110")

    def test_valid_short_sl_tp(self):
        """Test valid SL/TP for short trade."""
        result = validate_sl_tp(
            entry_price="100",
            sl_price="105",
            tp_price="90",
            direction="SHORT",
        )
        assert result.is_valid is True
        sl, tp = result.value
        assert sl == Decimal("105")
        assert tp == Decimal("90")

    def test_long_sl_above_entry_invalid(self):
        """Test SL above entry for long trade is invalid."""
        result = validate_sl_tp(
            entry_price="100",
            sl_price="105",
            tp_price="110",
            direction="LONG",
        )
        assert result.is_valid is False
        assert "below entry" in result.error.lower()

    def test_long_tp_below_entry_invalid(self):
        """Test TP below entry for long trade is invalid."""
        result = validate_sl_tp(
            entry_price="100",
            sl_price="95",
            tp_price="90",
            direction="LONG",
        )
        assert result.is_valid is False
        assert "above entry" in result.error.lower()

    def test_short_sl_below_entry_invalid(self):
        """Test SL below entry for short trade is invalid."""
        result = validate_sl_tp(
            entry_price="100",
            sl_price="95",
            tp_price="90",
            direction="SHORT",
        )
        assert result.is_valid is False
        assert "above entry" in result.error.lower()

    def test_short_tp_above_entry_invalid(self):
        """Test TP above entry for short trade is invalid."""
        result = validate_sl_tp(
            entry_price="100",
            sl_price="105",
            tp_price="110",
            direction="SHORT",
        )
        assert result.is_valid is False
        assert "below entry" in result.error.lower()

    def test_none_sl_tp_valid(self):
        """Test None SL/TP values are valid (optional)."""
        result = validate_sl_tp(
            entry_price="100",
            sl_price=None,
            tp_price=None,
            direction="LONG",
        )
        assert result.is_valid is True
        sl, tp = result.value
        assert sl is None
        assert tp is None

    def test_only_sl_provided(self):
        """Test only SL provided is valid."""
        result = validate_sl_tp(
            entry_price="100",
            sl_price="95",
            tp_price=None,
            direction="LONG",
        )
        assert result.is_valid is True
        sl, tp = result.value
        assert sl == Decimal("95")
        assert tp is None

    def test_invalid_entry_price_format(self):
        """Test invalid entry price format."""
        result = validate_sl_tp(
            entry_price="invalid",
            sl_price="95",
            tp_price="105",
            direction="LONG",
        )
        assert result.is_valid is False
        assert "entry price" in result.error.lower()

    def test_invalid_direction(self):
        """Test invalid direction."""
        result = validate_sl_tp(
            entry_price="100",
            sl_price="95",
            tp_price="105",
            direction="SIDEWAYS",
        )
        assert result.is_valid is False
        assert "direction" in result.error.lower()
