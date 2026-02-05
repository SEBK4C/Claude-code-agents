"""
Analytics handlers for the Telegram Trade Journal Bot.

This module provides:
- Analytics dashboard with key metrics
- Sub-menus for different analytics views (Overview, Performance, Risk, Patterns, Instruments)
- Account and date range filtering
- Chart generation and display
"""

import io
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from config import get_logger
from database.db import get_session
from handlers.accounts import get_user_accounts, get_user_by_telegram_id
from services.analytics_service import AnalyticsResult, get_analytics_service
from services.report_service import get_report_service
from utils.helpers import format_currency, format_percentage
from utils.keyboards import back_to_menu_keyboard

logger = get_logger(__name__)

# Context keys for analytics state
ANALYTICS_KEY = "analytics_state"


def analytics_main_keyboard() -> InlineKeyboardMarkup:
    """
    Create the main analytics menu keyboard.

    Returns:
        InlineKeyboardMarkup: Analytics main menu keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton("Overview", callback_data="analytics_overview"),
            InlineKeyboardButton("Performance", callback_data="analytics_performance"),
        ],
        [
            InlineKeyboardButton("Risk", callback_data="analytics_risk"),
            InlineKeyboardButton("Patterns", callback_data="analytics_patterns"),
        ],
        [
            InlineKeyboardButton("Instruments", callback_data="analytics_instruments"),
            InlineKeyboardButton("Charts", callback_data="analytics_charts"),
        ],
        [
            InlineKeyboardButton("Filter", callback_data="analytics_filter"),
        ],
        [
            InlineKeyboardButton("Back to Menu", callback_data="menu_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def analytics_filter_keyboard() -> InlineKeyboardMarkup:
    """
    Create the analytics filter keyboard for date range selection.

    Returns:
        InlineKeyboardMarkup: Analytics filter keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton("This Week", callback_data="analytics_range_week"),
            InlineKeyboardButton("This Month", callback_data="analytics_range_month"),
        ],
        [
            InlineKeyboardButton("Last 3 Months", callback_data="analytics_range_3months"),
            InlineKeyboardButton("All Time", callback_data="analytics_range_all"),
        ],
        [
            InlineKeyboardButton("Back", callback_data="menu_analytics"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def analytics_account_keyboard(accounts: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """
    Create account filter keyboard for analytics.

    Args:
        accounts: List of (account_id, account_name) tuples.

    Returns:
        InlineKeyboardMarkup: Account filter keyboard.
    """
    keyboard = []

    keyboard.append([
        InlineKeyboardButton("All Accounts", callback_data="analytics_account_all"),
    ])

    for account_id, account_name in accounts:
        keyboard.append([
            InlineKeyboardButton(account_name, callback_data=f"analytics_account_{account_id}"),
        ])

    keyboard.append([
        InlineKeyboardButton("Back", callback_data="analytics_filter"),
    ])

    return InlineKeyboardMarkup(keyboard)


def analytics_charts_keyboard() -> InlineKeyboardMarkup:
    """
    Create the charts sub-menu keyboard.

    Returns:
        InlineKeyboardMarkup: Charts menu keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton("Equity Curve", callback_data="chart_equity"),
            InlineKeyboardButton("Win/Loss Pie", callback_data="chart_pie"),
        ],
        [
            InlineKeyboardButton("Instruments", callback_data="chart_instruments"),
            InlineKeyboardButton("Drawdown", callback_data="chart_drawdown"),
        ],
        [
            InlineKeyboardButton("Day of Week", callback_data="chart_dow"),
            InlineKeyboardButton("Hour of Day", callback_data="chart_hour"),
        ],
        [
            InlineKeyboardButton("Download All", callback_data="chart_download_all"),
        ],
        [
            InlineKeyboardButton("Back", callback_data="menu_analytics"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def analytics_back_keyboard() -> InlineKeyboardMarkup:
    """
    Create a simple back keyboard for analytics sub-views.

    Returns:
        InlineKeyboardMarkup: Back to analytics keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton("Back to Analytics", callback_data="menu_analytics"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def chart_navigation_keyboard(current_chart: str) -> InlineKeyboardMarkup:
    """
    Create navigation keyboard for chart viewing.

    Args:
        current_chart: Current chart identifier for navigation context.

    Returns:
        InlineKeyboardMarkup: Chart navigation keyboard.
    """
    chart_order = ["equity", "pie", "instruments", "drawdown", "dow", "hour"]

    try:
        current_idx = chart_order.index(current_chart)
    except ValueError:
        current_idx = 0

    prev_idx = (current_idx - 1) % len(chart_order)
    next_idx = (current_idx + 1) % len(chart_order)

    keyboard = [
        [
            InlineKeyboardButton("< Previous", callback_data=f"chart_{chart_order[prev_idx]}"),
            InlineKeyboardButton("Next >", callback_data=f"chart_{chart_order[next_idx]}"),
        ],
        [
            InlineKeyboardButton("Back to Charts", callback_data="analytics_charts"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_date_range(range_key: str) -> tuple[Optional[date], Optional[date]]:
    """
    Get start and end dates for a date range key.

    Args:
        range_key: The range key (week, month, 3months, all).

    Returns:
        tuple: (start_date, end_date) - end_date is None for all ranges.
    """
    today = date.today()

    if range_key == "week":
        start = today - timedelta(days=today.weekday())  # Start of week (Monday)
        return start, today
    elif range_key == "month":
        start = today.replace(day=1)  # Start of month
        return start, today
    elif range_key == "3months":
        start = today - timedelta(days=90)
        return start, today
    else:  # all
        return None, None


def format_analytics_overview(analytics: AnalyticsResult) -> str:
    """
    Format analytics overview message.

    Args:
        analytics: The analytics result.

    Returns:
        str: Formatted overview message.
    """
    lines = [
        "Analytics Overview",
        "=" * 25,
        "",
        f"Total Trades: {analytics.total_trades}",
        f"Win Rate: {format_percentage(analytics.win_rate, include_sign=False)}",
        f"Net P&L: {format_currency(analytics.net_profit, include_sign=True)}",
        f"Profit Factor: {analytics.profit_factor}",
        "",
        "Quick Stats:",
        f"  Wins: {analytics.winning_trades}",
        f"  Losses: {analytics.losing_trades}",
        f"  Breakeven: {analytics.breakeven_trades}",
    ]

    if analytics.current_streak != 0:
        streak_type = "wins" if analytics.current_streak > 0 else "losses"
        lines.append(f"  Current Streak: {abs(analytics.current_streak)} {streak_type}")

    return "\n".join(lines)


def format_analytics_performance(analytics: AnalyticsResult) -> str:
    """
    Format analytics performance message.

    Args:
        analytics: The analytics result.

    Returns:
        str: Formatted performance message.
    """
    lines = [
        "Performance Metrics",
        "=" * 25,
        "",
        "Win/Loss Analysis:",
        f"  Win Rate: {format_percentage(analytics.win_rate, include_sign=False)}",
        f"  Loss Rate: {format_percentage(analytics.loss_rate, include_sign=False)}",
        f"  Avg Win: {format_currency(analytics.average_win)}",
        f"  Avg Loss: {format_currency(analytics.average_loss)}",
        f"  Avg R:R: {analytics.average_rr}",
        "",
        "Profit/Loss:",
        f"  Gross Profit: {format_currency(analytics.gross_profit)}",
        f"  Gross Loss: {format_currency(analytics.gross_loss)}",
        f"  Net Profit: {format_currency(analytics.net_profit, include_sign=True)}",
        f"  Profit Factor: {analytics.profit_factor}",
        "",
        "Streaks:",
        f"  Best Win Streak: {analytics.best_streak}",
        f"  Worst Loss Streak: {analytics.worst_streak}",
        f"  Current: {analytics.current_streak} ({'wins' if analytics.current_streak > 0 else 'losses' if analytics.current_streak < 0 else 'neutral'})",
        "",
        "Extremes:",
        f"  Largest Win: {format_currency(analytics.largest_win)}",
        f"  Largest Loss: {format_currency(analytics.largest_loss)}",
        "",
        f"Expectancy: {format_currency(analytics.expectancy)} per trade",
    ]

    return "\n".join(lines)


def format_analytics_risk(analytics: AnalyticsResult) -> str:
    """
    Format analytics risk message.

    Args:
        analytics: The analytics result.

    Returns:
        str: Formatted risk message.
    """
    lines = [
        "Risk Metrics",
        "=" * 25,
        "",
        "Drawdown:",
        f"  Max Drawdown: {format_currency(analytics.max_drawdown)}",
        f"  Max DD %: {format_percentage(analytics.max_drawdown_percent, include_sign=False)}",
        "",
        "Risk/Reward:",
        f"  Avg Win: {format_currency(analytics.average_win)}",
        f"  Avg Loss: {format_currency(analytics.average_loss)}",
        f"  Realized R:R: {analytics.average_rr}",
        "",
        "Consistency:",
        f"  Win Rate: {format_percentage(analytics.win_rate, include_sign=False)}",
        f"  Profit Factor: {analytics.profit_factor}",
        f"  Best Streak: {analytics.best_streak}",
        f"  Worst Streak: {analytics.worst_streak}",
    ]

    # Add risk assessment
    lines.append("")
    lines.append("Risk Assessment:")

    if analytics.profit_factor >= Decimal("2"):
        lines.append("  Excellent profit factor (>2.0)")
    elif analytics.profit_factor >= Decimal("1.5"):
        lines.append("  Good profit factor (1.5-2.0)")
    elif analytics.profit_factor >= Decimal("1"):
        lines.append("  Marginal profit factor (1.0-1.5)")
    else:
        lines.append("  Warning: Negative expectancy (<1.0)")

    if analytics.max_drawdown_percent > Decimal("30"):
        lines.append("  Warning: High drawdown (>30%)")
    elif analytics.max_drawdown_percent > Decimal("20"):
        lines.append("  Moderate drawdown (20-30%)")
    else:
        lines.append("  Controlled drawdown (<20%)")

    return "\n".join(lines)


def format_analytics_patterns(analytics: AnalyticsResult) -> str:
    """
    Format analytics patterns message (day of week and hour analysis).

    Args:
        analytics: The analytics result.

    Returns:
        str: Formatted patterns message.
    """
    lines = [
        "Trading Patterns",
        "=" * 25,
        "",
    ]

    if analytics.by_day_of_week:
        lines.append("By Day of Week:")
        for day in analytics.by_day_of_week:
            pnl_str = format_currency(day.net_profit, include_sign=True)
            lines.append(f"  {day.day_name[:3]}: {day.total_trades} trades, {format_percentage(day.win_rate, include_sign=False)} WR, {pnl_str}")

        # Find best and worst days
        best_day = max(analytics.by_day_of_week, key=lambda x: x.net_profit)
        worst_day = min(analytics.by_day_of_week, key=lambda x: x.net_profit)
        lines.append("")
        lines.append(f"Best Day: {best_day.day_name}")
        lines.append(f"Worst Day: {worst_day.day_name}")
    else:
        lines.append("No day of week data available.")

    lines.append("")

    if analytics.by_hour:
        lines.append("By Hour (Top 5):")
        sorted_hours = sorted(analytics.by_hour, key=lambda x: x.total_trades, reverse=True)[:5]
        for hour in sorted_hours:
            pnl_str = format_currency(hour.net_profit, include_sign=True)
            lines.append(f"  {hour.hour:02d}:00: {hour.total_trades} trades, {format_percentage(hour.win_rate, include_sign=False)} WR, {pnl_str}")

        # Find most active and most profitable hours
        most_active = max(analytics.by_hour, key=lambda x: x.total_trades)
        most_profitable = max(analytics.by_hour, key=lambda x: x.net_profit)
        lines.append("")
        lines.append(f"Most Active: {most_active.hour:02d}:00 ({most_active.total_trades} trades)")
        lines.append(f"Most Profitable: {most_profitable.hour:02d}:00 ({format_currency(most_profitable.net_profit, include_sign=True)})")
    else:
        lines.append("No hour data available.")

    return "\n".join(lines)


def format_analytics_instruments(analytics: AnalyticsResult) -> str:
    """
    Format analytics instruments message.

    Args:
        analytics: The analytics result.

    Returns:
        str: Formatted instruments message.
    """
    lines = [
        "Instrument Breakdown",
        "=" * 25,
        "",
    ]

    if not analytics.by_instrument:
        lines.append("No instrument data available.")
        return "\n".join(lines)

    for inst in analytics.by_instrument:
        lines.append(f"{inst.instrument}:")
        lines.append(f"  Trades: {inst.total_trades} ({inst.winning_trades}W/{inst.losing_trades}L)")
        lines.append(f"  Win Rate: {format_percentage(inst.win_rate, include_sign=False)}")
        lines.append(f"  Net P&L: {format_currency(inst.net_profit, include_sign=True)}")
        lines.append("")

    # Find best and worst instruments
    best_inst = max(analytics.by_instrument, key=lambda x: x.net_profit)
    worst_inst = min(analytics.by_instrument, key=lambda x: x.net_profit)

    lines.append("Summary:")
    lines.append(f"  Best: {best_inst.instrument} ({format_currency(best_inst.net_profit, include_sign=True)})")
    lines.append(f"  Worst: {worst_inst.instrument} ({format_currency(worst_inst.net_profit, include_sign=True)})")

    return "\n".join(lines)


async def get_user_analytics(
    telegram_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> Optional[AnalyticsResult]:
    """
    Get analytics for a user with current filter settings.

    Args:
        telegram_id: The Telegram user ID.
        context: The callback context containing filter state.

    Returns:
        Optional[AnalyticsResult]: Analytics result or None if user not found.
    """
    async with get_session() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            return None

        # Get filter settings from context
        state = context.user_data.get(ANALYTICS_KEY, {})
        account_id = state.get("account_id")
        date_range = state.get("date_range", "all")

        start_date, end_date = get_date_range(date_range)

        analytics_service = get_analytics_service()
        return await analytics_service.calculate_analytics(
            user_id=user.id,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )


async def handle_analytics_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the main analytics menu callback.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer()

    telegram_id = update.effective_user.id

    analytics = await get_user_analytics(telegram_id, context)

    if analytics is None:
        await query.edit_message_text(
            "Please use /start first to register.",
            reply_markup=back_to_menu_keyboard(),
        )
        return

    # Get filter description
    state = context.user_data.get(ANALYTICS_KEY, {})
    date_range = state.get("date_range", "all")
    account_id = state.get("account_id")

    filter_desc = f"Range: {date_range.title()}"
    if account_id:
        filter_desc += f" | Account: #{account_id}"
    else:
        filter_desc += " | All Accounts"

    message = format_analytics_overview(analytics)
    message += f"\n\n[{filter_desc}]"

    await query.edit_message_text(
        text=message,
        reply_markup=analytics_main_keyboard(),
    )


async def handle_analytics_overview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the analytics overview sub-menu.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer()

    analytics = await get_user_analytics(update.effective_user.id, context)

    if analytics is None:
        await query.edit_message_text(
            "No analytics data available.",
            reply_markup=analytics_back_keyboard(),
        )
        return

    await query.edit_message_text(
        text=format_analytics_overview(analytics),
        reply_markup=analytics_back_keyboard(),
    )


async def handle_analytics_performance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the analytics performance sub-menu.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer()

    analytics = await get_user_analytics(update.effective_user.id, context)

    if analytics is None:
        await query.edit_message_text(
            "No analytics data available.",
            reply_markup=analytics_back_keyboard(),
        )
        return

    await query.edit_message_text(
        text=format_analytics_performance(analytics),
        reply_markup=analytics_back_keyboard(),
    )


async def handle_analytics_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the analytics risk sub-menu.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer()

    analytics = await get_user_analytics(update.effective_user.id, context)

    if analytics is None:
        await query.edit_message_text(
            "No analytics data available.",
            reply_markup=analytics_back_keyboard(),
        )
        return

    await query.edit_message_text(
        text=format_analytics_risk(analytics),
        reply_markup=analytics_back_keyboard(),
    )


async def handle_analytics_patterns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the analytics patterns sub-menu.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer()

    analytics = await get_user_analytics(update.effective_user.id, context)

    if analytics is None:
        await query.edit_message_text(
            "No analytics data available.",
            reply_markup=analytics_back_keyboard(),
        )
        return

    await query.edit_message_text(
        text=format_analytics_patterns(analytics),
        reply_markup=analytics_back_keyboard(),
    )


async def handle_analytics_instruments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the analytics instruments sub-menu.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer()

    analytics = await get_user_analytics(update.effective_user.id, context)

    if analytics is None:
        await query.edit_message_text(
            "No analytics data available.",
            reply_markup=analytics_back_keyboard(),
        )
        return

    await query.edit_message_text(
        text=format_analytics_instruments(analytics),
        reply_markup=analytics_back_keyboard(),
    )


async def handle_analytics_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the analytics filter menu.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query:
        return

    await query.answer()

    state = context.user_data.get(ANALYTICS_KEY, {})
    current_range = state.get("date_range", "all")

    await query.edit_message_text(
        f"Select a date range for analytics.\n\nCurrent: {current_range.title()}",
        reply_markup=analytics_filter_keyboard(),
    )


async def handle_analytics_range(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle date range selection for analytics.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    range_key = query.data.replace("analytics_range_", "")

    if ANALYTICS_KEY not in context.user_data:
        context.user_data[ANALYTICS_KEY] = {}

    context.user_data[ANALYTICS_KEY]["date_range"] = range_key

    # Show account filter next
    telegram_id = update.effective_user.id if update.effective_user else 0

    async with get_session() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if user:
            accounts = await get_user_accounts(session, user.id)
            if accounts:
                account_tuples = [(acc_id, name) for acc_id, name, _, _ in accounts]
                await query.edit_message_text(
                    f"Date range set to: {range_key.title()}\n\n"
                    "Now select an account (or All Accounts):",
                    reply_markup=analytics_account_keyboard(account_tuples),
                )
                return

    # No accounts, go directly to analytics
    query.data = "menu_analytics"
    await handle_analytics_menu(update, context)


async def handle_analytics_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle account selection for analytics filter.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    if ANALYTICS_KEY not in context.user_data:
        context.user_data[ANALYTICS_KEY] = {}

    if query.data == "analytics_account_all":
        context.user_data[ANALYTICS_KEY]["account_id"] = None
    else:
        account_id_str = query.data.replace("analytics_account_", "")
        try:
            context.user_data[ANALYTICS_KEY]["account_id"] = int(account_id_str)
        except ValueError:
            pass

    # Return to main analytics view
    query.data = "menu_analytics"
    await handle_analytics_menu(update, context)


async def handle_analytics_charts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the charts sub-menu.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query:
        return

    await query.answer()

    await query.edit_message_text(
        "Select a chart to view:",
        reply_markup=analytics_charts_keyboard(),
    )


async def send_chart(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chart_bytes: bytes,
    caption: str,
    chart_type: str,
) -> None:
    """
    Send a chart image to the user.

    Args:
        update: The Telegram update object.
        context: The callback context.
        chart_bytes: The PNG image bytes.
        caption: Caption for the image.
        chart_type: Type identifier for navigation.
    """
    query = update.callback_query
    if not query or not query.message:
        return

    # Delete the menu message
    try:
        await query.message.delete()
    except Exception:
        pass

    # Send chart as photo
    await query.message.chat.send_photo(
        photo=InputFile(io.BytesIO(chart_bytes), filename=f"{chart_type}_chart.png"),
        caption=caption,
        reply_markup=chart_navigation_keyboard(chart_type),
    )


async def handle_chart_equity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle equity curve chart request.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer("Generating chart...")

    analytics = await get_user_analytics(update.effective_user.id, context)

    if analytics is None or not analytics.equity_curve:
        await query.edit_message_text(
            "No equity data available for chart.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    report_service = get_report_service()
    chart_bytes = report_service.generate_equity_curve(analytics)

    if not chart_bytes:
        await query.edit_message_text(
            "Failed to generate equity curve chart.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    await send_chart(
        update,
        context,
        chart_bytes,
        f"Equity Curve\nNet P&L: {format_currency(analytics.net_profit, include_sign=True)}",
        "equity",
    )


async def handle_chart_pie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle win/loss pie chart request.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer("Generating chart...")

    analytics = await get_user_analytics(update.effective_user.id, context)

    if analytics is None or analytics.total_trades == 0:
        await query.edit_message_text(
            "No trade data available for chart.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    report_service = get_report_service()
    chart_bytes = report_service.generate_win_loss_pie(analytics)

    if not chart_bytes:
        await query.edit_message_text(
            "Failed to generate win/loss chart.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    await send_chart(
        update,
        context,
        chart_bytes,
        f"Win/Loss Distribution\n{analytics.winning_trades}W / {analytics.losing_trades}L ({format_percentage(analytics.win_rate, include_sign=False)} WR)",
        "pie",
    )


async def handle_chart_instruments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle instrument breakdown chart request.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer("Generating chart...")

    analytics = await get_user_analytics(update.effective_user.id, context)

    if analytics is None or not analytics.by_instrument:
        await query.edit_message_text(
            "No instrument data available for chart.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    report_service = get_report_service()
    chart_bytes = report_service.generate_instrument_chart(analytics)

    if not chart_bytes:
        await query.edit_message_text(
            "Failed to generate instrument chart.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    await send_chart(
        update,
        context,
        chart_bytes,
        f"Performance by Instrument\n{len(analytics.by_instrument)} instruments traded",
        "instruments",
    )


async def handle_chart_drawdown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle drawdown chart request.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer("Generating chart...")

    analytics = await get_user_analytics(update.effective_user.id, context)

    if analytics is None or not analytics.equity_curve:
        await query.edit_message_text(
            "No equity data available for drawdown chart.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    report_service = get_report_service()
    chart_bytes = report_service.generate_drawdown_chart(analytics)

    if not chart_bytes:
        await query.edit_message_text(
            "Failed to generate drawdown chart.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    await send_chart(
        update,
        context,
        chart_bytes,
        f"Drawdown Chart\nMax DD: {format_currency(analytics.max_drawdown)} ({format_percentage(analytics.max_drawdown_percent, include_sign=False)})",
        "drawdown",
    )


async def handle_chart_dow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle day of week chart request.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer("Generating chart...")

    analytics = await get_user_analytics(update.effective_user.id, context)

    if analytics is None or not analytics.by_day_of_week:
        await query.edit_message_text(
            "No day of week data available for chart.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    report_service = get_report_service()
    chart_bytes = report_service.generate_day_of_week_chart(analytics)

    if not chart_bytes:
        await query.edit_message_text(
            "Failed to generate day of week chart.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    best_day = max(analytics.by_day_of_week, key=lambda x: x.net_profit)
    await send_chart(
        update,
        context,
        chart_bytes,
        f"Performance by Day of Week\nBest: {best_day.day_name}",
        "dow",
    )


async def handle_chart_hour(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle hour of day chart request.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer("Generating chart...")

    analytics = await get_user_analytics(update.effective_user.id, context)

    if analytics is None or not analytics.by_hour:
        await query.edit_message_text(
            "No hour data available for chart.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    report_service = get_report_service()
    chart_bytes = report_service.generate_hour_chart(analytics)

    if not chart_bytes:
        await query.edit_message_text(
            "Failed to generate hour chart.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    most_active = max(analytics.by_hour, key=lambda x: x.total_trades)
    await send_chart(
        update,
        context,
        chart_bytes,
        f"Trading Activity by Hour\nMost Active: {most_active.hour:02d}:00",
        "hour",
    )


async def handle_chart_download_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle download all charts request - sends charts as media group.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user or not query.message:
        return

    await query.answer("Generating all charts...")

    analytics = await get_user_analytics(update.effective_user.id, context)

    if analytics is None or analytics.total_trades == 0:
        await query.edit_message_text(
            "No data available to generate charts.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    report_service = get_report_service()
    all_charts = report_service.generate_all_charts(analytics)

    if not all_charts:
        await query.edit_message_text(
            "Failed to generate charts.",
            reply_markup=analytics_charts_keyboard(),
        )
        return

    # Delete the menu message
    try:
        await query.message.delete()
    except Exception:
        pass

    # Send charts as individual photos (Telegram media groups have limitations)
    for chart_name, chart_bytes in all_charts:
        await query.message.chat.send_photo(
            photo=InputFile(io.BytesIO(chart_bytes), filename=f"{chart_name.lower().replace(' ', '_')}.png"),
            caption=chart_name,
        )

    # Send summary message with navigation
    await query.message.chat.send_message(
        f"Generated {len(all_charts)} charts for your analytics.",
        reply_markup=analytics_back_keyboard(),
    )

    logger.info(
        "All charts downloaded",
        telegram_id=update.effective_user.id,
        chart_count=len(all_charts),
    )
