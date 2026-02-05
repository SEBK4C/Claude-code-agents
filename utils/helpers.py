"""
Helper utilities for the Telegram Trade Journal Bot.

This module provides formatting and calculation helper functions
for displaying trade data and computing metrics.
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional, Union

# Currency symbols mapping
CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "EUR": "\u20ac",
    "GBP": "\u00a3",
    "JPY": "\u00a5",
    "CHF": "CHF",
    "AUD": "A$",
    "CAD": "C$",
    "NZD": "NZ$",
    "HKD": "HK$",
    "SGD": "S$",
}


def format_currency(
    amount: Union[Decimal, float, int],
    currency: str = "USD",
    include_sign: bool = False,
) -> str:
    """
    Format a monetary amount with proper currency symbol and formatting.

    Args:
        amount: The monetary amount to format.
        currency: The currency code (e.g., "USD", "EUR").
        include_sign: Whether to include +/- sign for positive/negative values.

    Returns:
        str: Formatted currency string (e.g., "$1,234.56" or "-$500.00").
    """
    # Convert to Decimal for consistent handling
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))

    # Get currency symbol
    symbol = CURRENCY_SYMBOLS.get(currency.upper(), currency)

    # Determine sign
    is_negative = amount < 0
    abs_amount = abs(amount)

    # Format with 2 decimal places and thousands separator
    formatted_number = f"{abs_amount:,.2f}"

    # Build result
    if is_negative:
        result = f"-{symbol}{formatted_number}"
    elif include_sign and amount > 0:
        result = f"+{symbol}{formatted_number}"
    else:
        result = f"{symbol}{formatted_number}"

    return result


def format_percentage(
    value: Union[Decimal, float, int],
    include_sign: bool = True,
    decimal_places: int = 2,
) -> str:
    """
    Format a percentage value with optional sign and specified precision.

    Args:
        value: The percentage value to format (e.g., 5.25 for 5.25%).
        include_sign: Whether to include +/- sign.
        decimal_places: Number of decimal places.

    Returns:
        str: Formatted percentage string (e.g., "+5.25%" or "-3.50%").
    """
    # Convert to Decimal for consistent handling
    if not isinstance(value, Decimal):
        value = Decimal(str(value))

    # Format with specified decimal places
    format_str = f"{{:.{decimal_places}f}}"
    formatted = format_str.format(float(value))

    # Add sign
    if include_sign and value > 0:
        return f"+{formatted}%"
    else:
        return f"{formatted}%"


def format_datetime(
    dt: Optional[datetime],
    include_seconds: bool = False,
) -> str:
    """
    Format a datetime object in a user-friendly format.

    Args:
        dt: The datetime to format, or None.
        include_seconds: Whether to include seconds in the output.

    Returns:
        str: Formatted datetime string (e.g., "Jan 15, 2024 14:30") or "N/A" if None.
    """
    if dt is None:
        return "N/A"

    if include_seconds:
        return dt.strftime("%b %d, %Y %H:%M:%S")
    else:
        return dt.strftime("%b %d, %Y %H:%M")


def format_date(dt: Optional[datetime]) -> str:
    """
    Format a datetime object showing date only.

    Args:
        dt: The datetime to format, or None.

    Returns:
        str: Formatted date string (e.g., "Jan 15, 2024") or "N/A" if None.
    """
    if dt is None:
        return "N/A"

    return dt.strftime("%b %d, %Y")


def calculate_pnl(
    entry_price: Union[Decimal, float],
    exit_price: Union[Decimal, float],
    direction: str,
    lot_size: Union[Decimal, float],
    point_value: Union[Decimal, float] = Decimal("1"),
) -> Decimal:
    """
    Calculate the absolute P&L for a trade.

    Args:
        entry_price: The entry price of the trade.
        exit_price: The exit price of the trade.
        direction: Trade direction ("long" or "short", case-insensitive).
        lot_size: The position size.
        point_value: The value per point movement (default 1).

    Returns:
        Decimal: The absolute P&L amount.
    """
    # Convert all inputs to Decimal
    entry = Decimal(str(entry_price))
    exit_p = Decimal(str(exit_price))
    size = Decimal(str(lot_size))
    pv = Decimal(str(point_value))

    # Calculate price difference based on direction
    direction_lower = direction.lower()
    if direction_lower == "long":
        price_diff = exit_p - entry
    elif direction_lower == "short":
        price_diff = entry - exit_p
    else:
        raise ValueError(f"Invalid direction: {direction}. Must be 'long' or 'short'.")

    # Calculate P&L
    pnl = price_diff * size * pv

    return pnl


def calculate_pnl_percent(
    entry_price: Union[Decimal, float],
    exit_price: Union[Decimal, float],
    direction: str,
) -> Decimal:
    """
    Calculate the percentage P&L for a trade.

    Args:
        entry_price: The entry price of the trade.
        exit_price: The exit price of the trade.
        direction: Trade direction ("long" or "short", case-insensitive).

    Returns:
        Decimal: The percentage P&L.
    """
    # Convert to Decimal
    entry = Decimal(str(entry_price))
    exit_p = Decimal(str(exit_price))

    if entry == 0:
        return Decimal("0")

    # Calculate percentage based on direction
    direction_lower = direction.lower()
    if direction_lower == "long":
        pnl_percent = ((exit_p - entry) / entry) * 100
    elif direction_lower == "short":
        pnl_percent = ((entry - exit_p) / entry) * 100
    else:
        raise ValueError(f"Invalid direction: {direction}. Must be 'long' or 'short'.")

    return pnl_percent.quantize(Decimal("0.0001"))


def calculate_risk_reward(
    entry_price: Union[Decimal, float],
    sl_price: Union[Decimal, float],
    tp_price: Union[Decimal, float],
    direction: str,
) -> Optional[Decimal]:
    """
    Calculate the risk-to-reward ratio for a trade.

    Args:
        entry_price: The entry price of the trade.
        sl_price: The stop-loss price.
        tp_price: The take-profit price.
        direction: Trade direction ("long" or "short", case-insensitive).

    Returns:
        Optional[Decimal]: The R:R ratio (e.g., 2.5 for 1:2.5), or None if
        risk is zero or invalid configuration.
    """
    # Convert to Decimal
    entry = Decimal(str(entry_price))
    sl = Decimal(str(sl_price))
    tp = Decimal(str(tp_price))

    direction_lower = direction.lower()

    if direction_lower == "long":
        # For long: SL below entry, TP above entry
        risk = entry - sl
        reward = tp - entry
    elif direction_lower == "short":
        # For short: SL above entry, TP below entry
        risk = sl - entry
        reward = entry - tp
    else:
        raise ValueError(f"Invalid direction: {direction}. Must be 'long' or 'short'.")

    # Cannot calculate R:R if risk is zero or negative
    if risk <= 0:
        return None

    rr_ratio = reward / risk

    return rr_ratio.quantize(Decimal("0.01"))


def format_trade_summary(trade: Any) -> str:
    """
    Format a trade object into a multi-line summary string.

    Args:
        trade: A trade object with attributes: instrument, direction, entry_price,
               exit_price, lot_size, status, pnl, pnl_percent, opened_at, closed_at,
               notes, strategy.

    Returns:
        str: A formatted multi-line string summarizing the trade.
    """
    lines = []

    # Header with instrument and direction
    direction_display = trade.direction.value.upper() if hasattr(trade.direction, "value") else str(trade.direction).upper()
    lines.append(f"**{trade.instrument}** - {direction_display}")

    # Status
    status_display = trade.status.value.upper() if hasattr(trade.status, "value") else str(trade.status).upper()
    lines.append(f"Status: {status_display}")

    # Entry/Exit prices
    lines.append(f"Entry: {trade.entry_price}")
    if trade.exit_price is not None:
        lines.append(f"Exit: {trade.exit_price}")

    # Stop loss and take profit if available
    if hasattr(trade, "sl_price") and trade.sl_price is not None:
        lines.append(f"SL: {trade.sl_price}")
    if hasattr(trade, "tp_price") and trade.tp_price is not None:
        lines.append(f"TP: {trade.tp_price}")

    # Lot size
    lines.append(f"Size: {trade.lot_size}")

    # P&L (if closed)
    if trade.pnl is not None:
        pnl_str = format_currency(trade.pnl, include_sign=True)
        lines.append(f"P&L: {pnl_str}")
    if trade.pnl_percent is not None:
        pnl_pct_str = format_percentage(trade.pnl_percent)
        lines.append(f"P&L %: {pnl_pct_str}")

    # Timestamps
    if trade.opened_at is not None:
        lines.append(f"Opened: {format_datetime(trade.opened_at)}")
    if trade.closed_at is not None:
        lines.append(f"Closed: {format_datetime(trade.closed_at)}")

    # Strategy if available
    if hasattr(trade, "strategy") and trade.strategy is not None:
        strategy_name = trade.strategy.name if hasattr(trade.strategy, "name") else str(trade.strategy)
        lines.append(f"Strategy: {strategy_name}")

    # Notes if available
    if trade.notes:
        lines.append(f"Notes: {trade.notes}")

    return "\n".join(lines)


def truncate_text(
    text: str,
    max_length: int,
    suffix: str = "...",
) -> str:
    """
    Safely truncate text to a maximum length with an ellipsis suffix.

    Args:
        text: The text to truncate.
        max_length: The maximum length of the result (including suffix).
        suffix: The suffix to append when truncating.

    Returns:
        str: The truncated text with suffix, or original if within limit.
    """
    if not text:
        return ""

    if len(text) <= max_length:
        return text

    # Ensure we have room for the suffix
    truncate_at = max_length - len(suffix)
    if truncate_at <= 0:
        return suffix[:max_length]

    return text[:truncate_at] + suffix


def escape_markdown(text: str) -> str:
    """
    Escape special Telegram markdown characters in text.

    Args:
        text: The text to escape.

    Returns:
        str: The text with markdown special characters escaped.
    """
    if not text:
        return ""

    # Characters that need escaping in Telegram markdown v2
    # Note: This is for MarkdownV2 format
    special_chars = [
        "_", "*", "[", "]", "(", ")", "~", "`", ">",
        "#", "+", "-", "=", "|", "{", "}", ".", "!"
    ]

    result = text
    for char in special_chars:
        result = result.replace(char, f"\\{char}")

    return result
