"""
Price Service for the Telegram Trade Journal Bot.

This module provides real-time price fetching for financial instruments
using yfinance with in-memory caching.
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import get_logger

logger = get_logger(__name__)

# Symbol mapping from internal names to yfinance symbols
SYMBOL_MAP: dict[str, str] = {
    "DAX": "^GDAXI",
    "NASDAQ": "^IXIC",
    "SP500": "^GSPC",
    "DOW": "^DJI",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "GOLD": "GC=F",
    "OIL": "CL=F",
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
}

# Cache TTL in seconds
DEFAULT_CACHE_TTL = 5


@dataclass
class PriceResult:
    """
    Result of a price fetch operation.

    Attributes:
        price: The current price, or None if unavailable.
        timestamp: The timestamp of the price data, or None if unavailable.
        error: Error message if the fetch failed, or None on success.
    """

    price: Optional[float]
    timestamp: Optional[datetime]
    error: Optional[str]

    @property
    def success(self) -> bool:
        """Check if the price fetch was successful."""
        return self.price is not None and self.error is None


@dataclass
class CacheEntry:
    """
    Cache entry for price data.

    Attributes:
        result: The cached PriceResult.
        cached_at: Unix timestamp when the entry was cached.
    """

    result: PriceResult
    cached_at: float


class PriceService:
    """
    Service for fetching real-time prices with caching.

    Uses yfinance to fetch current prices and maintains an in-memory
    cache with configurable TTL to minimize API calls.

    Attributes:
        cache_ttl: Time-to-live for cache entries in seconds.
    """

    def __init__(self, cache_ttl: int = DEFAULT_CACHE_TTL):
        """
        Initialize the price service.

        Args:
            cache_ttl: Cache time-to-live in seconds.
        """
        self._cache: dict[str, CacheEntry] = {}
        self._cache_lock = threading.Lock()
        self._cache_ttl = cache_ttl
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="price_fetch")

        logger.info("PriceService initialized", cache_ttl=cache_ttl)

    def _get_yfinance_symbol(self, symbol: str) -> str:
        """
        Convert internal symbol to yfinance symbol.

        Args:
            symbol: Internal symbol name.

        Returns:
            str: The yfinance-compatible symbol.
        """
        symbol_upper = symbol.upper().strip()
        return SYMBOL_MAP.get(symbol_upper, symbol_upper)

    def _fetch_price_sync(self, symbol: str) -> PriceResult:
        """
        Synchronously fetch price using yfinance.

        This method runs in a thread pool to avoid blocking the event loop.

        Args:
            symbol: The symbol to fetch (already converted to yfinance format).

        Returns:
            PriceResult: The price result.
        """
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)

            # Try fast_info first (faster, less data)
            fast_info = ticker.fast_info

            price: Optional[float] = None
            if hasattr(fast_info, "last_price") and fast_info.last_price is not None:
                price = float(fast_info.last_price)
            elif hasattr(fast_info, "previous_close") and fast_info.previous_close is not None:
                price = float(fast_info.previous_close)

            if price is not None:
                return PriceResult(
                    price=price,
                    timestamp=datetime.utcnow(),
                    error=None,
                )

            # Fallback to history if fast_info doesn't have price
            hist = ticker.history(period="1d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                return PriceResult(
                    price=price,
                    timestamp=datetime.utcnow(),
                    error=None,
                )

            return PriceResult(
                price=None,
                timestamp=None,
                error=f"No price data available for {symbol}",
            )

        except ImportError:
            return PriceResult(
                price=None,
                timestamp=None,
                error="yfinance package not installed",
            )
        except Exception as e:
            error_msg = str(e)
            # Handle common yfinance errors
            if "No data found" in error_msg or "404" in error_msg:
                return PriceResult(
                    price=None,
                    timestamp=None,
                    error=f"Symbol not found: {symbol}",
                )
            return PriceResult(
                price=None,
                timestamp=None,
                error=f"Failed to fetch price: {error_msg}",
            )

    def _get_from_cache(self, symbol: str) -> Optional[PriceResult]:
        """
        Get a price from cache if valid.

        Args:
            symbol: The symbol to look up.

        Returns:
            Optional[PriceResult]: The cached result if valid, None otherwise.
        """
        with self._cache_lock:
            entry = self._cache.get(symbol)
            if entry is None:
                return None

            # Check if entry is still valid
            age = time.time() - entry.cached_at
            if age > self._cache_ttl:
                # Entry expired, remove it
                del self._cache[symbol]
                return None

            return entry.result

    def _update_cache(self, symbol: str, result: PriceResult) -> None:
        """
        Update the cache with a new price result.

        Args:
            symbol: The symbol to cache.
            result: The price result to cache.
        """
        # Only cache successful results
        if result.success:
            with self._cache_lock:
                self._cache[symbol] = CacheEntry(
                    result=result,
                    cached_at=time.time(),
                )

    async def get_current_price(self, symbol: str) -> PriceResult:
        """
        Get the current price for a symbol.

        Checks the cache first, then fetches from yfinance if needed.
        Runs the fetch in a thread pool to avoid blocking.

        Args:
            symbol: The symbol to fetch (internal or yfinance format).

        Returns:
            PriceResult: The price result with price, timestamp, and any error.
        """
        # Convert to yfinance symbol
        yf_symbol = self._get_yfinance_symbol(symbol)

        # Check cache first
        cached = self._get_from_cache(yf_symbol)
        if cached is not None:
            logger.debug("Price cache hit", symbol=symbol, yf_symbol=yf_symbol)
            return cached

        # Fetch price in thread pool
        logger.debug("Fetching price", symbol=symbol, yf_symbol=yf_symbol)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self._executor,
            self._fetch_price_sync,
            yf_symbol,
        )

        # Update cache
        self._update_cache(yf_symbol, result)

        if result.error:
            logger.warning("Price fetch failed", symbol=symbol, error=result.error)
        else:
            logger.debug("Price fetched", symbol=symbol, price=result.price)

        return result

    def clear_cache(self) -> None:
        """Clear the entire price cache."""
        with self._cache_lock:
            self._cache.clear()
        logger.info("Price cache cleared")

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
        logger.info("PriceService shutdown complete")


# Module-level singleton instance
_price_service: Optional[PriceService] = None


def get_price_service() -> PriceService:
    """
    Get or create the global price service instance.

    Returns:
        PriceService: The global price service singleton.
    """
    global _price_service
    if _price_service is None:
        _price_service = PriceService()
    return _price_service


def reset_price_service() -> None:
    """
    Reset the global price service instance.

    Useful for testing or reconfiguration.
    """
    global _price_service
    if _price_service is not None:
        _price_service.shutdown()
    _price_service = None
