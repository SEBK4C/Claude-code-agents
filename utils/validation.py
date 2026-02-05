"""
Input validation utilities for the Telegram Trade Journal Bot.

This module provides validation functions for user inputs including
prices, lot sizes, instruments, and other trading-related values.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional, Union

# Supported currencies list
SUPPORTED_CURRENCIES: set[str] = {
    "USD", "EUR", "GBP", "JPY", "CHF",
    "AUD", "CAD", "NZD", "HKD", "SGD",
}

# Known trading instruments
KNOWN_INSTRUMENTS: set[str] = {
    "DAX", "NASDAQ", "SP500", "DOW",
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
    "AUDUSD", "NZDUSD", "USDCAD",
    "XAUUSD", "XAGUSD",  # Gold, Silver
    "BTCUSD", "ETHUSD",  # Crypto
}


@dataclass
class ValidationResult:
    """
    Result of a validation operation.

    Attributes:
        is_valid: Whether the validation passed.
        value: The validated and converted value (if valid), or None.
        error: An error message describing the validation failure (if invalid), or None.
    """

    is_valid: bool
    value: Optional[Union[Decimal, float, str, int]] = None
    error: Optional[str] = None


def validate_price(input_value: str) -> ValidationResult:
    """
    Validate a price input.

    Args:
        input_value: The user input string to validate.

    Returns:
        ValidationResult: Contains is_valid, parsed value (Decimal), and error message.
    """
    if not input_value:
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Price cannot be empty.",
        )

    # Clean the input (remove whitespace, replace comma with period)
    cleaned = input_value.strip().replace(",", ".")

    try:
        price = Decimal(cleaned)
    except InvalidOperation:
        return ValidationResult(
            is_valid=False,
            value=None,
            error=f"Invalid price format: '{input_value}'. Please enter a valid number.",
        )

    # Price must be positive
    if price <= 0:
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Price must be greater than zero.",
        )

    return ValidationResult(
        is_valid=True,
        value=price,
        error=None,
    )


def validate_lot_size(
    input_value: str,
    min_lot: Decimal = Decimal("0.01"),
    max_lot: Decimal = Decimal("1000"),
) -> ValidationResult:
    """
    Validate a lot size input.

    Args:
        input_value: The user input string to validate.
        min_lot: Minimum allowed lot size (default 0.01).
        max_lot: Maximum allowed lot size (default 1000).

    Returns:
        ValidationResult: Contains is_valid, parsed value (Decimal), and error message.
    """
    if not input_value:
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Lot size cannot be empty.",
        )

    # Clean the input
    cleaned = input_value.strip().replace(",", ".")

    try:
        lot_size = Decimal(cleaned)
    except InvalidOperation:
        return ValidationResult(
            is_valid=False,
            value=None,
            error=f"Invalid lot size format: '{input_value}'. Please enter a valid number.",
        )

    # Check minimum
    if lot_size < min_lot:
        return ValidationResult(
            is_valid=False,
            value=None,
            error=f"Lot size must be at least {min_lot}.",
        )

    # Check maximum
    if lot_size > max_lot:
        return ValidationResult(
            is_valid=False,
            value=None,
            error=f"Lot size cannot exceed {max_lot}.",
        )

    return ValidationResult(
        is_valid=True,
        value=lot_size,
        error=None,
    )


def validate_instrument(
    input_value: str,
    allow_custom: bool = True,
) -> ValidationResult:
    """
    Validate a trading instrument input.

    Args:
        input_value: The user input string to validate.
        allow_custom: Whether to allow instruments not in the known list.

    Returns:
        ValidationResult: Contains is_valid, normalized instrument string, and error message.
    """
    if not input_value:
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Instrument cannot be empty.",
        )

    # Clean and normalize the input
    cleaned = input_value.strip().upper()

    # Remove common separators for forex pairs
    normalized = cleaned.replace("/", "").replace("-", "").replace(" ", "")

    # Check against known instruments
    if normalized in KNOWN_INSTRUMENTS:
        return ValidationResult(
            is_valid=True,
            value=normalized,
            error=None,
        )

    # Allow custom instruments if enabled
    if allow_custom:
        # Basic validation: alphanumeric, 2-20 characters
        if re.match(r"^[A-Z0-9]{2,20}$", normalized):
            return ValidationResult(
                is_valid=True,
                value=normalized,
                error=None,
            )
        else:
            return ValidationResult(
                is_valid=False,
                value=None,
                error="Instrument must be 2-20 alphanumeric characters.",
            )

    return ValidationResult(
        is_valid=False,
        value=None,
        error=f"Unknown instrument: '{input_value}'. Please select from the list.",
    )


def validate_account_name(input_value: str) -> ValidationResult:
    """
    Validate an account name input.

    Args:
        input_value: The user input string to validate.

    Returns:
        ValidationResult: Contains is_valid, cleaned string, and error message.
    """
    if not input_value:
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Account name cannot be empty.",
        )

    cleaned = input_value.strip()

    # Length check: 3-50 characters
    if len(cleaned) < 3:
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Account name must be at least 3 characters.",
        )

    if len(cleaned) > 50:
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Account name cannot exceed 50 characters.",
        )

    # Allow alphanumeric characters, spaces, hyphens, and underscores
    if not re.match(r"^[a-zA-Z0-9\s\-_]+$", cleaned):
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Account name can only contain letters, numbers, spaces, hyphens, and underscores.",
        )

    return ValidationResult(
        is_valid=True,
        value=cleaned,
        error=None,
    )


def validate_currency(input_value: str) -> ValidationResult:
    """
    Validate a currency code input.

    Args:
        input_value: The user input string to validate.

    Returns:
        ValidationResult: Contains is_valid, normalized currency code, and error message.
    """
    if not input_value:
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Currency cannot be empty.",
        )

    normalized = input_value.strip().upper()

    if normalized not in SUPPORTED_CURRENCIES:
        supported_list = ", ".join(sorted(SUPPORTED_CURRENCIES))
        return ValidationResult(
            is_valid=False,
            value=None,
            error=f"Unsupported currency: '{input_value}'. Supported: {supported_list}",
        )

    return ValidationResult(
        is_valid=True,
        value=normalized,
        error=None,
    )


def validate_time_format(input_value: str) -> ValidationResult:
    """
    Validate a time input in HH:MM format.

    Args:
        input_value: The user input string to validate.

    Returns:
        ValidationResult: Contains is_valid, validated time string, and error message.
    """
    if not input_value:
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Time cannot be empty.",
        )

    cleaned = input_value.strip()

    # Match HH:MM format (24-hour)
    match = re.match(r"^(\d{1,2}):(\d{2})$", cleaned)
    if not match:
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Invalid time format. Please use HH:MM (e.g., 09:30, 14:00).",
        )

    hours = int(match.group(1))
    minutes = int(match.group(2))

    # Validate hour range (0-23)
    if hours < 0 or hours > 23:
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Hours must be between 0 and 23.",
        )

    # Validate minute range (0-59)
    if minutes < 0 or minutes > 59:
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Minutes must be between 0 and 59.",
        )

    # Return normalized format (zero-padded)
    normalized_time = f"{hours:02d}:{minutes:02d}"

    return ValidationResult(
        is_valid=True,
        value=normalized_time,
        error=None,
    )


def validate_direction(input_value: str) -> ValidationResult:
    """
    Validate a trade direction input.

    Args:
        input_value: The user input string to validate.

    Returns:
        ValidationResult: Contains is_valid, normalized direction string, and error message.
    """
    if not input_value:
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Direction cannot be empty.",
        )

    normalized = input_value.strip().upper()

    if normalized not in ("LONG", "SHORT"):
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Direction must be 'LONG' or 'SHORT'.",
        )

    return ValidationResult(
        is_valid=True,
        value=normalized,
        error=None,
    )


def validate_sl_tp(
    entry_price: Union[Decimal, float, str],
    sl_price: Optional[Union[Decimal, float, str]],
    tp_price: Optional[Union[Decimal, float, str]],
    direction: str,
) -> ValidationResult:
    """
    Validate stop-loss and take-profit prices relative to entry and direction.

    For LONG trades:
    - SL must be below entry price
    - TP must be above entry price

    For SHORT trades:
    - SL must be above entry price
    - TP must be below entry price

    Args:
        entry_price: The entry price of the trade.
        sl_price: The stop-loss price (optional).
        tp_price: The take-profit price (optional).
        direction: Trade direction ("LONG" or "SHORT").

    Returns:
        ValidationResult: Contains is_valid, tuple of (sl, tp) Decimals, and error message.
    """
    # Parse entry price
    try:
        entry = Decimal(str(entry_price))
    except (InvalidOperation, ValueError):
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Invalid entry price format.",
        )

    # Normalize direction
    direction_upper = direction.strip().upper()
    if direction_upper not in ("LONG", "SHORT"):
        return ValidationResult(
            is_valid=False,
            value=None,
            error="Direction must be 'LONG' or 'SHORT'.",
        )

    sl: Optional[Decimal] = None
    tp: Optional[Decimal] = None

    # Parse and validate SL if provided
    if sl_price is not None and str(sl_price).strip():
        try:
            sl = Decimal(str(sl_price))
        except (InvalidOperation, ValueError):
            return ValidationResult(
                is_valid=False,
                value=None,
                error="Invalid stop-loss price format.",
            )

        if sl <= 0:
            return ValidationResult(
                is_valid=False,
                value=None,
                error="Stop-loss price must be greater than zero.",
            )

        # Validate SL position based on direction
        if direction_upper == "LONG" and sl >= entry:
            return ValidationResult(
                is_valid=False,
                value=None,
                error="For LONG trades, stop-loss must be below entry price.",
            )
        if direction_upper == "SHORT" and sl <= entry:
            return ValidationResult(
                is_valid=False,
                value=None,
                error="For SHORT trades, stop-loss must be above entry price.",
            )

    # Parse and validate TP if provided
    if tp_price is not None and str(tp_price).strip():
        try:
            tp = Decimal(str(tp_price))
        except (InvalidOperation, ValueError):
            return ValidationResult(
                is_valid=False,
                value=None,
                error="Invalid take-profit price format.",
            )

        if tp <= 0:
            return ValidationResult(
                is_valid=False,
                value=None,
                error="Take-profit price must be greater than zero.",
            )

        # Validate TP position based on direction
        if direction_upper == "LONG" and tp <= entry:
            return ValidationResult(
                is_valid=False,
                value=None,
                error="For LONG trades, take-profit must be above entry price.",
            )
        if direction_upper == "SHORT" and tp >= entry:
            return ValidationResult(
                is_valid=False,
                value=None,
                error="For SHORT trades, take-profit must be below entry price.",
            )

    return ValidationResult(
        is_valid=True,
        value=(sl, tp),
        error=None,
    )
