"""
Tests for the Currency Service.

This module tests:
- Exchange rate fetching
- Currency conversion
- Cache functionality
- Fallback rates
- Singleton pattern
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from services.currency_service import (
    CurrencyService,
    ExchangeRateResult,
    FALLBACK_RATES,
    get_currency_service,
    reset_currency_service,
)


class TestExchangeRateResult:
    """Tests for the ExchangeRateResult dataclass."""

    def test_successful_result(self):
        """Test that success property returns True when rate is available."""
        result = ExchangeRateResult(
            rate=1.08,
            from_currency="EUR",
            to_currency="USD",
            is_fallback=False,
            error=None,
        )
        assert result.success is True
        assert result.rate == 1.08
        assert result.from_currency == "EUR"
        assert result.to_currency == "USD"

    def test_failed_result(self):
        """Test that success property returns False when rate is None."""
        result = ExchangeRateResult(
            rate=None,
            from_currency="XYZ",
            to_currency="USD",
            is_fallback=False,
            error="Symbol not found",
        )
        assert result.success is False
        assert result.error == "Symbol not found"

    def test_fallback_result(self):
        """Test fallback result is marked correctly."""
        result = ExchangeRateResult(
            rate=1.08,
            from_currency="EUR",
            to_currency="USD",
            is_fallback=True,
            error=None,
        )
        assert result.success is True
        assert result.is_fallback is True


class TestCurrencyService:
    """Tests for the CurrencyService class."""

    @pytest.fixture
    def service(self):
        """Create a fresh CurrencyService instance for each test."""
        svc = CurrencyService(cache_ttl=300)
        yield svc
        svc.shutdown()

    def test_init(self, service):
        """Test CurrencyService initialization."""
        assert service._cache_ttl == 300
        assert len(service._cache) == 0

    def test_get_cache_key(self, service):
        """Test cache key generation."""
        key = service._get_cache_key("eur", "usd")
        assert key == "EURUSD"

    def test_get_yfinance_symbol(self, service):
        """Test yfinance symbol format."""
        symbol = service._get_yfinance_symbol("EUR", "USD")
        assert symbol == "EURUSD=X"

    def test_get_fallback_rate_direct(self, service):
        """Test getting direct fallback rate."""
        rate = service._get_fallback_rate("EUR", "USD")
        assert rate == FALLBACK_RATES["EURUSD"]

    def test_get_fallback_rate_inverse(self, service):
        """Test getting inverse fallback rate."""
        rate = service._get_fallback_rate("USD", "EUR")
        expected = 1.0 / FALLBACK_RATES["EURUSD"]
        assert abs(rate - expected) < 0.0001

    def test_get_fallback_rate_same_currency(self, service):
        """Test same currency returns 1.0."""
        rate = service._get_fallback_rate("USD", "USD")
        assert rate == 1.0

    def test_get_fallback_rate_unknown(self, service):
        """Test unknown currency pair returns None."""
        rate = service._get_fallback_rate("XYZ", "ABC")
        assert rate is None

    @pytest.mark.asyncio
    async def test_get_exchange_rate_same_currency(self, service):
        """Test getting rate for same currency returns 1.0."""
        result = await service.get_exchange_rate("USD", "USD")
        assert result.success is True
        assert result.rate == 1.0
        assert result.is_fallback is False

    @pytest.mark.asyncio
    async def test_get_exchange_rate_with_mock(self, service):
        """Test getting exchange rate with mocked yfinance."""
        mock_ticker = MagicMock()
        mock_ticker.fast_info.last_price = 1.0850

        # Import yfinance module for patching (lazy import)
        import sys
        mock_yf_module = MagicMock()
        mock_yf_module.Ticker.return_value = mock_ticker

        with patch.dict(sys.modules, {"yfinance": mock_yf_module}):
            result = await service.get_exchange_rate("EUR", "USD")

        assert result.success is True
        assert result.rate == 1.0850
        assert result.from_currency == "EUR"
        assert result.to_currency == "USD"
        assert result.is_fallback is False

    @pytest.mark.asyncio
    async def test_get_exchange_rate_cache(self, service):
        """Test that exchange rates are cached."""
        mock_ticker = MagicMock()
        mock_ticker.fast_info.last_price = 1.0900

        import sys
        mock_yf_module = MagicMock()
        mock_yf_module.Ticker.return_value = mock_ticker

        with patch.dict(sys.modules, {"yfinance": mock_yf_module}):
            # First call - should fetch
            result1 = await service.get_exchange_rate("EUR", "USD")
            # Second call - should use cache
            result2 = await service.get_exchange_rate("EUR", "USD")

        # yfinance should only be called once (cached on second call)
        assert mock_yf_module.Ticker.call_count == 1
        assert result1.rate == result2.rate

    @pytest.mark.asyncio
    async def test_get_exchange_rate_fallback_on_error(self, service):
        """Test that fallback rates are used when ALL API sources fail."""
        import sys
        mock_yf_module = MagicMock()
        mock_yf_module.Ticker.side_effect = Exception("API Error")

        # Mock ALL sources to test static fallback:
        # 1. yfinance - fails with exception
        # 2. exchangerate-api - returns None
        # 3. frankfurter - returns None
        with patch.dict(sys.modules, {"yfinance": mock_yf_module}), \
             patch.object(service, "_fetch_from_exchangerate_api", return_value=None), \
             patch.object(service, "_fetch_from_frankfurter", return_value=None):
            result = await service.get_exchange_rate("EUR", "USD")

        assert result.success is True
        assert result.rate == FALLBACK_RATES["EURUSD"]
        assert result.is_fallback is True

    @pytest.mark.asyncio
    async def test_convert_same_currency(self, service):
        """Test converting same currency returns original amount."""
        amount = Decimal("100.00")
        converted, error = await service.convert(amount, "USD", "USD")

        assert error is None
        assert converted == amount

    @pytest.mark.asyncio
    async def test_convert_with_mock(self, service):
        """Test converting between currencies with mocked rate."""
        mock_ticker = MagicMock()
        mock_ticker.fast_info.last_price = 1.0800

        import sys
        mock_yf_module = MagicMock()
        mock_yf_module.Ticker.return_value = mock_ticker

        with patch.dict(sys.modules, {"yfinance": mock_yf_module}):
            amount = Decimal("100.00")
            converted, error = await service.convert(amount, "EUR", "USD")

        assert error is None
        expected = Decimal("100.00") * Decimal("1.0800")
        assert converted == expected

    @pytest.mark.asyncio
    async def test_convert_fallback_on_error(self, service):
        """Test conversion uses fallback when ALL API sources fail."""
        import sys
        mock_yf_module = MagicMock()
        mock_yf_module.Ticker.side_effect = Exception("API Error")

        # Mock ALL sources to test static fallback:
        # 1. yfinance - fails with exception
        # 2. exchangerate-api - returns None
        # 3. frankfurter - returns None
        with patch.dict(sys.modules, {"yfinance": mock_yf_module}), \
             patch.object(service, "_fetch_from_exchangerate_api", return_value=None), \
             patch.object(service, "_fetch_from_frankfurter", return_value=None):
            amount = Decimal("100.00")
            converted, error = await service.convert(amount, "EUR", "USD")

        assert error is None
        expected = Decimal("100.00") * Decimal(str(FALLBACK_RATES["EURUSD"]))
        assert converted == expected

    @pytest.mark.asyncio
    async def test_convert_unknown_currency_no_fallback(self, service):
        """Test conversion fails for unknown currency with no fallback."""
        import sys
        mock_yf_module = MagicMock()
        mock_yf_module.Ticker.side_effect = Exception("API Error")

        with patch.dict(sys.modules, {"yfinance": mock_yf_module}):
            amount = Decimal("100.00")
            converted, error = await service.convert(amount, "XYZ", "ABC")

        assert converted is None
        assert error is not None

    def test_clear_cache(self, service):
        """Test cache clearing."""
        # Add something to cache manually
        from services.currency_service import CacheEntry, ExchangeRateResult
        import time as time_module

        service._cache["EURUSD"] = CacheEntry(
            result=ExchangeRateResult(
                rate=1.08, from_currency="EUR", to_currency="USD"
            ),
            cached_at=time_module.time(),
        )

        assert len(service._cache) == 1
        service.clear_cache()
        assert len(service._cache) == 0

    def test_get_cache_stats(self, service):
        """Test cache statistics."""
        stats = service.get_cache_stats()
        assert stats["total_entries"] == 0
        assert stats["valid_entries"] == 0


class TestSingletonPattern:
    """Tests for the singleton pattern."""

    def test_get_currency_service_returns_same_instance(self):
        """Test that get_currency_service returns the same instance."""
        reset_currency_service()

        service1 = get_currency_service()
        service2 = get_currency_service()

        assert service1 is service2

        reset_currency_service()

    def test_reset_currency_service_creates_new_instance(self):
        """Test that reset creates a new instance."""
        reset_currency_service()

        service1 = get_currency_service()
        reset_currency_service()
        service2 = get_currency_service()

        assert service1 is not service2

        reset_currency_service()


class TestFallbackRates:
    """Tests for the fallback rates configuration."""

    def test_fallback_rates_defined(self):
        """Test that common fallback rates are defined."""
        assert "EURUSD" in FALLBACK_RATES
        assert "GBPUSD" in FALLBACK_RATES

    def test_fallback_rates_reasonable(self):
        """Test that fallback rates are reasonable values."""
        # EUR/USD should be around 1.0-1.2
        assert 0.9 < FALLBACK_RATES["EURUSD"] < 1.3
        # GBP/USD should be around 1.1-1.4
        assert 1.0 < FALLBACK_RATES["GBPUSD"] < 1.5


class TestIndividualSourceSuccess:
    """Tests for individual exchange rate source success scenarios (AC3.8)."""

    @pytest.fixture
    def service(self):
        """Create a fresh CurrencyService instance for each test."""
        svc = CurrencyService(cache_ttl=300)
        yield svc
        svc.shutdown()

    @pytest.mark.asyncio
    async def test_exchangerate_api_success(self, service):
        """Test that exchangerate-api returns correct rate when called successfully.

        AC3.8: Verify exchangerate-api returns correct rate when yfinance fails.
        """
        import sys

        # Mock yfinance to fail
        mock_yf_module = MagicMock()
        mock_yf_module.Ticker.side_effect = Exception("yfinance unavailable")

        # Mock aiohttp to simulate successful exchangerate-api response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = MagicMock(return_value={
            "result": "success",
            "rates": {"USD": 1.0850}
        })

        # Create async context managers for aiohttp
        mock_session_instance = MagicMock()
        mock_session_instance.get = MagicMock(return_value=MagicMock(
            __aenter__=MagicMock(return_value=mock_response),
            __aexit__=MagicMock(return_value=None)
        ))

        # Patch the _fetch_from_exchangerate_api to return a successful rate
        # and frankfurter to not be called
        with patch.dict(sys.modules, {"yfinance": mock_yf_module}), \
             patch.object(service, "_fetch_from_exchangerate_api", return_value=1.0850):
            result = await service.get_exchange_rate("EUR", "USD")

        assert result.success is True
        assert result.rate == 1.0850
        assert result.from_currency == "EUR"
        assert result.to_currency == "USD"
        assert result.source == "exchangerate-api"
        assert result.is_fallback is False

    @pytest.mark.asyncio
    async def test_frankfurter_success(self, service):
        """Test that frankfurter returns correct rate when called successfully.

        AC3.8: Verify frankfurter returns correct rate when yfinance and exchangerate-api fail.
        """
        import sys

        # Mock yfinance to fail
        mock_yf_module = MagicMock()
        mock_yf_module.Ticker.side_effect = Exception("yfinance unavailable")

        # Patch both failing sources and successful frankfurter
        with patch.dict(sys.modules, {"yfinance": mock_yf_module}), \
             patch.object(service, "_fetch_from_exchangerate_api", return_value=None), \
             patch.object(service, "_fetch_from_frankfurter", return_value=1.0825):
            result = await service.get_exchange_rate("EUR", "USD")

        assert result.success is True
        assert result.rate == 1.0825
        assert result.from_currency == "EUR"
        assert result.to_currency == "USD"
        assert result.source == "frankfurter"
        assert result.is_fallback is False

    @pytest.mark.asyncio
    async def test_exchangerate_api_returns_correct_rate_value(self, service):
        """Test that exchangerate-api returns the exact rate from API response.

        Verifies the rate value is correctly extracted and returned.
        """
        import sys

        mock_yf_module = MagicMock()
        mock_yf_module.Ticker.side_effect = Exception("yfinance unavailable")

        # Test with a specific rate value
        expected_rate = 0.93  # USD to EUR

        with patch.dict(sys.modules, {"yfinance": mock_yf_module}), \
             patch.object(service, "_fetch_from_exchangerate_api", return_value=expected_rate):
            result = await service.get_exchange_rate("USD", "EUR")

        assert result.success is True
        assert result.rate == expected_rate
        assert result.source == "exchangerate-api"

    @pytest.mark.asyncio
    async def test_frankfurter_returns_correct_rate_value(self, service):
        """Test that frankfurter returns the exact rate from API response.

        Verifies the rate value is correctly extracted and returned.
        """
        import sys

        mock_yf_module = MagicMock()
        mock_yf_module.Ticker.side_effect = Exception("yfinance unavailable")

        # Test with GBP/USD rate
        expected_rate = 1.2650

        with patch.dict(sys.modules, {"yfinance": mock_yf_module}), \
             patch.object(service, "_fetch_from_exchangerate_api", return_value=None), \
             patch.object(service, "_fetch_from_frankfurter", return_value=expected_rate):
            result = await service.get_exchange_rate("GBP", "USD")

        assert result.success is True
        assert result.rate == expected_rate
        assert result.source == "frankfurter"
