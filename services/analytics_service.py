"""
Analytics Service for the Telegram Trade Journal Bot.

This module provides comprehensive trading analytics calculations including:
- Win/loss metrics
- Profit/loss calculations
- Risk metrics (drawdown, profit factor)
- Streak analysis
- Breakdown by instrument, day of week, hour
- Equity curve data
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_logger
from database.db import get_session
from database.models import Account, Trade, TradeStatus, User
from services.pnl_service import get_pnl_service

logger = get_logger(__name__)


@dataclass
class InstrumentBreakdown:
    """Analytics breakdown for a specific instrument."""

    instrument: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Decimal = Decimal("0")
    gross_profit: Decimal = Decimal("0")
    gross_loss: Decimal = Decimal("0")
    net_profit: Decimal = Decimal("0")


@dataclass
class DayOfWeekBreakdown:
    """Analytics breakdown for a specific day of week."""

    day_name: str
    day_number: int  # 0=Monday, 6=Sunday
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Decimal = Decimal("0")
    net_profit: Decimal = Decimal("0")


@dataclass
class HourBreakdown:
    """Analytics breakdown for a specific hour."""

    hour: int  # 0-23
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Decimal = Decimal("0")
    net_profit: Decimal = Decimal("0")


@dataclass
class EquityPoint:
    """A single point on the equity curve."""

    date: date
    cumulative_pnl: Decimal
    trade_count: int


@dataclass
class AnalyticsResult:
    """
    Complete analytics result containing all calculated metrics.

    Attributes:
        user_id: The user ID these analytics are for.
        account_id: The account ID if filtered, None for all accounts.
        start_date: Start of the analysis period.
        end_date: End of the analysis period.

        # Trade counts
        total_trades: Total number of closed trades.
        winning_trades: Number of profitable trades.
        losing_trades: Number of unprofitable trades.
        breakeven_trades: Number of trades with zero P&L.

        # Win/Loss rates
        win_rate: Percentage of winning trades (0-100).
        loss_rate: Percentage of losing trades (0-100).

        # Profit/Loss metrics
        gross_profit: Total profit from winning trades.
        gross_loss: Total loss from losing trades (absolute value).
        net_profit: Net profit (gross_profit - gross_loss).
        profit_factor: Gross profit / gross loss ratio.

        # Average metrics
        average_win: Average profit per winning trade.
        average_loss: Average loss per losing trade.
        average_rr: Average realized risk-reward ratio.
        expectancy: Statistical expectancy per trade.

        # Extremes
        largest_win: Largest single winning trade.
        largest_loss: Largest single losing trade (absolute value).

        # Drawdown
        max_drawdown: Maximum drawdown in absolute terms.
        max_drawdown_percent: Maximum drawdown as percentage of peak.

        # Streaks
        best_streak: Longest winning streak.
        worst_streak: Longest losing streak.
        current_streak: Current streak (positive = wins, negative = losses).

        # Breakdowns
        by_instrument: Analytics broken down by instrument.
        by_day_of_week: Analytics broken down by day of week.
        by_hour: Analytics broken down by hour.

        # Equity curve
        equity_curve: List of (date, cumulative_pnl) points.
    """

    user_id: int
    account_id: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    # Trade counts
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0

    # Win/Loss rates
    win_rate: Decimal = Decimal("0")
    loss_rate: Decimal = Decimal("0")

    # Profit/Loss metrics
    gross_profit: Decimal = Decimal("0")
    gross_loss: Decimal = Decimal("0")
    net_profit: Decimal = Decimal("0")
    profit_factor: Decimal = Decimal("0")

    # Average metrics
    average_win: Decimal = Decimal("0")
    average_loss: Decimal = Decimal("0")
    average_rr: Decimal = Decimal("0")
    expectancy: Decimal = Decimal("0")

    # Extremes
    largest_win: Decimal = Decimal("0")
    largest_loss: Decimal = Decimal("0")

    # Drawdown
    max_drawdown: Decimal = Decimal("0")
    max_drawdown_percent: Decimal = Decimal("0")

    # Streaks
    best_streak: int = 0
    worst_streak: int = 0
    current_streak: int = 0

    # Breakdowns
    by_instrument: list[InstrumentBreakdown] = field(default_factory=list)
    by_day_of_week: list[DayOfWeekBreakdown] = field(default_factory=list)
    by_hour: list[HourBreakdown] = field(default_factory=list)

    # Equity curve
    equity_curve: list[EquityPoint] = field(default_factory=list)


class AnalyticsService:
    """
    Service class for calculating trading analytics.

    Provides comprehensive analytics calculations from trade data including
    performance metrics, risk metrics, and breakdowns by various dimensions.
    """

    def __init__(self) -> None:
        """Initialize the analytics service."""
        logger.info("AnalyticsService initialized")

    async def calculate_analytics(
        self,
        user_id: int,
        account_id: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> AnalyticsResult:
        """
        Calculate comprehensive analytics for a user's trades.

        Args:
            user_id: The internal user ID.
            account_id: Optional account ID to filter by. If None, all accounts.
            start_date: Optional start date for the analysis period.
            end_date: Optional end date for the analysis period.

        Returns:
            AnalyticsResult: Complete analytics results.
        """
        result = AnalyticsResult(
            user_id=user_id,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )

        async with get_session() as session:
            # Get user's account IDs
            if account_id:
                account_ids = [account_id]
            else:
                accounts_result = await session.execute(
                    select(Account.id)
                    .where(Account.user_id == user_id)
                    .where(Account.is_active == True)
                )
                account_ids = [row[0] for row in accounts_result.fetchall()]

            if not account_ids:
                logger.info("No accounts found for analytics", user_id=user_id)
                return result

            # Build query for closed trades
            query = (
                select(Trade)
                .where(Trade.account_id.in_(account_ids))
                .where(Trade.status == TradeStatus.CLOSED)
                .where(Trade.pnl.isnot(None))
            )

            if start_date:
                query = query.where(Trade.closed_at >= datetime.combine(start_date, datetime.min.time()))
            if end_date:
                query = query.where(Trade.closed_at <= datetime.combine(end_date, datetime.max.time()))

            query = query.order_by(Trade.closed_at)

            trades_result = await session.execute(query)
            trades = list(trades_result.scalars().all())

            if not trades:
                logger.info("No closed trades found for analytics", user_id=user_id)
                return result

            # Calculate all metrics
            self._calculate_basic_metrics(result, trades)
            self._calculate_averages(result, trades)
            self._calculate_extremes(result, trades)
            self._calculate_drawdown(result, trades)
            self._calculate_streaks(result, trades)
            self._calculate_instrument_breakdown(result, trades)
            self._calculate_day_of_week_breakdown(result, trades)
            self._calculate_hour_breakdown(result, trades)
            self._calculate_equity_curve(result, trades)

            logger.info(
                "Analytics calculated",
                user_id=user_id,
                account_id=account_id,
                total_trades=result.total_trades,
                win_rate=str(result.win_rate),
                net_profit=str(result.net_profit),
            )

        return result

    def _calculate_basic_metrics(self, result: AnalyticsResult, trades: list[Trade]) -> None:
        """Calculate basic trade count and P&L metrics."""
        result.total_trades = len(trades)

        for trade in trades:
            pnl = trade.pnl or Decimal("0")

            if pnl > 0:
                result.winning_trades += 1
                result.gross_profit += pnl
            elif pnl < 0:
                result.losing_trades += 1
                result.gross_loss += abs(pnl)
            else:
                result.breakeven_trades += 1

        result.net_profit = result.gross_profit - result.gross_loss

        # Win/Loss rates
        if result.total_trades > 0:
            result.win_rate = (Decimal(result.winning_trades) / Decimal(result.total_trades) * 100).quantize(Decimal("0.01"))
            result.loss_rate = (Decimal(result.losing_trades) / Decimal(result.total_trades) * 100).quantize(Decimal("0.01"))

        # Profit factor
        if result.gross_loss > 0:
            result.profit_factor = (result.gross_profit / result.gross_loss).quantize(Decimal("0.01"))
        elif result.gross_profit > 0:
            result.profit_factor = Decimal("999.99")  # Infinite profit factor capped

    def _calculate_averages(self, result: AnalyticsResult, trades: list[Trade]) -> None:
        """Calculate average metrics."""
        if result.winning_trades > 0:
            result.average_win = (result.gross_profit / Decimal(result.winning_trades)).quantize(Decimal("0.01"))

        if result.losing_trades > 0:
            result.average_loss = (result.gross_loss / Decimal(result.losing_trades)).quantize(Decimal("0.01"))

        # Average R:R (realized)
        if result.average_loss > 0:
            result.average_rr = (result.average_win / result.average_loss).quantize(Decimal("0.01"))

        # Expectancy = (Win% * Avg Win) - (Loss% * Avg Loss)
        if result.total_trades > 0:
            win_pct = Decimal(result.winning_trades) / Decimal(result.total_trades)
            loss_pct = Decimal(result.losing_trades) / Decimal(result.total_trades)
            result.expectancy = ((win_pct * result.average_win) - (loss_pct * result.average_loss)).quantize(Decimal("0.01"))

    def _calculate_extremes(self, result: AnalyticsResult, trades: list[Trade]) -> None:
        """Calculate largest win and loss."""
        for trade in trades:
            pnl = trade.pnl or Decimal("0")

            if pnl > result.largest_win:
                result.largest_win = pnl

            if pnl < 0 and abs(pnl) > result.largest_loss:
                result.largest_loss = abs(pnl)

    def _calculate_drawdown(self, result: AnalyticsResult, trades: list[Trade]) -> None:
        """Calculate maximum drawdown metrics."""
        if not trades:
            return

        cumulative_pnl = Decimal("0")
        peak = Decimal("0")
        max_dd = Decimal("0")
        max_dd_pct = Decimal("0")

        for trade in trades:
            pnl = trade.pnl or Decimal("0")
            cumulative_pnl += pnl

            if cumulative_pnl > peak:
                peak = cumulative_pnl

            drawdown = peak - cumulative_pnl
            if drawdown > max_dd:
                max_dd = drawdown

            if peak > 0:
                dd_pct = (drawdown / peak) * 100
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct

        result.max_drawdown = max_dd.quantize(Decimal("0.01"))
        result.max_drawdown_percent = max_dd_pct.quantize(Decimal("0.01"))

    def _calculate_streaks(self, result: AnalyticsResult, trades: list[Trade]) -> None:
        """Calculate winning and losing streaks."""
        if not trades:
            return

        current_streak = 0
        best_win_streak = 0
        worst_loss_streak = 0

        for trade in trades:
            pnl = trade.pnl or Decimal("0")

            if pnl > 0:
                if current_streak > 0:
                    current_streak += 1
                else:
                    current_streak = 1
                if current_streak > best_win_streak:
                    best_win_streak = current_streak
            elif pnl < 0:
                if current_streak < 0:
                    current_streak -= 1
                else:
                    current_streak = -1
                if abs(current_streak) > worst_loss_streak:
                    worst_loss_streak = abs(current_streak)
            # Breakeven trades don't affect streak

        result.best_streak = best_win_streak
        result.worst_streak = worst_loss_streak
        result.current_streak = current_streak

    def _calculate_instrument_breakdown(self, result: AnalyticsResult, trades: list[Trade]) -> None:
        """Calculate breakdown by instrument."""
        instrument_data: dict[str, InstrumentBreakdown] = {}

        for trade in trades:
            instrument = trade.instrument
            if instrument not in instrument_data:
                instrument_data[instrument] = InstrumentBreakdown(instrument=instrument)

            bd = instrument_data[instrument]
            pnl = trade.pnl or Decimal("0")

            bd.total_trades += 1
            if pnl > 0:
                bd.winning_trades += 1
                bd.gross_profit += pnl
            elif pnl < 0:
                bd.losing_trades += 1
                bd.gross_loss += abs(pnl)

        # Calculate derived metrics
        for bd in instrument_data.values():
            bd.net_profit = bd.gross_profit - bd.gross_loss
            if bd.total_trades > 0:
                bd.win_rate = (Decimal(bd.winning_trades) / Decimal(bd.total_trades) * 100).quantize(Decimal("0.01"))

        # Sort by total trades descending
        result.by_instrument = sorted(
            instrument_data.values(),
            key=lambda x: x.total_trades,
            reverse=True,
        )

    def _calculate_day_of_week_breakdown(self, result: AnalyticsResult, trades: list[Trade]) -> None:
        """Calculate breakdown by day of week."""
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_data: dict[int, DayOfWeekBreakdown] = {}

        for trade in trades:
            if not trade.closed_at:
                continue

            day_num = trade.closed_at.weekday()
            if day_num not in day_data:
                day_data[day_num] = DayOfWeekBreakdown(
                    day_name=day_names[day_num],
                    day_number=day_num,
                )

            bd = day_data[day_num]
            pnl = trade.pnl or Decimal("0")

            bd.total_trades += 1
            bd.net_profit += pnl
            if pnl > 0:
                bd.winning_trades += 1
            elif pnl < 0:
                bd.losing_trades += 1

        # Calculate win rates and sort by day number
        for bd in day_data.values():
            if bd.total_trades > 0:
                bd.win_rate = (Decimal(bd.winning_trades) / Decimal(bd.total_trades) * 100).quantize(Decimal("0.01"))

        result.by_day_of_week = sorted(day_data.values(), key=lambda x: x.day_number)

    def _calculate_hour_breakdown(self, result: AnalyticsResult, trades: list[Trade]) -> None:
        """Calculate breakdown by hour of day."""
        hour_data: dict[int, HourBreakdown] = {}

        for trade in trades:
            if not trade.closed_at:
                continue

            hour = trade.closed_at.hour
            if hour not in hour_data:
                hour_data[hour] = HourBreakdown(hour=hour)

            bd = hour_data[hour]
            pnl = trade.pnl or Decimal("0")

            bd.total_trades += 1
            bd.net_profit += pnl
            if pnl > 0:
                bd.winning_trades += 1
            elif pnl < 0:
                bd.losing_trades += 1

        # Calculate win rates and sort by hour
        for bd in hour_data.values():
            if bd.total_trades > 0:
                bd.win_rate = (Decimal(bd.winning_trades) / Decimal(bd.total_trades) * 100).quantize(Decimal("0.01"))

        result.by_hour = sorted(hour_data.values(), key=lambda x: x.hour)

    def _calculate_equity_curve(self, result: AnalyticsResult, trades: list[Trade]) -> None:
        """Calculate equity curve data points."""
        if not trades:
            return

        # Group trades by date
        date_pnl: dict[date, tuple[Decimal, int]] = {}

        for trade in trades:
            if not trade.closed_at:
                continue

            trade_date = trade.closed_at.date()
            pnl = trade.pnl or Decimal("0")

            if trade_date in date_pnl:
                existing_pnl, existing_count = date_pnl[trade_date]
                date_pnl[trade_date] = (existing_pnl + pnl, existing_count + 1)
            else:
                date_pnl[trade_date] = (pnl, 1)

        # Build equity curve with cumulative P&L
        cumulative = Decimal("0")
        sorted_dates = sorted(date_pnl.keys())

        for d in sorted_dates:
            daily_pnl, trade_count = date_pnl[d]
            cumulative += daily_pnl
            result.equity_curve.append(EquityPoint(
                date=d,
                cumulative_pnl=cumulative.quantize(Decimal("0.01")),
                trade_count=trade_count,
            ))

    async def get_trade_context_for_ai(
        self,
        user_id: int,
        account_id: Optional[int] = None,
    ) -> str:
        """
        Generate a text summary of user's trade data for AI context.

        Args:
            user_id: The internal user ID.
            account_id: Optional account ID to filter by.

        Returns:
            str: A formatted summary of trading performance for AI context.
        """
        # Get recent analytics (last 30 days)
        end_date = date.today()
        start_date = end_date - timedelta(days=30)

        recent = await self.calculate_analytics(
            user_id=user_id,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )

        # Get all-time analytics
        all_time = await self.calculate_analytics(
            user_id=user_id,
            account_id=account_id,
        )

        lines = [
            "=== TRADING PERFORMANCE SUMMARY ===",
            "",
            "## Last 30 Days",
            f"- Total Trades: {recent.total_trades}",
            f"- Win Rate: {recent.win_rate}%",
            f"- Net P&L: ${recent.net_profit}",
            f"- Profit Factor: {recent.profit_factor}",
            f"- Best Streak: {recent.best_streak} wins",
            f"- Worst Streak: {recent.worst_streak} losses",
            f"- Current Streak: {recent.current_streak} ({'wins' if recent.current_streak > 0 else 'losses' if recent.current_streak < 0 else 'neutral'})",
            "",
            "## All-Time Statistics",
            f"- Total Trades: {all_time.total_trades}",
            f"- Win Rate: {all_time.win_rate}%",
            f"- Net P&L: ${all_time.net_profit}",
            f"- Profit Factor: {all_time.profit_factor}",
            f"- Average Win: ${all_time.average_win}",
            f"- Average Loss: ${all_time.average_loss}",
            f"- Largest Win: ${all_time.largest_win}",
            f"- Largest Loss: ${all_time.largest_loss}",
            f"- Max Drawdown: ${all_time.max_drawdown} ({all_time.max_drawdown_percent}%)",
            f"- Expectancy: ${all_time.expectancy} per trade",
        ]

        # Add top instruments
        if all_time.by_instrument:
            lines.append("")
            lines.append("## Top Instruments")
            for inst in all_time.by_instrument[:5]:
                lines.append(f"- {inst.instrument}: {inst.total_trades} trades, {inst.win_rate}% win rate, ${inst.net_profit} P&L")

        # Add day of week insights
        if all_time.by_day_of_week:
            best_day = max(all_time.by_day_of_week, key=lambda x: x.net_profit)
            worst_day = min(all_time.by_day_of_week, key=lambda x: x.net_profit)
            lines.append("")
            lines.append("## Day of Week Insights")
            lines.append(f"- Best Day: {best_day.day_name} (${best_day.net_profit} P&L, {best_day.win_rate}% win rate)")
            lines.append(f"- Worst Day: {worst_day.day_name} (${worst_day.net_profit} P&L, {worst_day.win_rate}% win rate)")

        return "\n".join(lines)

    async def recalculate_all_pnl(
        self,
        user_id: Optional[int] = None,
    ) -> dict:
        """
        Recalculate P&L for all closed trades using PnLService.

        This method iterates through all closed trades and recalculates their P&L
        using the current PnLService, which handles currency conversion correctly.
        This is useful for migrating historical trades to the new P&L calculation system.

        Args:
            user_id: Optional user ID to filter trades. If None, recalculates for all users.

        Returns:
            dict: Result summary with structure:
                {
                    "updated_count": int,
                    "error_count": int,
                    "total_processed": int,
                    "errors": list[str] (first 10 errors),
                }
        """
        pnl_service = get_pnl_service()
        updated_count = 0
        error_count = 0
        errors: list[str] = []

        async with get_session() as session:
            # Build query for closed trades with exit price
            query = (
                select(Trade)
                .where(Trade.status == TradeStatus.CLOSED)
                .where(Trade.exit_price.isnot(None))
            )

            # Filter by user if specified
            if user_id is not None:
                # Get user's account IDs
                accounts_result = await session.execute(
                    select(Account.id)
                    .where(Account.user_id == user_id)
                    .where(Account.is_active == True)
                )
                account_ids = [row[0] for row in accounts_result.fetchall()]

                if not account_ids:
                    return {
                        "updated_count": 0,
                        "error_count": 0,
                        "total_processed": 0,
                        "errors": ["No accounts found for user"],
                    }

                query = query.where(Trade.account_id.in_(account_ids))

            result = await session.execute(query)
            trades = list(result.scalars().all())

            logger.info(
                "Starting P&L recalculation",
                trade_count=len(trades),
                user_id=user_id,
            )

            for trade in trades:
                try:
                    # Calculate P&L using PnLService
                    pnl_result = await pnl_service.calculate_pnl(
                        instrument=trade.instrument,
                        direction=trade.direction.value,
                        entry_price=float(trade.entry_price),
                        exit_price=float(trade.exit_price),
                        lot_size=float(trade.lot_size) if trade.lot_size else 1.0,
                    )

                    if pnl_result.success:
                        # Update trade with new P&L (in base currency - USD)
                        new_pnl = Decimal(str(pnl_result.pnl_base))

                        # Only update if different
                        if trade.pnl != new_pnl:
                            trade.pnl = new_pnl
                            updated_count += 1

                            logger.debug(
                                "Trade P&L recalculated",
                                trade_id=trade.id,
                                old_pnl=str(trade.pnl),
                                new_pnl=str(new_pnl),
                                instrument=trade.instrument,
                            )
                    else:
                        error_count += 1
                        if len(errors) < 10:
                            errors.append(f"Trade {trade.id}: {pnl_result.error}")

                except Exception as e:
                    error_count += 1
                    if len(errors) < 10:
                        errors.append(f"Trade {trade.id}: {str(e)}")
                    logger.error(
                        "Error recalculating trade P&L",
                        trade_id=trade.id,
                        error=str(e),
                    )

            # Commit all changes
            await session.flush()

            logger.info(
                "P&L recalculation complete",
                updated_count=updated_count,
                error_count=error_count,
                total_processed=len(trades),
            )

        return {
            "updated_count": updated_count,
            "error_count": error_count,
            "total_processed": len(trades),
            "errors": errors,
        }

    @staticmethod
    async def get_all_data_for_ai(user_id: Optional[int] = None) -> dict:
        """
        Get aggregated trade data in format suitable for AI strategy builder.

        Args:
            user_id: Optional user ID to filter by. If None, returns empty stats.

        Returns:
            dict: Trade statistics formatted for AI consumption with structure:
                {
                    "statistics": {
                        "overall": {"total_trades": int, "win_rate": float, ...},
                        "by_instrument": {"SYMBOL": {"total_trades": int, ...}},
                        "by_direction": {"LONG": {...}, "SHORT": {...}}
                    }
                }
        """
        if user_id is None:
            return {
                "statistics": {
                    "overall": {"total_trades": 0, "win_rate": 0, "profit_factor": 0, "max_drawdown_pct": 0},
                    "by_instrument": {},
                    "by_direction": {"LONG": {"total_trades": 0, "win_rate": 0}, "SHORT": {"total_trades": 0, "win_rate": 0}}
                }
            }

        service = AnalyticsService()
        analytics = await service.calculate_analytics(user_id=user_id)

        # Build instrument breakdown dict
        by_instrument = {}
        for inst in analytics.by_instrument:
            by_instrument[inst.instrument] = {
                "total_trades": inst.total_trades,
                "win_rate": float(inst.win_rate),
                "net_profit": float(inst.net_profit)
            }

        # Build direction breakdown - need to calculate from trades
        by_direction = {"LONG": {"total_trades": 0, "win_rate": 0}, "SHORT": {"total_trades": 0, "win_rate": 0}}

        async with get_session() as session:
            from database.models import Account, Trade, TradeStatus, TradeDirection

            # Get user's account IDs
            accounts_result = await session.execute(
                select(Account.id).where(Account.user_id == user_id).where(Account.is_active == True)
            )
            account_ids = [row[0] for row in accounts_result.fetchall()]

            if account_ids:
                # Get closed trades
                trades_result = await session.execute(
                    select(Trade)
                    .where(Trade.account_id.in_(account_ids))
                    .where(Trade.status == TradeStatus.CLOSED)
                )
                trades = trades_result.scalars().all()

                long_trades = [t for t in trades if t.direction == TradeDirection.LONG]
                short_trades = [t for t in trades if t.direction == TradeDirection.SHORT]

                if long_trades:
                    long_wins = sum(1 for t in long_trades if t.pnl and t.pnl > 0)
                    by_direction["LONG"] = {
                        "total_trades": len(long_trades),
                        "win_rate": (long_wins / len(long_trades)) * 100 if long_trades else 0
                    }

                if short_trades:
                    short_wins = sum(1 for t in short_trades if t.pnl and t.pnl > 0)
                    by_direction["SHORT"] = {
                        "total_trades": len(short_trades),
                        "win_rate": (short_wins / len(short_trades)) * 100 if short_trades else 0
                    }

        return {
            "statistics": {
                "overall": {
                    "total_trades": analytics.total_trades,
                    "win_rate": float(analytics.win_rate),
                    "profit_factor": float(analytics.profit_factor),
                    "max_drawdown_pct": float(analytics.max_drawdown_percent)
                },
                "by_instrument": by_instrument,
                "by_direction": by_direction
            }
        }


# Module-level singleton instance
_analytics_service: Optional[AnalyticsService] = None


def get_analytics_service() -> AnalyticsService:
    """
    Get or create the global analytics service instance.

    Returns:
        AnalyticsService: The global analytics service singleton.
    """
    global _analytics_service
    if _analytics_service is None:
        _analytics_service = AnalyticsService()
    return _analytics_service


def reset_analytics_service() -> None:
    """
    Reset the global analytics service instance.

    Useful for testing or reconfiguration.
    """
    global _analytics_service
    _analytics_service = None
