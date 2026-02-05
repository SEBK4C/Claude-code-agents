"""
Price Monitor Service for the Telegram Trade Journal Bot.

This module provides background price monitoring for open trades,
detecting SL/TP hits and triggering alert callbacks.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Optional, Set

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config import get_config, get_logger
from database.db import get_session
from database.models import Account, Trade, TradeDirection, TradeStatus
from services.price_service import PriceService, get_price_service
from services.pnl_service import get_pnl_service

logger = get_logger(__name__)

# Default check interval in seconds
DEFAULT_CHECK_INTERVAL = 5


class AlertType(str, Enum):
    """Type of price alert."""

    SL_HIT = "sl_hit"
    TP_HIT = "tp_hit"


@dataclass
class PriceAlert:
    """
    Price alert data structure.

    Attributes:
        trade_id: The ID of the trade that triggered the alert.
        instrument: The trading instrument.
        direction: The trade direction.
        entry_price: The entry price of the trade.
        current_price: The current market price.
        alert_type: Type of alert (SL or TP hit).
        sl_price: The stop-loss price.
        tp_price: The take-profit price.
        account_id: The account ID for the trade.
        telegram_id: The Telegram user ID to notify.
        timestamp: When the alert was generated.
        lot_size: The position lot size (for P&L calculation).
        pnl_base: Calculated P&L in base currency (USD).
        pnl_native: Calculated P&L in native currency.
        native_currency: The instrument's native currency.
    """

    trade_id: int
    instrument: str
    direction: str
    entry_price: Decimal
    current_price: float
    alert_type: AlertType
    sl_price: Optional[Decimal]
    tp_price: Optional[Decimal]
    account_id: int
    telegram_id: int
    timestamp: datetime
    lot_size: Optional[Decimal] = None
    pnl_base: Optional[float] = None
    pnl_native: Optional[float] = None
    native_currency: Optional[str] = None


# Type for alert callback functions
AlertCallback = Callable[[PriceAlert], Any]


class PriceMonitor:
    """
    Background service for monitoring prices and alerting on SL/TP hits.

    This service runs a background task that periodically checks prices
    for all unique instruments in open trades and triggers callbacks
    when SL or TP levels are hit.

    Attributes:
        check_interval: Interval between price checks in seconds.
    """

    def __init__(
        self,
        price_service: Optional[PriceService] = None,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
    ):
        """
        Initialize the price monitor.

        Args:
            price_service: Optional PriceService instance. Uses global if not provided.
            check_interval: Interval between price checks in seconds.
        """
        self._price_service = price_service or get_price_service()
        self._check_interval = check_interval
        self._running = False
        self._task: Optional[asyncio.Task[None]] = None
        self._callbacks: list[AlertCallback] = []
        self._alerted_trades: dict[int, Set[AlertType]] = {}  # Track alerts per trade

        logger.info("PriceMonitor initialized", check_interval=check_interval)

    @property
    def is_running(self) -> bool:
        """Check if the monitor is currently running."""
        return self._running

    def register_callback(self, callback: AlertCallback) -> None:
        """
        Register a callback to be called when price alerts are triggered.

        Args:
            callback: A callable that accepts a PriceAlert object.
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)
            logger.info("Alert callback registered", callback_count=len(self._callbacks))

    def unregister_callback(self, callback: AlertCallback) -> None:
        """
        Unregister a previously registered callback.

        Args:
            callback: The callback to remove.
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)
            logger.info("Alert callback unregistered", callback_count=len(self._callbacks))

    def _has_alerted(self, trade_id: int, alert_type: AlertType) -> bool:
        """
        Check if an alert has already been sent for this trade and type.

        Args:
            trade_id: The trade ID.
            alert_type: The type of alert.

        Returns:
            bool: True if already alerted, False otherwise.
        """
        trade_alerts = self._alerted_trades.get(trade_id, set())
        return alert_type in trade_alerts

    def _mark_alerted(self, trade_id: int, alert_type: AlertType) -> None:
        """
        Mark a trade as having received an alert.

        Args:
            trade_id: The trade ID.
            alert_type: The type of alert.
        """
        if trade_id not in self._alerted_trades:
            self._alerted_trades[trade_id] = set()
        self._alerted_trades[trade_id].add(alert_type)

    def clear_trade_alerts(self, trade_id: int) -> None:
        """
        Clear alert history for a trade (e.g., when trade is closed).

        Args:
            trade_id: The trade ID to clear.
        """
        self._alerted_trades.pop(trade_id, None)

    def _check_sl_hit(
        self,
        current_price: float,
        sl_price: Decimal,
        direction: TradeDirection,
    ) -> bool:
        """
        Check if stop-loss has been hit.

        Args:
            current_price: Current market price.
            sl_price: Stop-loss price.
            direction: Trade direction.

        Returns:
            bool: True if SL hit, False otherwise.
        """
        sl_float = float(sl_price)
        if direction == TradeDirection.LONG:
            # For long: SL hit if price <= SL
            return current_price <= sl_float
        else:
            # For short: SL hit if price >= SL
            return current_price >= sl_float

    def _check_tp_hit(
        self,
        current_price: float,
        tp_price: Decimal,
        direction: TradeDirection,
    ) -> bool:
        """
        Check if take-profit has been hit.

        Args:
            current_price: Current market price.
            tp_price: Take-profit price.
            direction: Trade direction.

        Returns:
            bool: True if TP hit, False otherwise.
        """
        tp_float = float(tp_price)
        if direction == TradeDirection.LONG:
            # For long: TP hit if price >= TP
            return current_price >= tp_float
        else:
            # For short: TP hit if price <= TP
            return current_price <= tp_float

    async def _trigger_callbacks(self, alert: PriceAlert) -> None:
        """
        Trigger all registered callbacks with an alert.

        Args:
            alert: The price alert to send to callbacks.
        """
        for callback in self._callbacks:
            try:
                result = callback(alert)
                # If callback is a coroutine, await it
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(
                    "Alert callback failed",
                    error=str(e),
                    trade_id=alert.trade_id,
                    alert_type=alert.alert_type.value,
                )

    async def _calculate_pnl_for_alert(
        self,
        trade: Trade,
        exit_price: float,
    ) -> tuple[Optional[float], Optional[float], Optional[str]]:
        """
        Calculate P&L for a price alert.

        Args:
            trade: The trade that triggered the alert.
            exit_price: The price at which the alert was triggered.

        Returns:
            tuple: (pnl_base, pnl_native, native_currency) or (None, None, None) on error.
        """
        try:
            pnl_service = get_pnl_service()
            result = await pnl_service.calculate_pnl(
                instrument=trade.instrument,
                direction=trade.direction.value,
                entry_price=float(trade.entry_price),
                exit_price=exit_price,
                lot_size=float(trade.lot_size) if trade.lot_size else 1.0,
            )

            if result.success:
                return result.pnl_base, result.pnl_native, result.native_currency

        except Exception as e:
            logger.debug(f"Failed to calculate P&L for alert: {e}")

        return None, None, None

    async def _check_open_trades(self) -> None:
        """
        Check prices for all open trades with SL/TP set.

        Fetches open trades, gets current prices, and triggers alerts
        when SL or TP levels are hit. Includes P&L calculation for alerts.
        """
        try:
            async with get_session() as session:
                # Get all open trades with SL or TP set
                result = await session.execute(
                    select(Trade)
                    .options(selectinload(Trade.account).selectinload(Account.user))
                    .where(Trade.status == TradeStatus.OPEN)
                    .where(
                        (Trade.sl_price.isnot(None)) | (Trade.tp_price.isnot(None))
                    )
                )
                trades = result.scalars().all()

                if not trades:
                    return

                # Group trades by instrument to minimize price fetches
                instruments: dict[str, list[Trade]] = {}
                for trade in trades:
                    if trade.instrument not in instruments:
                        instruments[trade.instrument] = []
                    instruments[trade.instrument].append(trade)

                # Fetch prices for each instrument
                for instrument, instrument_trades in instruments.items():
                    price_result = await self._price_service.get_current_price(instrument)

                    if not price_result.success or price_result.price is None:
                        logger.debug(
                            "Failed to get price for monitoring",
                            instrument=instrument,
                            error=price_result.error,
                        )
                        continue

                    current_price = price_result.price

                    # Check each trade for this instrument
                    for trade in instrument_trades:
                        # Check SL
                        if (
                            trade.sl_price is not None
                            and not self._has_alerted(trade.id, AlertType.SL_HIT)
                            and self._check_sl_hit(current_price, trade.sl_price, trade.direction)
                        ):
                            # Calculate P&L at SL price
                            pnl_base, pnl_native, native_currency = await self._calculate_pnl_for_alert(
                                trade, float(trade.sl_price)
                            )

                            alert = PriceAlert(
                                trade_id=trade.id,
                                instrument=trade.instrument,
                                direction=trade.direction.value,
                                entry_price=trade.entry_price,
                                current_price=current_price,
                                alert_type=AlertType.SL_HIT,
                                sl_price=trade.sl_price,
                                tp_price=trade.tp_price,
                                account_id=trade.account_id,
                                telegram_id=trade.account.user.telegram_id,
                                timestamp=datetime.utcnow(),
                                lot_size=trade.lot_size,
                                pnl_base=pnl_base,
                                pnl_native=pnl_native,
                                native_currency=native_currency,
                            )
                            self._mark_alerted(trade.id, AlertType.SL_HIT)
                            logger.warning(
                                "SL hit detected",
                                trade_id=trade.id,
                                instrument=instrument,
                                sl_price=str(trade.sl_price),
                                current_price=current_price,
                                pnl_base=pnl_base,
                            )
                            await self._trigger_callbacks(alert)

                        # Check TP
                        if (
                            trade.tp_price is not None
                            and not self._has_alerted(trade.id, AlertType.TP_HIT)
                            and self._check_tp_hit(current_price, trade.tp_price, trade.direction)
                        ):
                            # Calculate P&L at TP price
                            pnl_base, pnl_native, native_currency = await self._calculate_pnl_for_alert(
                                trade, float(trade.tp_price)
                            )

                            alert = PriceAlert(
                                trade_id=trade.id,
                                instrument=trade.instrument,
                                direction=trade.direction.value,
                                entry_price=trade.entry_price,
                                current_price=current_price,
                                alert_type=AlertType.TP_HIT,
                                sl_price=trade.sl_price,
                                tp_price=trade.tp_price,
                                account_id=trade.account_id,
                                telegram_id=trade.account.user.telegram_id,
                                timestamp=datetime.utcnow(),
                                lot_size=trade.lot_size,
                                pnl_base=pnl_base,
                                pnl_native=pnl_native,
                                native_currency=native_currency,
                            )
                            self._mark_alerted(trade.id, AlertType.TP_HIT)
                            logger.info(
                                "TP hit detected",
                                trade_id=trade.id,
                                instrument=instrument,
                                tp_price=str(trade.tp_price),
                                current_price=current_price,
                                pnl_base=pnl_base,
                            )
                            await self._trigger_callbacks(alert)

        except Exception as e:
            logger.error("Error checking open trades", error=str(e))

    async def _monitor_loop(self) -> None:
        """
        Main monitoring loop that runs in the background.

        Continuously checks prices at the configured interval.
        """
        logger.info("Price monitor loop started")

        while self._running:
            try:
                await self._check_open_trades()
            except Exception as e:
                logger.error("Error in monitor loop", error=str(e))

            # Wait for next check
            await asyncio.sleep(self._check_interval)

        logger.info("Price monitor loop stopped")

    async def start(self) -> None:
        """
        Start the price monitoring background task.

        If already running, this is a no-op.
        """
        if self._running:
            logger.warning("Price monitor already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Price monitor started")

    async def stop(self) -> None:
        """
        Stop the price monitoring background task.

        Waits for the current check to complete before stopping.
        """
        if not self._running:
            logger.warning("Price monitor not running")
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("Price monitor stopped")

    def get_stats(self) -> dict[str, Any]:
        """
        Get monitoring statistics.

        Returns:
            dict: Statistics including running state and alert counts.
        """
        return {
            "running": self._running,
            "check_interval": self._check_interval,
            "callback_count": len(self._callbacks),
            "tracked_trades": len(self._alerted_trades),
            "total_alerts_sent": sum(len(alerts) for alerts in self._alerted_trades.values()),
        }


# Module-level singleton instance
_price_monitor: Optional[PriceMonitor] = None


def get_price_monitor() -> PriceMonitor:
    """
    Get or create the global price monitor instance.

    Returns:
        PriceMonitor: The global price monitor singleton.
    """
    global _price_monitor
    if _price_monitor is None:
        _price_monitor = PriceMonitor()
    return _price_monitor


async def shutdown_price_monitor() -> None:
    """
    Shutdown the global price monitor instance.

    Stops the monitoring loop and cleans up resources.
    """
    global _price_monitor
    if _price_monitor is not None:
        await _price_monitor.stop()
        _price_monitor = None


def reset_price_monitor() -> None:
    """
    Reset the global price monitor instance synchronously.

    Useful for testing. Does not properly stop the loop.
    """
    global _price_monitor
    if _price_monitor is not None:
        _price_monitor._running = False
    _price_monitor = None
