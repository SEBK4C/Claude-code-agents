"""
P&L Service for the Telegram Trade Journal Bot.

This module provides profit and loss calculation functionality,
including currency conversion for instruments traded in non-base currencies.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from config import BASE_CURRENCY, get_instrument_config, get_logger
from services.currency_service import get_currency_service

logger = get_logger(__name__)


@dataclass
class PnLResult:
    """
    Result of a P&L calculation.

    Attributes:
        pnl_native: P&L in the instrument's native currency.
        pnl_base: P&L converted to base currency (USD).
        native_currency: The instrument's native currency code.
        base_currency: The base currency code (USD).
        exchange_rate: Exchange rate used for conversion.
        points: Price movement in points.
        point_value: Value per point for the instrument.
        is_fallback_rate: Whether a fallback exchange rate was used.
        rate_source: The data source that provided the exchange rate.
        error: Error message if calculation failed.
    """

    pnl_native: float
    pnl_base: float
    native_currency: str
    base_currency: str
    exchange_rate: float
    points: float
    point_value: float
    is_fallback_rate: bool = False
    rate_source: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Check if the calculation was successful."""
        return self.error is None


@dataclass
class RiskRewardResult:
    """
    Result of a risk/reward calculation.

    Attributes:
        risk_points: Distance from entry to stop loss in points.
        reward_points: Distance from entry to take profit in points.
        risk_reward_ratio: Reward divided by risk (e.g., 2.0 means 2:1 R:R).
        error: Error message if calculation failed.
    """

    risk_points: float
    reward_points: float
    risk_reward_ratio: float
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Check if the calculation was successful."""
        return self.error is None


@dataclass
class PositionSizeResult:
    """
    Result of a position size calculation.

    Attributes:
        lot_size: Recommended lot size.
        risk_amount: Dollar amount at risk.
        risk_percent: Risk as percentage of account.
        sl_distance: Stop loss distance in price points.
        error: Error message if calculation failed.
    """

    lot_size: float
    risk_amount: float
    risk_percent: float
    sl_distance: float
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Check if the calculation was successful."""
        return self.error is None


class PnLService:
    """
    Service for calculating profit and loss with currency conversion.

    Handles P&L calculations for instruments traded in different currencies,
    converting results to the base currency (USD) using real-time exchange rates.

    Example:
        >>> service = PnLService()
        >>> result = await service.calculate_pnl(
        ...     instrument="DAX",
        ...     direction="LONG",
        ...     entry_price=18000.0,
        ...     exit_price=18050.0,
        ...     lot_size=1.0
        ... )
        >>> print(f"P&L: {result.pnl_base} USD")
    """

    def __init__(self):
        """Initialize the P&L service."""
        logger.info("PnLService initialized")

    async def calculate_pnl(
        self,
        instrument: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        lot_size: float,
    ) -> PnLResult:
        """
        Calculate realized P&L for a closed trade.

        Args:
            instrument: The trading instrument (e.g., "DAX", "NASDAQ").
            direction: Trade direction ("LONG" or "SHORT").
            entry_price: Entry price of the trade.
            exit_price: Exit price of the trade.
            lot_size: Position size in lots.

        Returns:
            PnLResult: The P&L calculation result with native and base currency values.
        """
        try:
            # Get instrument configuration
            config = get_instrument_config(instrument)
            native_currency = config.get("currency", "USD")
            point_value = config.get("point_value", 1.0)

            # Calculate points gained/lost
            direction_upper = direction.upper()
            if direction_upper == "LONG":
                points = exit_price - entry_price
            elif direction_upper == "SHORT":
                points = entry_price - exit_price
            else:
                return PnLResult(
                    pnl_native=0.0,
                    pnl_base=0.0,
                    native_currency=native_currency,
                    base_currency=BASE_CURRENCY,
                    exchange_rate=1.0,
                    points=0.0,
                    point_value=point_value,
                    error=f"Invalid direction: {direction}. Use 'LONG' or 'SHORT'.",
                )

            # Calculate P&L in native currency
            pnl_native = points * point_value * lot_size

            # Convert to base currency if needed
            exchange_rate = 1.0
            is_fallback = False
            rate_source: Optional[str] = None

            if native_currency.upper() != BASE_CURRENCY.upper():
                currency_service = get_currency_service()
                rate_result = await currency_service.get_exchange_rate(
                    native_currency, BASE_CURRENCY
                )

                if rate_result.success:
                    exchange_rate = rate_result.rate
                    is_fallback = rate_result.is_fallback
                    rate_source = rate_result.source
                    logger.info(
                        "Currency conversion rate obtained",
                        from_currency=native_currency,
                        to_currency=BASE_CURRENCY,
                        rate=exchange_rate,
                        source=rate_source,
                        is_fallback=is_fallback,
                    )
                else:
                    # Use fallback rate of 1.0 if conversion fails
                    rate_source = "conversion_failed"
                    logger.warning(
                        "Currency conversion failed, using 1:1 rate",
                        from_currency=native_currency,
                        to_currency=BASE_CURRENCY,
                        error=rate_result.error,
                    )
            else:
                rate_source = "same_currency"

            pnl_base = pnl_native * exchange_rate

            logger.debug(
                "P&L calculated",
                instrument=instrument,
                direction=direction_upper,
                points=points,
                pnl_native=pnl_native,
                pnl_base=pnl_base,
                native_currency=native_currency,
                exchange_rate=exchange_rate,
                rate_source=rate_source,
            )

            return PnLResult(
                pnl_native=round(pnl_native, 2),
                pnl_base=round(pnl_base, 2),
                native_currency=native_currency,
                base_currency=BASE_CURRENCY,
                exchange_rate=round(exchange_rate, 6),
                points=round(points, 2),
                point_value=point_value,
                is_fallback_rate=is_fallback,
                rate_source=rate_source,
            )

        except Exception as e:
            logger.error(
                "P&L calculation failed",
                instrument=instrument,
                direction=direction,
                error=str(e),
            )
            return PnLResult(
                pnl_native=0.0,
                pnl_base=0.0,
                native_currency="USD",
                base_currency=BASE_CURRENCY,
                exchange_rate=1.0,
                points=0.0,
                point_value=1.0,
                error=f"P&L calculation failed: {str(e)}",
            )

    async def calculate_unrealized_pnl(
        self,
        instrument: str,
        direction: str,
        entry_price: float,
        lot_size: float,
        current_price: float,
    ) -> PnLResult:
        """
        Calculate unrealized P&L for an open position.

        This is equivalent to calculate_pnl but uses the current market price
        instead of an exit price.

        Args:
            instrument: The trading instrument (e.g., "DAX", "NASDAQ").
            direction: Trade direction ("LONG" or "SHORT").
            entry_price: Entry price of the trade.
            lot_size: Position size in lots.
            current_price: Current market price.

        Returns:
            PnLResult: The unrealized P&L calculation result.
        """
        return await self.calculate_pnl(
            instrument=instrument,
            direction=direction,
            entry_price=entry_price,
            exit_price=current_price,
            lot_size=lot_size,
        )

    def calculate_risk_reward(
        self,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        direction: str,
    ) -> RiskRewardResult:
        """
        Calculate risk/reward ratio for a trade setup.

        Args:
            entry_price: Planned entry price.
            sl_price: Stop loss price.
            tp_price: Take profit price.
            direction: Trade direction ("LONG" or "SHORT").

        Returns:
            RiskRewardResult: The risk/reward calculation result.
        """
        try:
            direction_upper = direction.upper()

            if direction_upper == "LONG":
                # For long: SL below entry, TP above entry
                risk_points = entry_price - sl_price
                reward_points = tp_price - entry_price
            elif direction_upper == "SHORT":
                # For short: SL above entry, TP below entry
                risk_points = sl_price - entry_price
                reward_points = entry_price - tp_price
            else:
                return RiskRewardResult(
                    risk_points=0.0,
                    reward_points=0.0,
                    risk_reward_ratio=0.0,
                    error=f"Invalid direction: {direction}. Use 'LONG' or 'SHORT'.",
                )

            # Validate risk is positive
            if risk_points <= 0:
                return RiskRewardResult(
                    risk_points=risk_points,
                    reward_points=reward_points,
                    risk_reward_ratio=0.0,
                    error="Invalid stop loss placement: risk must be positive.",
                )

            # Validate reward is positive
            if reward_points <= 0:
                return RiskRewardResult(
                    risk_points=risk_points,
                    reward_points=reward_points,
                    risk_reward_ratio=0.0,
                    error="Invalid take profit placement: reward must be positive.",
                )

            risk_reward_ratio = reward_points / risk_points

            logger.debug(
                "Risk/reward calculated",
                direction=direction_upper,
                risk_points=risk_points,
                reward_points=reward_points,
                risk_reward_ratio=risk_reward_ratio,
            )

            return RiskRewardResult(
                risk_points=round(risk_points, 4),
                reward_points=round(reward_points, 4),
                risk_reward_ratio=round(risk_reward_ratio, 2),
            )

        except Exception as e:
            logger.error("Risk/reward calculation failed", error=str(e))
            return RiskRewardResult(
                risk_points=0.0,
                reward_points=0.0,
                risk_reward_ratio=0.0,
                error=f"Risk/reward calculation failed: {str(e)}",
            )

    async def calculate_position_size(
        self,
        account_balance: float,
        risk_percent: float,
        entry_price: float,
        sl_price: float,
        instrument: str,
    ) -> PositionSizeResult:
        """
        Calculate recommended position size based on risk parameters.

        Args:
            account_balance: Current account balance in base currency (USD).
            risk_percent: Maximum risk as percentage (e.g., 1.0 for 1%).
            entry_price: Planned entry price.
            sl_price: Stop loss price.
            instrument: The trading instrument (e.g., "DAX", "NASDAQ").

        Returns:
            PositionSizeResult: The position size calculation result.
        """
        try:
            # Validate inputs
            if account_balance <= 0:
                return PositionSizeResult(
                    lot_size=0.0,
                    risk_amount=0.0,
                    risk_percent=risk_percent,
                    sl_distance=0.0,
                    error="Account balance must be positive.",
                )

            if risk_percent <= 0 or risk_percent > 100:
                return PositionSizeResult(
                    lot_size=0.0,
                    risk_amount=0.0,
                    risk_percent=risk_percent,
                    sl_distance=0.0,
                    error="Risk percent must be between 0 and 100.",
                )

            # Get instrument configuration
            config = get_instrument_config(instrument)
            native_currency = config.get("currency", "USD")
            point_value = config.get("point_value", 1.0)

            # Calculate stop loss distance
            sl_distance = abs(entry_price - sl_price)
            if sl_distance == 0:
                return PositionSizeResult(
                    lot_size=0.0,
                    risk_amount=0.0,
                    risk_percent=risk_percent,
                    sl_distance=0.0,
                    error="Stop loss distance cannot be zero.",
                )

            # Calculate risk amount in base currency
            risk_amount = account_balance * (risk_percent / 100)

            # Get exchange rate if instrument is in different currency
            exchange_rate = 1.0
            if native_currency.upper() != BASE_CURRENCY.upper():
                currency_service = get_currency_service()
                rate_result = await currency_service.get_exchange_rate(
                    BASE_CURRENCY, native_currency
                )
                if rate_result.success:
                    exchange_rate = rate_result.rate

            # Convert risk amount to native currency
            risk_amount_native = risk_amount * exchange_rate

            # Calculate lot size
            # lot_size = risk_amount_native / (sl_distance * point_value)
            value_per_lot_per_point = sl_distance * point_value
            if value_per_lot_per_point == 0:
                return PositionSizeResult(
                    lot_size=0.0,
                    risk_amount=risk_amount,
                    risk_percent=risk_percent,
                    sl_distance=sl_distance,
                    error="Cannot calculate position size: value per point is zero.",
                )

            lot_size = risk_amount_native / value_per_lot_per_point

            logger.debug(
                "Position size calculated",
                instrument=instrument,
                account_balance=account_balance,
                risk_percent=risk_percent,
                risk_amount=risk_amount,
                sl_distance=sl_distance,
                lot_size=lot_size,
            )

            return PositionSizeResult(
                lot_size=round(lot_size, 2),
                risk_amount=round(risk_amount, 2),
                risk_percent=risk_percent,
                sl_distance=round(sl_distance, 4),
            )

        except Exception as e:
            logger.error("Position size calculation failed", error=str(e))
            return PositionSizeResult(
                lot_size=0.0,
                risk_amount=0.0,
                risk_percent=risk_percent,
                sl_distance=0.0,
                error=f"Position size calculation failed: {str(e)}",
            )


# Module-level singleton instance
_pnl_service: Optional[PnLService] = None


def get_pnl_service() -> PnLService:
    """
    Get or create the global P&L service instance.

    Returns:
        PnLService: The global P&L service singleton.
    """
    global _pnl_service
    if _pnl_service is None:
        _pnl_service = PnLService()
    return _pnl_service


def reset_pnl_service() -> None:
    """
    Reset the global P&L service instance.

    Useful for testing or reconfiguration.
    """
    global _pnl_service
    _pnl_service = None
