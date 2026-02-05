"""
Report Service for the Telegram Trade Journal Bot.

This module provides chart generation functionality for trading analytics
using matplotlib with dark theme styling optimized for Telegram display.
"""

import io
from decimal import Decimal
from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.figure import Figure

from config import get_logger
from services.analytics_service import AnalyticsResult, EquityPoint

# Use non-interactive backend for server-side rendering
matplotlib.use("Agg")

logger = get_logger(__name__)

# Chart styling constants
CHART_WIDTH = 10  # inches
CHART_HEIGHT = 6  # inches
CHART_DPI = 100  # Results in approximately 1000x600 pixels
BACKGROUND_COLOR = "#1a1a2e"
TEXT_COLOR = "#eaeaea"
GRID_COLOR = "#2d2d44"
POSITIVE_COLOR = "#00c853"
NEGATIVE_COLOR = "#ff5252"
NEUTRAL_COLOR = "#64b5f6"
ACCENT_COLOR = "#bb86fc"


def _apply_dark_theme(fig: Figure, ax: plt.Axes) -> None:
    """
    Apply dark theme styling to a matplotlib figure and axes.

    Args:
        fig: The matplotlib Figure object.
        ax: The matplotlib Axes object.
    """
    fig.patch.set_facecolor(BACKGROUND_COLOR)
    ax.set_facecolor(BACKGROUND_COLOR)

    # Style axes
    ax.spines["bottom"].set_color(TEXT_COLOR)
    ax.spines["top"].set_color(BACKGROUND_COLOR)
    ax.spines["left"].set_color(TEXT_COLOR)
    ax.spines["right"].set_color(BACKGROUND_COLOR)

    ax.tick_params(colors=TEXT_COLOR, which="both")
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.title.set_color(TEXT_COLOR)

    # Grid styling
    ax.grid(True, color=GRID_COLOR, linestyle="--", alpha=0.5)


def _save_chart_to_bytes(fig: Figure) -> bytes:
    """
    Save a matplotlib figure to PNG bytes.

    Args:
        fig: The matplotlib Figure object.

    Returns:
        bytes: PNG image data.
    """
    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        dpi=CHART_DPI,
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
        edgecolor="none",
    )
    buf.seek(0)
    plt.close(fig)
    return buf.getvalue()


def generate_equity_curve(equity_data: list[EquityPoint]) -> Optional[bytes]:
    """
    Generate an equity curve chart from equity data points.

    Args:
        equity_data: List of EquityPoint objects with date and cumulative_pnl.

    Returns:
        Optional[bytes]: PNG image bytes, or None if data is empty.
    """
    if not equity_data:
        logger.warning("No equity data provided for chart generation")
        return None

    try:
        fig, ax = plt.subplots(figsize=(CHART_WIDTH, CHART_HEIGHT))
        _apply_dark_theme(fig, ax)

        # Extract data
        dates = [point.date for point in equity_data]
        pnl_values = [float(point.cumulative_pnl) for point in equity_data]

        # Plot the equity curve
        ax.plot(dates, pnl_values, color=ACCENT_COLOR, linewidth=2, label="Equity")

        # Fill area under curve with gradient effect
        ax.fill_between(
            dates,
            pnl_values,
            alpha=0.3,
            color=POSITIVE_COLOR if pnl_values[-1] >= 0 else NEGATIVE_COLOR,
        )

        # Add zero line
        ax.axhline(y=0, color=TEXT_COLOR, linestyle="-", alpha=0.3)

        # Highlight positive/negative regions
        for i in range(len(pnl_values)):
            if pnl_values[i] >= 0:
                ax.scatter(dates[i], pnl_values[i], color=POSITIVE_COLOR, s=20, alpha=0.7, zorder=5)
            else:
                ax.scatter(dates[i], pnl_values[i], color=NEGATIVE_COLOR, s=20, alpha=0.7, zorder=5)

        # Labels and title
        ax.set_title("Equity Curve", fontsize=16, fontweight="bold", pad=15)
        ax.set_xlabel("Date", fontsize=12)
        ax.set_ylabel("Cumulative P&L ($)", fontsize=12)

        # Format x-axis dates
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate()

        # Add final value annotation
        final_pnl = pnl_values[-1]
        color = POSITIVE_COLOR if final_pnl >= 0 else NEGATIVE_COLOR
        sign = "+" if final_pnl >= 0 else ""
        ax.annotate(
            f"{sign}${final_pnl:,.2f}",
            xy=(dates[-1], final_pnl),
            xytext=(10, 10),
            textcoords="offset points",
            fontsize=12,
            fontweight="bold",
            color=color,
            bbox=dict(boxstyle="round,pad=0.3", facecolor=BACKGROUND_COLOR, edgecolor=color),
        )

        logger.info("Equity curve chart generated", data_points=len(equity_data))
        return _save_chart_to_bytes(fig)

    except Exception as e:
        logger.error("Failed to generate equity curve chart", error=str(e))
        plt.close("all")
        return None


def generate_win_loss_pie(wins: int, losses: int, breakeven: int = 0) -> Optional[bytes]:
    """
    Generate a win/loss pie chart.

    Args:
        wins: Number of winning trades.
        losses: Number of losing trades.
        breakeven: Number of breakeven trades.

    Returns:
        Optional[bytes]: PNG image bytes, or None if no data.
    """
    total = wins + losses + breakeven
    if total == 0:
        logger.warning("No trade data provided for pie chart")
        return None

    try:
        fig, ax = plt.subplots(figsize=(CHART_WIDTH, CHART_HEIGHT))
        fig.patch.set_facecolor(BACKGROUND_COLOR)
        ax.set_facecolor(BACKGROUND_COLOR)

        # Prepare data
        sizes = []
        labels = []
        colors = []
        explode = []

        if wins > 0:
            sizes.append(wins)
            labels.append(f"Wins ({wins})")
            colors.append(POSITIVE_COLOR)
            explode.append(0.02)

        if losses > 0:
            sizes.append(losses)
            labels.append(f"Losses ({losses})")
            colors.append(NEGATIVE_COLOR)
            explode.append(0.02)

        if breakeven > 0:
            sizes.append(breakeven)
            labels.append(f"Breakeven ({breakeven})")
            colors.append(NEUTRAL_COLOR)
            explode.append(0.02)

        # Create pie chart
        wedges, texts, autotexts = ax.pie(
            sizes,
            labels=labels,
            colors=colors,
            explode=explode,
            autopct="%1.1f%%",
            startangle=90,
            textprops={"color": TEXT_COLOR, "fontsize": 11},
            wedgeprops={"edgecolor": BACKGROUND_COLOR, "linewidth": 2},
        )

        # Style percentage text
        for autotext in autotexts:
            autotext.set_color(BACKGROUND_COLOR)
            autotext.set_fontweight("bold")

        ax.set_title("Win/Loss Distribution", fontsize=16, fontweight="bold", color=TEXT_COLOR, pad=15)

        # Add win rate text
        if total > 0:
            win_rate = (wins / total) * 100
            ax.text(
                0.5,
                -0.1,
                f"Win Rate: {win_rate:.1f}%",
                transform=ax.transAxes,
                ha="center",
                fontsize=14,
                fontweight="bold",
                color=POSITIVE_COLOR if win_rate >= 50 else NEGATIVE_COLOR,
            )

        logger.info("Win/loss pie chart generated", wins=wins, losses=losses, breakeven=breakeven)
        return _save_chart_to_bytes(fig)

    except Exception as e:
        logger.error("Failed to generate win/loss pie chart", error=str(e))
        plt.close("all")
        return None


def generate_instrument_bar(
    instruments: list[str],
    values: list[Decimal],
    title: str = "Performance by Instrument",
    ylabel: str = "Net P&L ($)",
) -> Optional[bytes]:
    """
    Generate a horizontal bar chart for instrument breakdown.

    Args:
        instruments: List of instrument names.
        values: List of values (P&L or trade counts) corresponding to instruments.
        title: Chart title.
        ylabel: Y-axis label.

    Returns:
        Optional[bytes]: PNG image bytes, or None if no data.
    """
    if not instruments or not values:
        logger.warning("No instrument data provided for bar chart")
        return None

    try:
        fig, ax = plt.subplots(figsize=(CHART_WIDTH, CHART_HEIGHT))
        _apply_dark_theme(fig, ax)

        # Convert Decimals to floats
        float_values = [float(v) for v in values]

        # Sort by value
        sorted_data = sorted(zip(instruments, float_values), key=lambda x: x[1], reverse=True)
        sorted_instruments = [d[0] for d in sorted_data]
        sorted_values = [d[1] for d in sorted_data]

        # Determine colors based on positive/negative
        colors = [POSITIVE_COLOR if v >= 0 else NEGATIVE_COLOR for v in sorted_values]

        # Create horizontal bar chart
        y_pos = range(len(sorted_instruments))
        bars = ax.barh(y_pos, sorted_values, color=colors, edgecolor=BACKGROUND_COLOR, height=0.6)

        # Add value labels on bars
        for bar, value in zip(bars, sorted_values):
            width = bar.get_width()
            label_x = width + (max(abs(v) for v in sorted_values) * 0.02) if width >= 0 else width - (max(abs(v) for v in sorted_values) * 0.02)
            ha = "left" if width >= 0 else "right"
            color = POSITIVE_COLOR if value >= 0 else NEGATIVE_COLOR
            ax.text(
                label_x,
                bar.get_y() + bar.get_height() / 2,
                f"${value:,.0f}",
                ha=ha,
                va="center",
                color=color,
                fontsize=10,
                fontweight="bold",
            )

        ax.set_yticks(y_pos)
        ax.set_yticklabels(sorted_instruments)
        ax.set_xlabel(ylabel, fontsize=12)
        ax.set_title(title, fontsize=16, fontweight="bold", pad=15)

        # Add zero line
        ax.axvline(x=0, color=TEXT_COLOR, linestyle="-", alpha=0.3)

        # Adjust layout
        plt.tight_layout()

        logger.info("Instrument bar chart generated", instruments=len(instruments))
        return _save_chart_to_bytes(fig)

    except Exception as e:
        logger.error("Failed to generate instrument bar chart", error=str(e))
        plt.close("all")
        return None


def generate_drawdown_chart(equity_data: list[EquityPoint]) -> Optional[bytes]:
    """
    Generate a drawdown chart showing peak-to-trough declines.

    Args:
        equity_data: List of EquityPoint objects with date and cumulative_pnl.

    Returns:
        Optional[bytes]: PNG image bytes, or None if no data.
    """
    if not equity_data:
        logger.warning("No equity data provided for drawdown chart")
        return None

    try:
        fig, ax = plt.subplots(figsize=(CHART_WIDTH, CHART_HEIGHT))
        _apply_dark_theme(fig, ax)

        # Extract data and calculate drawdown
        dates = [point.date for point in equity_data]
        pnl_values = [float(point.cumulative_pnl) for point in equity_data]

        # Calculate drawdown series
        peak = pnl_values[0]
        drawdowns = []

        for pnl in pnl_values:
            if pnl > peak:
                peak = pnl
            drawdown = peak - pnl
            drawdowns.append(-drawdown)  # Negative for visual display below zero

        # Plot drawdown as filled area
        ax.fill_between(dates, drawdowns, 0, color=NEGATIVE_COLOR, alpha=0.5)
        ax.plot(dates, drawdowns, color=NEGATIVE_COLOR, linewidth=1.5)

        # Add zero line
        ax.axhline(y=0, color=TEXT_COLOR, linestyle="-", linewidth=1)

        # Labels and title
        ax.set_title("Drawdown Chart", fontsize=16, fontweight="bold", pad=15)
        ax.set_xlabel("Date", fontsize=12)
        ax.set_ylabel("Drawdown ($)", fontsize=12)

        # Format x-axis dates
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate()

        # Add max drawdown annotation
        min_dd = min(drawdowns)
        min_dd_idx = drawdowns.index(min_dd)
        ax.annotate(
            f"Max DD: ${abs(min_dd):,.2f}",
            xy=(dates[min_dd_idx], min_dd),
            xytext=(10, -20),
            textcoords="offset points",
            fontsize=11,
            fontweight="bold",
            color=NEGATIVE_COLOR,
            bbox=dict(boxstyle="round,pad=0.3", facecolor=BACKGROUND_COLOR, edgecolor=NEGATIVE_COLOR),
            arrowprops=dict(arrowstyle="->", color=NEGATIVE_COLOR),
        )

        logger.info("Drawdown chart generated", data_points=len(equity_data))
        return _save_chart_to_bytes(fig)

    except Exception as e:
        logger.error("Failed to generate drawdown chart", error=str(e))
        plt.close("all")
        return None


def generate_day_of_week_chart(
    days: list[str],
    win_rates: list[Decimal],
    net_profits: list[Decimal],
) -> Optional[bytes]:
    """
    Generate a combined chart showing win rate and P&L by day of week.

    Args:
        days: List of day names.
        win_rates: List of win rates (0-100) for each day.
        net_profits: List of net P&L for each day.

    Returns:
        Optional[bytes]: PNG image bytes, or None if no data.
    """
    if not days:
        logger.warning("No day of week data provided for chart")
        return None

    try:
        fig, ax1 = plt.subplots(figsize=(CHART_WIDTH, CHART_HEIGHT))
        _apply_dark_theme(fig, ax1)

        x = range(len(days))

        # Bar chart for net P&L
        float_profits = [float(p) for p in net_profits]
        colors = [POSITIVE_COLOR if p >= 0 else NEGATIVE_COLOR for p in float_profits]
        bars = ax1.bar(x, float_profits, color=colors, alpha=0.7, label="Net P&L", edgecolor=BACKGROUND_COLOR)

        ax1.set_xlabel("Day of Week", fontsize=12)
        ax1.set_ylabel("Net P&L ($)", fontsize=12, color=TEXT_COLOR)
        ax1.tick_params(axis="y", labelcolor=TEXT_COLOR)
        ax1.axhline(y=0, color=TEXT_COLOR, linestyle="-", alpha=0.3)

        # Create second y-axis for win rate
        ax2 = ax1.twinx()
        ax2.set_facecolor(BACKGROUND_COLOR)
        float_win_rates = [float(w) for w in win_rates]
        ax2.plot(x, float_win_rates, color=ACCENT_COLOR, linewidth=3, marker="o", markersize=8, label="Win Rate")
        ax2.set_ylabel("Win Rate (%)", fontsize=12, color=ACCENT_COLOR)
        ax2.tick_params(axis="y", labelcolor=ACCENT_COLOR)
        ax2.set_ylim(0, 100)

        # Add 50% reference line
        ax2.axhline(y=50, color=ACCENT_COLOR, linestyle="--", alpha=0.5)

        ax1.set_xticks(x)
        ax1.set_xticklabels(days, fontsize=10)
        ax1.set_title("Performance by Day of Week", fontsize=16, fontweight="bold", pad=15)

        # Combined legend
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", facecolor=BACKGROUND_COLOR, edgecolor=TEXT_COLOR, labelcolor=TEXT_COLOR)

        plt.tight_layout()

        logger.info("Day of week chart generated", days=len(days))
        return _save_chart_to_bytes(fig)

    except Exception as e:
        logger.error("Failed to generate day of week chart", error=str(e))
        plt.close("all")
        return None


def generate_hour_chart(
    hours: list[int],
    trade_counts: list[int],
    net_profits: list[Decimal],
) -> Optional[bytes]:
    """
    Generate a chart showing trading activity and P&L by hour.

    Args:
        hours: List of hours (0-23).
        trade_counts: List of trade counts for each hour.
        net_profits: List of net P&L for each hour.

    Returns:
        Optional[bytes]: PNG image bytes, or None if no data.
    """
    if not hours:
        logger.warning("No hour data provided for chart")
        return None

    try:
        fig, ax1 = plt.subplots(figsize=(CHART_WIDTH, CHART_HEIGHT))
        _apply_dark_theme(fig, ax1)

        # Create full 24-hour range with zeros for missing hours
        full_hours = list(range(24))
        full_counts = [0] * 24
        full_profits = [Decimal("0")] * 24

        for i, h in enumerate(hours):
            full_counts[h] = trade_counts[i]
            full_profits[h] = net_profits[i]

        x = full_hours

        # Bar chart for trade counts
        ax1.bar(x, full_counts, color=NEUTRAL_COLOR, alpha=0.6, label="Trade Count", edgecolor=BACKGROUND_COLOR)
        ax1.set_xlabel("Hour of Day", fontsize=12)
        ax1.set_ylabel("Number of Trades", fontsize=12, color=NEUTRAL_COLOR)
        ax1.tick_params(axis="y", labelcolor=NEUTRAL_COLOR)

        # Create second y-axis for P&L
        ax2 = ax1.twinx()
        ax2.set_facecolor(BACKGROUND_COLOR)
        float_profits = [float(p) for p in full_profits]
        colors = [POSITIVE_COLOR if p >= 0 else NEGATIVE_COLOR for p in float_profits]

        # Line plot for P&L
        ax2.plot(x, float_profits, color=ACCENT_COLOR, linewidth=2, marker=".", markersize=4, label="Net P&L")
        ax2.set_ylabel("Net P&L ($)", fontsize=12, color=ACCENT_COLOR)
        ax2.tick_params(axis="y", labelcolor=ACCENT_COLOR)
        ax2.axhline(y=0, color=TEXT_COLOR, linestyle="-", alpha=0.3)

        ax1.set_xticks(range(0, 24, 2))
        ax1.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)], fontsize=9, rotation=45)
        ax1.set_title("Trading Activity by Hour", fontsize=16, fontweight="bold", pad=15)

        # Combined legend
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", facecolor=BACKGROUND_COLOR, edgecolor=TEXT_COLOR, labelcolor=TEXT_COLOR)

        plt.tight_layout()

        logger.info("Hour chart generated", hours=len(hours))
        return _save_chart_to_bytes(fig)

    except Exception as e:
        logger.error("Failed to generate hour chart", error=str(e))
        plt.close("all")
        return None


class ReportService:
    """
    Service class for generating analytics reports and charts.

    Provides methods to generate various chart types from analytics data.
    """

    def __init__(self) -> None:
        """Initialize the report service."""
        logger.info("ReportService initialized")

    def generate_equity_curve(self, analytics: AnalyticsResult) -> Optional[bytes]:
        """
        Generate an equity curve chart from analytics results.

        Args:
            analytics: The analytics result containing equity curve data.

        Returns:
            Optional[bytes]: PNG image bytes, or None if no data.
        """
        return generate_equity_curve(analytics.equity_curve)

    def generate_win_loss_pie(self, analytics: AnalyticsResult) -> Optional[bytes]:
        """
        Generate a win/loss pie chart from analytics results.

        Args:
            analytics: The analytics result containing trade counts.

        Returns:
            Optional[bytes]: PNG image bytes, or None if no data.
        """
        return generate_win_loss_pie(
            wins=analytics.winning_trades,
            losses=analytics.losing_trades,
            breakeven=analytics.breakeven_trades,
        )

    def generate_instrument_chart(self, analytics: AnalyticsResult) -> Optional[bytes]:
        """
        Generate an instrument breakdown bar chart from analytics results.

        Args:
            analytics: The analytics result containing instrument breakdown.

        Returns:
            Optional[bytes]: PNG image bytes, or None if no data.
        """
        if not analytics.by_instrument:
            return None

        instruments = [b.instrument for b in analytics.by_instrument]
        values = [b.net_profit for b in analytics.by_instrument]

        return generate_instrument_bar(instruments, values)

    def generate_drawdown_chart(self, analytics: AnalyticsResult) -> Optional[bytes]:
        """
        Generate a drawdown chart from analytics results.

        Args:
            analytics: The analytics result containing equity curve data.

        Returns:
            Optional[bytes]: PNG image bytes, or None if no data.
        """
        return generate_drawdown_chart(analytics.equity_curve)

    def generate_day_of_week_chart(self, analytics: AnalyticsResult) -> Optional[bytes]:
        """
        Generate a day of week performance chart from analytics results.

        Args:
            analytics: The analytics result containing day of week breakdown.

        Returns:
            Optional[bytes]: PNG image bytes, or None if no data.
        """
        if not analytics.by_day_of_week:
            return None

        days = [b.day_name for b in analytics.by_day_of_week]
        win_rates = [b.win_rate for b in analytics.by_day_of_week]
        net_profits = [b.net_profit for b in analytics.by_day_of_week]

        return generate_day_of_week_chart(days, win_rates, net_profits)

    def generate_hour_chart(self, analytics: AnalyticsResult) -> Optional[bytes]:
        """
        Generate an hour of day activity chart from analytics results.

        Args:
            analytics: The analytics result containing hour breakdown.

        Returns:
            Optional[bytes]: PNG image bytes, or None if no data.
        """
        if not analytics.by_hour:
            return None

        hours = [b.hour for b in analytics.by_hour]
        trade_counts = [b.total_trades for b in analytics.by_hour]
        net_profits = [b.net_profit for b in analytics.by_hour]

        return generate_hour_chart(hours, trade_counts, net_profits)

    def generate_all_charts(self, analytics: AnalyticsResult) -> list[tuple[str, bytes]]:
        """
        Generate all available charts from analytics results.

        Args:
            analytics: The analytics result.

        Returns:
            list: List of (chart_name, chart_bytes) tuples for non-empty charts.
        """
        charts: list[tuple[str, bytes]] = []

        # Equity curve
        equity = self.generate_equity_curve(analytics)
        if equity:
            charts.append(("Equity Curve", equity))

        # Win/Loss pie
        pie = self.generate_win_loss_pie(analytics)
        if pie:
            charts.append(("Win/Loss Distribution", pie))

        # Instrument breakdown
        instrument = self.generate_instrument_chart(analytics)
        if instrument:
            charts.append(("Performance by Instrument", instrument))

        # Drawdown
        drawdown = self.generate_drawdown_chart(analytics)
        if drawdown:
            charts.append(("Drawdown", drawdown))

        # Day of week
        dow = self.generate_day_of_week_chart(analytics)
        if dow:
            charts.append(("Day of Week Performance", dow))

        # Hour of day
        hour = self.generate_hour_chart(analytics)
        if hour:
            charts.append(("Trading by Hour", hour))

        logger.info("Generated all charts", chart_count=len(charts))
        return charts


# Module-level singleton instance
_report_service: Optional[ReportService] = None


def get_report_service() -> ReportService:
    """
    Get or create the global report service instance.

    Returns:
        ReportService: The global report service singleton.
    """
    global _report_service
    if _report_service is None:
        _report_service = ReportService()
    return _report_service


def reset_report_service() -> None:
    """
    Reset the global report service instance.

    Useful for testing or reconfiguration.
    """
    global _report_service
    _report_service = None
