"""
Utilities package for the Telegram Trade Journal Bot.

This package contains utility modules for:
- keyboards: Telegram inline keyboard builders
- helpers: Formatting and calculation helpers
- validation: Input validation utilities
- constants: Strategy builder states and callback prefixes
"""

from utils.constants import (
    CB_BACK,
    CB_CREATE_STRATEGY,
    CB_DELETE_STRATEGY,
    CB_MAIN_MENU,
    CB_STRATEGIES,
    CB_STRATEGY_DETAIL,
    STATE_STRATEGY_CONFIRM,
    STATE_STRATEGY_FOLLOWUP,
    STATE_STRATEGY_NAME,
    STATE_STRATEGY_SECTION_A,
    STATE_STRATEGY_SECTION_B,
    STATE_STRATEGY_SECTION_C,
    STATE_STRATEGY_SECTION_D,
)
from utils.helpers import (
    calculate_pnl,
    calculate_pnl_percent,
    calculate_risk_reward,
    escape_markdown,
    format_currency,
    format_date,
    format_datetime,
    format_percentage,
    format_trade_summary,
    truncate_text,
)
from utils.keyboards import (
    account_select_keyboard,
    back_cancel_keyboard,
    back_to_menu_keyboard,
    confirmation_keyboard,
    direction_keyboard,
    instrument_keyboard,
    main_menu_keyboard,
    pagination_keyboard,
    strategy_select_keyboard,
    tag_select_keyboard,
)
from utils.validation import (
    ValidationResult,
    validate_account_name,
    validate_currency,
    validate_direction,
    validate_instrument,
    validate_lot_size,
    validate_price,
    validate_sl_tp,
    validate_time_format,
)

__all__ = [
    # Constants - Strategy builder states
    "STATE_STRATEGY_SECTION_A",
    "STATE_STRATEGY_SECTION_B",
    "STATE_STRATEGY_SECTION_C",
    "STATE_STRATEGY_SECTION_D",
    "STATE_STRATEGY_FOLLOWUP",
    "STATE_STRATEGY_CONFIRM",
    "STATE_STRATEGY_NAME",
    # Constants - Callback prefixes
    "CB_STRATEGIES",
    "CB_STRATEGY_DETAIL",
    "CB_CREATE_STRATEGY",
    "CB_DELETE_STRATEGY",
    "CB_MAIN_MENU",
    "CB_BACK",
    # Keyboards
    "main_menu_keyboard",
    "back_to_menu_keyboard",
    "account_select_keyboard",
    "instrument_keyboard",
    "direction_keyboard",
    "strategy_select_keyboard",
    "tag_select_keyboard",
    "confirmation_keyboard",
    "back_cancel_keyboard",
    "pagination_keyboard",
    # Helpers
    "format_currency",
    "format_percentage",
    "format_datetime",
    "format_date",
    "calculate_pnl",
    "calculate_pnl_percent",
    "calculate_risk_reward",
    "format_trade_summary",
    "truncate_text",
    "escape_markdown",
    # Validation
    "ValidationResult",
    "validate_price",
    "validate_lot_size",
    "validate_instrument",
    "validate_account_name",
    "validate_currency",
    "validate_time_format",
    "validate_direction",
    "validate_sl_tp",
]
