"""
Tests for the Instrument Configuration.

This module tests:
- INSTRUMENTS_CONFIG dictionary
- get_instrument_config helper function
- BASE_CURRENCY and EXCHANGE_RATE_CACHE_TTL constants
"""

import pytest

from config import (
    BASE_CURRENCY,
    EXCHANGE_RATE_CACHE_TTL,
    INSTRUMENTS_CONFIG,
    get_instrument_config,
)


class TestInstrumentsConfig:
    """Tests for the INSTRUMENTS_CONFIG dictionary."""

    def test_instruments_config_exists(self):
        """Test that INSTRUMENTS_CONFIG is defined and is a dict."""
        assert isinstance(INSTRUMENTS_CONFIG, dict)

    def test_dax_config(self):
        """Test DAX instrument configuration."""
        assert "DAX" in INSTRUMENTS_CONFIG
        dax = INSTRUMENTS_CONFIG["DAX"]

        assert dax["symbol"] == "^GDAXI"
        assert dax["currency"] == "EUR"
        assert dax["point_value"] == 1.0

    def test_nasdaq_config(self):
        """Test NASDAQ instrument configuration."""
        assert "NASDAQ" in INSTRUMENTS_CONFIG
        nasdaq = INSTRUMENTS_CONFIG["NASDAQ"]

        assert nasdaq["symbol"] == "^IXIC"
        assert nasdaq["currency"] == "USD"
        assert nasdaq["point_value"] == 1.0

    def test_all_instruments_have_required_keys(self):
        """Test all instruments have required configuration keys."""
        required_keys = {"symbol", "currency", "point_value"}

        for instrument, config in INSTRUMENTS_CONFIG.items():
            for key in required_keys:
                assert key in config, f"{instrument} missing key: {key}"


class TestGetInstrumentConfig:
    """Tests for the get_instrument_config helper function."""

    def test_get_known_instrument(self):
        """Test getting a known instrument returns its config."""
        config = get_instrument_config("DAX")
        assert config["symbol"] == "^GDAXI"
        assert config["currency"] == "EUR"
        assert config["point_value"] == 1.0

    def test_get_instrument_case_insensitive(self):
        """Test that instrument lookup is case-insensitive."""
        config_lower = get_instrument_config("dax")
        config_upper = get_instrument_config("DAX")
        config_mixed = get_instrument_config("Dax")

        assert config_lower == config_upper == config_mixed

    def test_get_unknown_instrument_returns_default(self):
        """Test unknown instrument returns default configuration."""
        config = get_instrument_config("UNKNOWN_SYMBOL")

        assert config["symbol"] == "UNKNOWN_SYMBOL"
        assert config["currency"] == "USD"
        assert config["point_value"] == 1.0

    def test_get_instrument_preserves_original_for_unknown(self):
        """Test unknown instrument preserves original symbol name."""
        config = get_instrument_config("MY_CUSTOM_INSTRUMENT")
        assert config["symbol"] == "MY_CUSTOM_INSTRUMENT"

    def test_get_instrument_different_currencies(self):
        """Test getting instruments with different currencies."""
        dax_config = get_instrument_config("DAX")
        nasdaq_config = get_instrument_config("NASDAQ")

        assert dax_config["currency"] == "EUR"
        assert nasdaq_config["currency"] == "USD"


class TestBaseCurrency:
    """Tests for the BASE_CURRENCY constant."""

    def test_base_currency_is_usd(self):
        """Test that BASE_CURRENCY is set to USD."""
        assert BASE_CURRENCY == "USD"

    def test_base_currency_is_string(self):
        """Test that BASE_CURRENCY is a string."""
        assert isinstance(BASE_CURRENCY, str)


class TestExchangeRateCacheTTL:
    """Tests for the EXCHANGE_RATE_CACHE_TTL constant."""

    def test_cache_ttl_is_60_seconds(self):
        """Test that cache TTL is 1 minute (60 seconds) for fresher rates."""
        assert EXCHANGE_RATE_CACHE_TTL == 60

    def test_cache_ttl_is_integer(self):
        """Test that cache TTL is an integer."""
        assert isinstance(EXCHANGE_RATE_CACHE_TTL, int)
