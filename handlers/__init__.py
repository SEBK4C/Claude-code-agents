"""
Handlers package for the Telegram Trade Journal Bot.

This package contains all Telegram bot handlers including:
- start: Start command and main dashboard
- accounts: Account creation and management
- trades: Trade entry wizard, close flow, and history
- tags: Tag management
- strategies: Strategy management and AI builder
- ai_chat: AI conversation mode
- analytics: Analytics dashboard and charts
- export: CSV, JSON, and PDF export
- reminders: Reminder schedule management
"""

from handlers.accounts import (
    account_create_conversation,
    handle_account_delete_confirm,
    handle_account_detail,
    handle_account_edit,
    handle_accounts_menu,
    handle_deposit_withdraw,
    handle_transaction_amount,
)
from handlers.ai_chat import ai_chat_conversation
from handlers.analytics import (
    handle_analytics_account,
    handle_analytics_charts,
    handle_analytics_filter,
    handle_analytics_instruments,
    handle_analytics_menu,
    handle_analytics_overview,
    handle_analytics_patterns,
    handle_analytics_performance,
    handle_analytics_range,
    handle_analytics_risk,
    handle_chart_dow,
    handle_chart_download_all,
    handle_chart_drawdown,
    handle_chart_equity,
    handle_chart_hour,
    handle_chart_instruments,
    handle_chart_pie,
)
from handlers.start import (
    handle_help_callback,
    handle_menu_home,
    help_command,
    start_command,
)
from handlers.strategies import (
    ai_strategy_conversation,
    create_strategy_callback,
    get_strategy_builder_handlers,
    handle_strategies_menu,
    handle_strategy_delete,
    handle_strategy_edit_cancel,
    handle_strategy_edit_desc,
    handle_strategy_edit_input,
    handle_strategy_edit_name,
    handle_strategy_edit_rules,
    handle_strategy_name_input,
    handle_strategy_section_response,
    handle_strategy_view,
    skip_section_callback,
    strategy_create_conversation,
)
from handlers.tags import (
    handle_tag_delete,
    handle_tag_toggle_default,
    handle_tag_view,
    handle_tags_menu,
    tag_create_conversation,
)
from handlers.trades import (
    close_trade_conversation,
    handle_edit_cancel,
    handle_edit_direction,
    handle_edit_direction_select,
    handle_edit_entry,
    handle_edit_exit,
    handle_edit_input,
    handle_edit_instrument,
    handle_edit_instrument_select,
    handle_edit_lotsize,
    handle_edit_menu,
    handle_edit_notes,
    handle_edit_sl,
    handle_edit_tp,
    handle_edit_screenshot,
    handle_edit_strategy,
    handle_edit_strategy_clear,
    handle_edit_strategy_select,
    handle_edit_tag_toggle,
    handle_edit_tags,
    handle_edit_tags_clear,
    handle_edit_tags_save,
    handle_open_trades,
    handle_open_trades_filter,
    handle_screenshot_remove,
    handle_screenshot_replace,
    handle_screenshot_upload,
    handle_trade_delete,
    handle_trade_detail,
    handle_trade_history,
    register_price_alert_callback,
    trade_entry_conversation,
)
from handlers.export import export_conversation
from handlers.reminders import (
    handle_reminder_confirm_delete,
    handle_reminder_delete,
    handle_reminder_toggle,
    handle_reminder_view,
    handle_reminders_menu,
    reminder_add_conversation,
)
from handlers.natural_input import (
    handle_missing_field_response,
    handle_natural_account_callback,
    handle_natural_cancel_callback,
    handle_natural_close_select_callback,
    handle_natural_confirm_callback,
    handle_natural_direction_callback,
    handle_natural_trade_input,
    NATURAL_TRADE_KEY,
    NATURAL_TRADE_STATE_KEY,
)

__all__ = [
    # Start handlers
    "start_command",
    "help_command",
    "handle_menu_home",
    "handle_help_callback",
    # Account handlers
    "account_create_conversation",
    "handle_accounts_menu",
    "handle_account_detail",
    "handle_account_edit",
    "handle_account_delete_confirm",
    "handle_deposit_withdraw",
    "handle_transaction_amount",
    # Trade handlers
    "trade_entry_conversation",
    "close_trade_conversation",
    "handle_open_trades",
    "handle_trade_history",
    "handle_trade_detail",
    "handle_trade_delete",
    "handle_open_trades_filter",
    "handle_edit_menu",
    "handle_edit_sl",
    "handle_edit_tp",
    "handle_edit_notes",
    "handle_edit_input",
    "handle_edit_cancel",
    "handle_edit_instrument",
    "handle_edit_instrument_select",
    "handle_edit_direction",
    "handle_edit_direction_select",
    "handle_edit_entry",
    "handle_edit_lotsize",
    "handle_edit_exit",
    "handle_edit_screenshot",
    "handle_edit_tags",
    "handle_edit_tag_toggle",
    "handle_edit_tags_clear",
    "handle_edit_tags_save",
    "handle_edit_strategy",
    "handle_edit_strategy_select",
    "handle_edit_strategy_clear",
    "handle_screenshot_replace",
    "handle_screenshot_remove",
    "handle_screenshot_upload",
    "register_price_alert_callback",
    # Tag handlers
    "tag_create_conversation",
    "handle_tags_menu",
    "handle_tag_view",
    "handle_tag_toggle_default",
    "handle_tag_delete",
    # Strategy handlers
    "strategy_create_conversation",
    "ai_strategy_conversation",
    "handle_strategies_menu",
    "handle_strategy_view",
    "handle_strategy_edit_name",
    "handle_strategy_edit_desc",
    "handle_strategy_edit_rules",
    "handle_strategy_edit_input",
    "handle_strategy_edit_cancel",
    "handle_strategy_delete",
    # New AI Strategy Builder handlers
    "create_strategy_callback",
    "handle_strategy_section_response",
    "skip_section_callback",
    "handle_strategy_name_input",
    "get_strategy_builder_handlers",
    # AI Chat handlers
    "ai_chat_conversation",
    # Analytics handlers
    "handle_analytics_menu",
    "handle_analytics_overview",
    "handle_analytics_performance",
    "handle_analytics_risk",
    "handle_analytics_patterns",
    "handle_analytics_instruments",
    "handle_analytics_filter",
    "handle_analytics_range",
    "handle_analytics_account",
    "handle_analytics_charts",
    "handle_chart_equity",
    "handle_chart_pie",
    "handle_chart_instruments",
    "handle_chart_drawdown",
    "handle_chart_dow",
    "handle_chart_hour",
    "handle_chart_download_all",
    # Export handlers
    "export_conversation",
    # Reminder handlers
    "handle_reminders_menu",
    "handle_reminder_view",
    "handle_reminder_toggle",
    "handle_reminder_delete",
    "handle_reminder_confirm_delete",
    "reminder_add_conversation",
    # Natural input handlers
    "handle_natural_trade_input",
    "handle_missing_field_response",
    "handle_natural_direction_callback",
    "handle_natural_account_callback",
    "handle_natural_close_select_callback",
    "handle_natural_confirm_callback",
    "handle_natural_cancel_callback",
    "NATURAL_TRADE_KEY",
    "NATURAL_TRADE_STATE_KEY",
]
