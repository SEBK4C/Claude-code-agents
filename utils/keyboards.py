"""
Telegram keyboard utilities for the Trade Journal Bot.

This module provides functions to create InlineKeyboardMarkup objects
for various bot interactions including menus, selections, and navigation.
"""

from typing import Optional, Sequence

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Create the main dashboard keyboard with all primary navigation options.

    Returns:
        InlineKeyboardMarkup: The main menu keyboard with 8+ buttons arranged
        in a user-friendly grid layout.
    """
    keyboard = [
        [
            InlineKeyboardButton("Add Trade", callback_data="menu_add_trade"),
            InlineKeyboardButton("Open Trades", callback_data="menu_open_trades"),
        ],
        [
            InlineKeyboardButton("Accounts", callback_data="menu_accounts"),
            InlineKeyboardButton("Trade History", callback_data="menu_history"),
        ],
        [
            InlineKeyboardButton("Analytics", callback_data="menu_analytics"),
            InlineKeyboardButton("Ask AI", callback_data="menu_ask_ai"),
        ],
        [
            InlineKeyboardButton("Strategies", callback_data="menu_strategies"),
            InlineKeyboardButton("Tags", callback_data="menu_tags"),
        ],
        [
            InlineKeyboardButton("Deposit/Withdraw", callback_data="menu_transactions"),
            InlineKeyboardButton("Export", callback_data="menu_export"),
        ],
        [
            InlineKeyboardButton("Reminders", callback_data="menu_reminders"),
            InlineKeyboardButton("Help", callback_data="menu_help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Create a keyboard with a single "Back to Menu" button.

    This keyboard is used to provide users a quick way to return to the
    main menu from any screen.

    Returns:
        InlineKeyboardMarkup: A keyboard with a single "Back to Menu" button.
    """
    keyboard = [
        [InlineKeyboardButton("Back to Menu", callback_data="menu_home")],
    ]
    return InlineKeyboardMarkup(keyboard)


def account_select_keyboard(
    accounts: Sequence[tuple[int, str]],
    include_create: bool = True,
) -> InlineKeyboardMarkup:
    """
    Create a keyboard for selecting a trading account.

    Args:
        accounts: A sequence of (account_id, account_name) tuples.
        include_create: Whether to include a "Create Account" button.

    Returns:
        InlineKeyboardMarkup: A keyboard with account buttons and optional
        create account button.
    """
    keyboard = []

    # Add account buttons (one per row for clarity)
    for account_id, account_name in accounts:
        keyboard.append([
            InlineKeyboardButton(
                account_name,
                callback_data=f"account_select_{account_id}",
            )
        ])

    # Add create account option if requested
    if include_create:
        keyboard.append([
            InlineKeyboardButton(
                "+ Create Account",
                callback_data="account_create",
            )
        ])

    # Add back button
    keyboard.append([
        InlineKeyboardButton("Back", callback_data="back")
    ])

    return InlineKeyboardMarkup(keyboard)


def instrument_keyboard() -> InlineKeyboardMarkup:
    """
    Create a keyboard for selecting a trading instrument.

    Returns:
        InlineKeyboardMarkup: A keyboard with DAX, NASDAQ, and custom input options.
    """
    keyboard = [
        [
            InlineKeyboardButton("DAX", callback_data="instrument_DAX"),
            InlineKeyboardButton("NASDAQ", callback_data="instrument_NASDAQ"),
        ],
        [
            InlineKeyboardButton("S&P 500", callback_data="instrument_SP500"),
            InlineKeyboardButton("DOW", callback_data="instrument_DOW"),
        ],
        [
            InlineKeyboardButton("EUR/USD", callback_data="instrument_EURUSD"),
            InlineKeyboardButton("GBP/USD", callback_data="instrument_GBPUSD"),
        ],
        [
            InlineKeyboardButton("Custom...", callback_data="instrument_custom"),
        ],
        [
            InlineKeyboardButton("Back", callback_data="back"),
            InlineKeyboardButton("Cancel", callback_data="cancel"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def direction_keyboard() -> InlineKeyboardMarkup:
    """
    Create a keyboard for selecting trade direction.

    Returns:
        InlineKeyboardMarkup: A keyboard with LONG (green-styled text) and
        SHORT (red-styled text) buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton("LONG", callback_data="direction_long"),
            InlineKeyboardButton("SHORT", callback_data="direction_short"),
        ],
        [
            InlineKeyboardButton("Back", callback_data="back"),
            InlineKeyboardButton("Cancel", callback_data="cancel"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def strategy_select_keyboard(
    strategies: Sequence[tuple[int, str]],
    include_skip: bool = True,
) -> InlineKeyboardMarkup:
    """
    Create a keyboard for selecting a trading strategy.

    Args:
        strategies: A sequence of (strategy_id, strategy_name) tuples.
        include_skip: Whether to include a "Skip" button for optional selection.

    Returns:
        InlineKeyboardMarkup: A keyboard with strategy buttons and optional skip button.
    """
    keyboard = []

    # Add strategy buttons (one per row)
    for strategy_id, strategy_name in strategies:
        keyboard.append([
            InlineKeyboardButton(
                strategy_name,
                callback_data=f"strategy_select_{strategy_id}",
            )
        ])

    # Add skip option if requested
    if include_skip:
        keyboard.append([
            InlineKeyboardButton("Skip", callback_data="strategy_skip")
        ])

    # Add navigation
    keyboard.append([
        InlineKeyboardButton("Back", callback_data="back"),
        InlineKeyboardButton("Cancel", callback_data="cancel"),
    ])

    return InlineKeyboardMarkup(keyboard)


def tag_select_keyboard(
    tags: Sequence[tuple[int, str]],
    selected_ids: Optional[set[int]] = None,
) -> InlineKeyboardMarkup:
    """
    Create a multi-select keyboard for selecting tags.

    Args:
        tags: A sequence of (tag_id, tag_name) tuples.
        selected_ids: A set of currently selected tag IDs for checkmark display.

    Returns:
        InlineKeyboardMarkup: A keyboard with tag buttons showing checkmarks
        for selected tags and a Done button.
    """
    if selected_ids is None:
        selected_ids = set()

    keyboard = []

    # Add tag buttons in pairs (2 per row)
    row = []
    for tag_id, tag_name in tags:
        # Add checkmark for selected tags
        display_name = f"[x] {tag_name}" if tag_id in selected_ids else tag_name
        row.append(
            InlineKeyboardButton(
                display_name,
                callback_data=f"tag_toggle_{tag_id}",
            )
        )

        # Two buttons per row
        if len(row) == 2:
            keyboard.append(row)
            row = []

    # Add remaining button if odd number
    if row:
        keyboard.append(row)

    # Add done and cancel buttons
    keyboard.append([
        InlineKeyboardButton("Done", callback_data="tags_done"),
        InlineKeyboardButton("Clear All", callback_data="tags_clear"),
    ])
    keyboard.append([
        InlineKeyboardButton("Back", callback_data="back"),
        InlineKeyboardButton("Cancel", callback_data="cancel"),
    ])

    return InlineKeyboardMarkup(keyboard)


def confirmation_keyboard(
    confirm_text: str = "Confirm",
    cancel_text: str = "Cancel",
    confirm_data: str = "confirm",
    cancel_data: str = "cancel",
) -> InlineKeyboardMarkup:
    """
    Create a confirmation keyboard with Confirm and Cancel buttons.

    Args:
        confirm_text: Text for the confirm button.
        cancel_text: Text for the cancel button.
        confirm_data: Callback data for the confirm button.
        cancel_data: Callback data for the cancel button.

    Returns:
        InlineKeyboardMarkup: A keyboard with confirm and cancel buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton(confirm_text, callback_data=confirm_data),
            InlineKeyboardButton(cancel_text, callback_data=cancel_data),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def back_cancel_keyboard(
    back_text: str = "Back",
    cancel_text: str = "Cancel",
    back_data: str = "back",
    cancel_data: str = "cancel",
) -> InlineKeyboardMarkup:
    """
    Create a navigation keyboard with Back and Cancel buttons.

    Args:
        back_text: Text for the back button.
        cancel_text: Text for the cancel button.
        back_data: Callback data for the back button.
        cancel_data: Callback data for the cancel button.

    Returns:
        InlineKeyboardMarkup: A keyboard with back and cancel buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton(back_text, callback_data=back_data),
            InlineKeyboardButton(cancel_text, callback_data=cancel_data),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def pagination_keyboard(
    current_page: int,
    total_pages: int,
    prefix: str = "page",
) -> InlineKeyboardMarkup:
    """
    Create a pagination keyboard for navigating through pages of content.

    Args:
        current_page: The current page number (1-indexed).
        total_pages: The total number of pages.
        prefix: A prefix for callback data to namespace the pagination.

    Returns:
        InlineKeyboardMarkup: A keyboard with Previous/Next buttons and
        page indicator. Buttons are disabled when at boundaries.
    """
    keyboard = []
    nav_row = []

    # Previous button (disabled on first page)
    if current_page > 1:
        nav_row.append(
            InlineKeyboardButton(
                "< Previous",
                callback_data=f"{prefix}_prev_{current_page - 1}",
            )
        )
    else:
        nav_row.append(
            InlineKeyboardButton(
                "< Previous",
                callback_data=f"{prefix}_noop",
            )
        )

    # Page indicator
    nav_row.append(
        InlineKeyboardButton(
            f"{current_page}/{total_pages}",
            callback_data=f"{prefix}_noop",
        )
    )

    # Next button (disabled on last page)
    if current_page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                "Next >",
                callback_data=f"{prefix}_next_{current_page + 1}",
            )
        )
    else:
        nav_row.append(
            InlineKeyboardButton(
                "Next >",
                callback_data=f"{prefix}_noop",
            )
        )

    keyboard.append(nav_row)

    # Add back button
    keyboard.append([
        InlineKeyboardButton("Back to Menu", callback_data="menu_main")
    ])

    return InlineKeyboardMarkup(keyboard)
