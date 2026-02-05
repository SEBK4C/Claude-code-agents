"""
Currency Service for the Telegram Trade Journal Bot.

This module provides currency conversion functionality for P&L calculations,
using multiple data sources with fallback chain for real-time exchange rates.

Fallback chain order:
1. yfinance (primary - via ThreadPoolExecutor)
2. exchangerate-api.com (free tier)
3. frankfurter.app (free, no API key required)
4. static fallback rates (last resort)
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

import aiohttp

from config import EXCHANGE_RATE_CACHE_TTL, get_logger

logger = get_logger(__name__)


class RateSource(Enum):
    """Enumeration of exchange rate data sources."""

    YFINANCE = "yfinance"
    EXCHANGERATE_API = "exchangerate-api"
    FRANKFURTER = "frankfurter"
    FALLBACK = "static_fallback"
    SAME_CURRENCY = "same_currency"

# Fallback exchange rates when API is unavailable
FALLBACK_RATES: dict[str, float] = {
    "EURUSD": 1.08,  # EUR to USD
    "GBPUSD": 1.26,  # GBP to USD
    "USDJPY": 150.0,  # USD to JPY
    "USDCHF": 0.88,  # USD to CHF
    "AUDUSD": 0.65,  # AUD to USD
    "USDCAD": 1.36,  # USD to CAD
}


@dataclass
class ExchangeRateResult:
    """
    Result of an exchange rate fetch operation.

    Attributes:
        rate: The exchange rate, or None if unavailable.
        from_currency: The source currency code.
        to_currency: The target currency code.
        is_fallback: Whether the rate is from fallback data.
        source: The data source that provided the rate.
        error: Error message if the fetch failed, or None on success.
    """

    rate: Optional[float]
    from_currency: str
    to_currency: str
    is_fallback: bool = False
    source: str = RateSource.YFINANCE.value
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Check if the rate fetch was successful."""
        return self.rate is not None


@dataclass
class CacheEntry:
    """
    Cache entry for exchange rate data.

    Attributes:
        result: The cached ExchangeRateResult.
        cached_at: Unix timestamp when the entry was cached.
    """

    result: ExchangeRateResult
    cached_at: float


class CurrencyService:
    """
    Service for currency conversion with caching.

    Uses yfinance to fetch current exchange rates and maintains an in-memory
    cache with configurable TTL to minimize API calls.

    Attributes:
        cache_ttl: Time-to-live for cache entries in seconds.
    """

    def __init__(self, cache_ttl: int = EXCHANGE_RATE_CACHE_TTL):
        """
        Initialize the currency service.

        Args:
            cache_ttl: Cache time-to-live in seconds. Defaults to 5 minutes.
        """
        self._cache: dict[str, CacheEntry] = {}
        self._cache_lock = threading.Lock()
        self._cache_ttl = cache_ttl
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="currency_fetch")

        logger.info("CurrencyService initialized", cache_ttl=cache_ttl)

    def _get_cache_key(self, from_currency: str, to_currency: str) -> str:
        """
        Generate a cache key for a currency pair.

        Args:
            from_currency: Source currency code.
            to_currency: Target currency code.

        Returns:
            str: The cache key.
        """
        return f"{from_currency.upper()}{to_currency.upper()}"

    def _get_yfinance_symbol(self, from_currency: str, to_currency: str) -> str:
        """
        Convert currency pair to yfinance symbol format.

        Args:
            from_currency: Source currency code.
            to_currency: Target currency code.

        Returns:
            str: The yfinance-compatible symbol (e.g., "EURUSD=X").
        """
        return f"{from_currency.upper()}{to_currency.upper()}=X"

    def _get_fallback_rate(self, from_currency: str, to_currency: str) -> Optional[float]:
        """
        Get a fallback exchange rate for a currency pair.

        Args:
            from_currency: Source currency code.
            to_currency: Target currency code.

        Returns:
            Optional[float]: The fallback rate, or None if not available.
        """
        from_upper = from_currency.upper()
        to_upper = to_currency.upper()

        # Same currency - rate is 1.0
        if from_upper == to_upper:
            return 1.0

        # Direct lookup
        direct_key = f"{from_upper}{to_upper}"
        if direct_key in FALLBACK_RATES:
            return FALLBACK_RATES[direct_key]

        # Inverse lookup
        inverse_key = f"{to_upper}{from_upper}"
        if inverse_key in FALLBACK_RATES:
            return 1.0 / FALLBACK_RATES[inverse_key]

        return None

    def _fetch_rate_yfinance_sync(self, from_currency: str, to_currency: str) -> Optional[float]:
        """
        Synchronously fetch exchange rate using yfinance.

        This method runs in a thread pool to avoid blocking the event loop.

        Args:
            from_currency: Source currency code.
            to_currency: Target currency code.

        Returns:
            Optional[float]: The exchange rate, or None if fetch failed.
        """
        try:
            import yfinance as yf

            symbol = self._get_yfinance_symbol(from_currency, to_currency)
            ticker = yf.Ticker(symbol)

            rate: Optional[float] = None

            # Try fast_info first (faster, less data)
            fast_info = ticker.fast_info
            if hasattr(fast_info, "last_price") and fast_info.last_price is not None:
                rate = float(fast_info.last_price)
            elif hasattr(fast_info, "previous_close") and fast_info.previous_close is not None:
                rate = float(fast_info.previous_close)

            if rate is not None and rate > 0:
                return rate

            # Fallback to history if fast_info doesn't have rate
            hist = ticker.history(period="1d")
            if not hist.empty:
                rate = float(hist["Close"].iloc[-1])
                if rate > 0:
                    return rate

            return None

        except ImportError:
            logger.warning("yfinance package not installed")
            return None
        except Exception as e:
            logger.warning(
                "yfinance fetch failed",
                from_currency=from_currency,
                to_currency=to_currency,
                error=str(e),
            )
            return None

    async def _fetch_from_exchangerate_api(
        self, from_currency: str, to_currency: str
    ) -> Optional[float]:
        """
        Fetch exchange rate from exchangerate-api.com (free tier).

        Endpoint: https://open.er-api.com/v6/latest/{BASE_CURRENCY}

        Args:
            from_currency: Source currency code.
            to_currency: Target currency code.

        Returns:
            Optional[float]: The exchange rate, or None if fetch failed.
        """
        url = f"https://open.er-api.com/v6/latest/{from_currency.upper()}"

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("result") == "success":
                            rates = data.get("rates", {})
                            rate = rates.get(to_currency.upper())
                            if rate is not None and rate > 0:
                                logger.debug(
                                    "exchangerate-api fetch successful",
                                    from_currency=from_currency,
                                    to_currency=to_currency,
                                    rate=rate,
                                )
                                return float(rate)
                    logger.warning(
                        "exchangerate-api returned non-success status",
                        status=resp.status,
                        from_currency=from_currency,
                        to_currency=to_currency,
                    )
                    return None
        except asyncio.TimeoutError:
            logger.warning(
                "exchangerate-api timeout",
                from_currency=from_currency,
                to_currency=to_currency,
            )
            return None
        except aiohttp.ClientError as e:
            logger.warning(
                "exchangerate-api client error",
                from_currency=from_currency,
                to_currency=to_currency,
                error=str(e),
            )
            return None
        except Exception as e:
            logger.warning(
                "exchangerate-api fetch failed",
                from_currency=from_currency,
                to_currency=to_currency,
                error=str(e),
            )
            return None

    async def _fetch_from_frankfurter(
        self, from_currency: str, to_currency: str
    ) -> Optional[float]:
        """
        Fetch exchange rate from frankfurter.app (free, no API key required).

        Endpoint: https://api.frankfurter.dev/v1/latest?base={BASE}&symbols={TARGET}

        Args:
            from_currency: Source currency code.
            to_currency: Target currency code.

        Returns:
            Optional[float]: The exchange rate, or None if fetch failed.
        """
        url = f"https://api.frankfurter.dev/v1/latest?base={from_currency.upper()}&symbols={to_currency.upper()}"

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        rates = data.get("rates", {})
                        rate = rates.get(to_currency.upper())
                        if rate is not None and rate > 0:
                            logger.debug(
                                "frankfurter fetch successful",
                                from_currency=from_currency,
                                to_currency=to_currency,
                                rate=rate,
                            )
                            return float(rate)
                    logger.warning(
                        "frankfurter returned non-success status",
                        status=resp.status,
                        from_currency=from_currency,
                        to_currency=to_currency,
                    )
                    return None
        except asyncio.TimeoutError:
            logger.warning(
                "frankfurter timeout",
                from_currency=from_currency,
                to_currency=to_currency,
            )
            return None
        except aiohttp.ClientError as e:
            logger.warning(
                "frankfurter client error",
                from_currency=from_currency,
                to_currency=to_currency,
                error=str(e),
            )
            return None
        except Exception as e:
            logger.warning(
                "frankfurter fetch failed",
                from_currency=from_currency,
                to_currency=to_currency,
                error=str(e),
            )
            return None

    def _get_from_cache(self, cache_key: str) -> Optional[ExchangeRateResult]:
        """
        Get an exchange rate from cache if valid.

        Args:
            cache_key: The cache key to look up.

        Returns:
            Optional[ExchangeRateResult]: The cached result if valid, None otherwise.
        """
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry is None:
                return None

            # Check if entry is still valid
            age = time.time() - entry.cached_at
            if age > self._cache_ttl:
                # Entry expired, remove it
                del self._cache[cache_key]
                return None

            return entry.result

    def _update_cache(self, cache_key: str, result: ExchangeRateResult) -> None:
        """
        Update the cache with a new exchange rate result.

        Args:
            cache_key: The cache key.
            result: The exchange rate result to cache.
        """
        # Only cache successful results
        if result.success:
            with self._cache_lock:
                self._cache[cache_key] = CacheEntry(
                    result=result,
                    cached_at=time.time(),
                )

    async def get_exchange_rate(
        self, from_currency: str, to_currency: str
    ) -> ExchangeRateResult:
        """
        Get the exchange rate between two currencies.

        Uses a fallback chain for maximum reliability:
        1. yfinance (primary - via ThreadPoolExecutor)
        2. exchangerate-api.com (free tier)
        3. frankfurter.app (free, no API key required)
        4. static fallback rates (last resort)

        Checks the cache first, then fetches from sources if needed.

        Args:
            from_currency: Source currency code (e.g., "EUR").
            to_currency: Target currency code (e.g., "USD").

        Returns:
            ExchangeRateResult: The exchange rate result with source information.
        """
        from_upper = from_currency.upper()
        to_upper = to_currency.upper()

        # Same currency - no conversion needed
        if from_upper == to_upper:
            return ExchangeRateResult(
                rate=1.0,
                from_currency=from_upper,
                to_currency=to_upper,
                is_fallback=False,
                source=RateSource.SAME_CURRENCY.value,
                error=None,
            )

        cache_key = self._get_cache_key(from_currency, to_currency)

        # Check cache first
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            logger.debug(
                "Exchange rate cache hit",
                from_currency=from_upper,
                to_currency=to_upper,
                source=cached.source,
            )
            return cached

        logger.debug(
            "Fetching exchange rate via fallback chain",
            from_currency=from_upper,
            to_currency=to_upper,
        )

        # Fallback chain: yfinance -> exchangerate-api -> frankfurter -> static fallback
        rate: Optional[float] = None
        source: RateSource = RateSource.FALLBACK

        # 1. Try yfinance (primary source, via thread pool)
        loop = asyncio.get_event_loop()
        rate = await loop.run_in_executor(
            self._executor,
            self._fetch_rate_yfinance_sync,
            from_upper,
            to_upper,
        )
        if rate is not None:
            source = RateSource.YFINANCE
            logger.info(
                "Exchange rate from yfinance",
                from_currency=from_upper,
                to_currency=to_upper,
                rate=rate,
            )
        else:
            # 2. Try exchangerate-api.com
            rate = await self._fetch_from_exchangerate_api(from_upper, to_upper)
            if rate is not None:
                source = RateSource.EXCHANGERATE_API
                logger.info(
                    "Exchange rate from exchangerate-api",
                    from_currency=from_upper,
                    to_currency=to_upper,
                    rate=rate,
                )
            else:
                # 3. Try frankfurter.app
                rate = await self._fetch_from_frankfurter(from_upper, to_upper)
                if rate is not None:
                    source = RateSource.FRANKFURTER
                    logger.info(
                        "Exchange rate from frankfurter",
                        from_currency=from_upper,
                        to_currency=to_upper,
                        rate=rate,
                    )
                else:
                    # 4. Use static fallback
                    rate = self._get_fallback_rate(from_upper, to_upper)
                    if rate is not None:
                        source = RateSource.FALLBACK
                        logger.warning(
                            "Using static fallback rate - all API sources failed",
                            from_currency=from_upper,
                            to_currency=to_upper,
                            fallback_rate=rate,
                        )

        # Build result
        if rate is not None:
            result = ExchangeRateResult(
                rate=rate,
                from_currency=from_upper,
                to_currency=to_upper,
                is_fallback=(source == RateSource.FALLBACK),
                source=source.value,
                error=None,
            )
        else:
            result = ExchangeRateResult(
                rate=None,
                from_currency=from_upper,
                to_currency=to_upper,
                is_fallback=False,
                source="none",
                error=f"No exchange rate data available for {from_upper}/{to_upper} from any source",
            )

        # Update cache
        self._update_cache(cache_key, result)

        if result.error:
            logger.warning(
                "Exchange rate fetch failed from all sources",
                from_currency=from_upper,
                to_currency=to_upper,
                error=result.error,
            )
        else:
            logger.debug(
                "Exchange rate fetched successfully",
                from_currency=from_upper,
                to_currency=to_upper,
                rate=result.rate,
                source=result.source,
                is_fallback=result.is_fallback,
            )

        return result

    async def convert(
        self, amount: Decimal, from_currency: str, to_currency: str
    ) -> tuple[Optional[Decimal], Optional[str]]:
        """
        Convert an amount from one currency to another.

        Args:
            amount: The amount to convert.
            from_currency: Source currency code.
            to_currency: Target currency code.

        Returns:
            tuple: (converted_amount, error_message).
                   converted_amount is None if conversion failed.
                   error_message is None if conversion succeeded.
        """
        # Same currency - no conversion needed
        if from_currency.upper() == to_currency.upper():
            return amount, None

        result = await self.get_exchange_rate(from_currency, to_currency)

        if not result.success:
            return None, result.error

        converted = amount * Decimal(str(result.rate))
        return converted, None

    def clear_cache(self) -> None:
        """Clear the entire exchange rate cache."""
        with self._cache_lock:
            self._cache.clear()
        logger.info("Exchange rate cache cleared")

    def get_cache_stats(self) -> dict[str, int]:
        """
        Get cache statistics.

        Returns:
            dict: Cache statistics including size and valid entries.
        """
        with self._cache_lock:
            current_time = time.time()
            valid_entries = sum(
                1 for entry in self._cache.values()
                if (current_time - entry.cached_at) <= self._cache_ttl
            )
            return {
                "total_entries": len(self._cache),
                "valid_entries": valid_entries,
            }

    def shutdown(self) -> None:
        """Shutdown the thread pool executor."""
        self._executor.shutdown(wait=False)
        logger.info("CurrencyService shutdown complete")


# Module-level singleton instance
_currency_service: Optional[CurrencyService] = None


def get_currency_service() -> CurrencyService:
    """
    Get or create the global currency service instance.

    Returns:
        CurrencyService: The global currency service singleton.
    """
    global _currency_service
    if _currency_service is None:
        _currency_service = CurrencyService()
    return _currency_service


def reset_currency_service() -> None:
    """
    Reset the global currency service instance.

    Useful for testing or reconfiguration.
    """
    global _currency_service
    if _currency_service is not None:
        _currency_service.shutdown()
    _currency_service = None
