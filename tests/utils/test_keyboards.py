"""
Tests for the keyboard utilities module.

This module tests all keyboard builder functions including:
- Main menu keyboard
- Account selection keyboard
- Instrument selection keyboard
- Direction selection keyboard
- Strategy selection keyboard
- Tag multi-select keyboard
- Confirmation and navigation keyboards
- Pagination keyboard
"""

import pytest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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


class TestMainMenuKeyboard:
    """Tests for main_menu_keyboard function."""

    def test_returns_inline_keyboard_markup(self):
        """Test that main_menu_keyboard returns an InlineKeyboardMarkup."""
        result = main_menu_keyboard()
        assert isinstance(result, InlineKeyboardMarkup)

    def test_has_at_least_8_buttons(self):
        """Test that main menu has at least 8 buttons as required."""
        result = main_menu_keyboard()
        total_buttons = sum(len(row) for row in result.inline_keyboard)
        assert total_buttons >= 8

    def test_contains_required_menu_options(self):
        """Test that main menu contains all required navigation options."""
        result = main_menu_keyboard()

        # Collect all button texts
        button_texts = []
        for row in result.inline_keyboard:
            for button in row:
                button_texts.append(button.text)

        required_options = [
            "Add Trade", "Open Trades", "Accounts", "Trade History",
            "Analytics", "Ask AI", "Strategies", "Tags",
            "Deposit/Withdraw", "Export", "Reminders", "Help"
        ]

        for option in required_options:
            assert option in button_texts, f"Missing required option: {option}"

    def test_callback_data_format(self):
        """Test that callback data uses menu_ prefix."""
        result = main_menu_keyboard()

        for row in result.inline_keyboard:
            for button in row:
                assert button.callback_data.startswith("menu_")


class TestBackToMenuKeyboard:
    """Tests for back_to_menu_keyboard function."""

    def test_returns_inline_keyboard_markup(self):
        """Test that back_to_menu_keyboard returns an InlineKeyboardMarkup."""
        result = back_to_menu_keyboard()
        assert isinstance(result, InlineKeyboardMarkup)

    def test_has_single_button(self):
        """Test that the keyboard has exactly one button with correct text."""
        result = back_to_menu_keyboard()

        # Should have exactly one row with one button
        assert len(result.inline_keyboard) == 1
        assert len(result.inline_keyboard[0]) == 1

        # Button should say "Back to Menu"
        button = result.inline_keyboard[0][0]
        assert button.text == "Back to Menu"

    def test_button_callback_data(self):
        """Test that the button has correct callback_data."""
        result = back_to_menu_keyboard()

        button = result.inline_keyboard[0][0]
        assert button.callback_data == "menu_home"

    def test_button_is_inline_keyboard_button(self):
        """Test that the button is an InlineKeyboardButton instance."""
        result = back_to_menu_keyboard()

        button = result.inline_keyboard[0][0]
        assert isinstance(button, InlineKeyboardButton)


class TestAccountSelectKeyboard:
    """Tests for account_select_keyboard function."""

    def test_empty_accounts_with_create(self):
        """Test keyboard with no accounts but create option."""
        result = account_select_keyboard([])

        assert isinstance(result, InlineKeyboardMarkup)

        # Should have create button and back button
        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "+ Create Account" in all_texts
        assert "Back" in all_texts

    def test_accounts_displayed(self):
        """Test that provided accounts are shown."""
        accounts = [(1, "Main Account"), (2, "Demo Account")]
        result = account_select_keyboard(accounts)

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "Main Account" in all_texts
        assert "Demo Account" in all_texts

    def test_account_callback_data_format(self):
        """Test that account buttons have correct callback data."""
        accounts = [(123, "Test Account")]
        result = account_select_keyboard(accounts)

        # Find the account button
        for row in result.inline_keyboard:
            for button in row:
                if button.text == "Test Account":
                    assert button.callback_data == "account_select_123"

    def test_without_create_option(self):
        """Test keyboard without create account option."""
        accounts = [(1, "Account")]
        result = account_select_keyboard(accounts, include_create=False)

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "+ Create Account" not in all_texts


class TestInstrumentKeyboard:
    """Tests for instrument_keyboard function."""

    def test_returns_inline_keyboard(self):
        """Test that instrument_keyboard returns an InlineKeyboardMarkup."""
        result = instrument_keyboard()
        assert isinstance(result, InlineKeyboardMarkup)

    def test_has_dax_and_nasdaq(self):
        """Test that DAX and NASDAQ buttons are present."""
        result = instrument_keyboard()

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "DAX" in all_texts
        assert "NASDAQ" in all_texts

    def test_has_navigation_buttons(self):
        """Test that back and cancel buttons are present."""
        result = instrument_keyboard()

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "Back" in all_texts
        assert "Cancel" in all_texts

    def test_instrument_callback_data_format(self):
        """Test that instrument buttons have correct callback data format."""
        result = instrument_keyboard()

        for row in result.inline_keyboard:
            for button in row:
                if button.text == "DAX":
                    assert button.callback_data == "instrument_DAX"
                if button.text == "NASDAQ":
                    assert button.callback_data == "instrument_NASDAQ"


class TestDirectionKeyboard:
    """Tests for direction_keyboard function."""

    def test_returns_inline_keyboard(self):
        """Test that direction_keyboard returns an InlineKeyboardMarkup."""
        result = direction_keyboard()
        assert isinstance(result, InlineKeyboardMarkup)

    def test_has_long_and_short(self):
        """Test that LONG and SHORT buttons are present."""
        result = direction_keyboard()

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "LONG" in all_texts
        assert "SHORT" in all_texts

    def test_direction_callback_data(self):
        """Test callback data for direction buttons."""
        result = direction_keyboard()

        for row in result.inline_keyboard:
            for button in row:
                if button.text == "LONG":
                    assert button.callback_data == "direction_long"
                if button.text == "SHORT":
                    assert button.callback_data == "direction_short"

    def test_has_navigation(self):
        """Test that navigation buttons are present."""
        result = direction_keyboard()

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "Back" in all_texts
        assert "Cancel" in all_texts


class TestStrategySelectKeyboard:
    """Tests for strategy_select_keyboard function."""

    def test_empty_strategies_with_skip(self):
        """Test keyboard with no strategies but skip option."""
        result = strategy_select_keyboard([])

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "Skip" in all_texts

    def test_strategies_displayed(self):
        """Test that strategies are shown."""
        strategies = [(1, "Scalping"), (2, "Swing")]
        result = strategy_select_keyboard(strategies)

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "Scalping" in all_texts
        assert "Swing" in all_texts

    def test_strategy_callback_data(self):
        """Test callback data format for strategies."""
        strategies = [(42, "Test Strategy")]
        result = strategy_select_keyboard(strategies)

        for row in result.inline_keyboard:
            for button in row:
                if button.text == "Test Strategy":
                    assert button.callback_data == "strategy_select_42"

    def test_without_skip_option(self):
        """Test keyboard without skip option."""
        strategies = [(1, "Strategy")]
        result = strategy_select_keyboard(strategies, include_skip=False)

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "Skip" not in all_texts


class TestTagSelectKeyboard:
    """Tests for tag_select_keyboard function."""

    def test_tags_displayed(self):
        """Test that tags are shown."""
        tags = [(1, "Breakout"), (2, "Reversal"), (3, "Trend")]
        result = tag_select_keyboard(tags)

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "Breakout" in all_texts
        assert "Reversal" in all_texts
        assert "Trend" in all_texts

    def test_selected_tags_have_checkmark(self):
        """Test that selected tags display with checkmark."""
        tags = [(1, "Tag1"), (2, "Tag2")]
        selected = {1}
        result = tag_select_keyboard(tags, selected_ids=selected)

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "[x] Tag1" in all_texts
        assert "Tag2" in all_texts  # Not selected, no checkmark

    def test_has_done_button(self):
        """Test that Done button is present."""
        tags = [(1, "Tag")]
        result = tag_select_keyboard(tags)

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "Done" in all_texts

    def test_tag_toggle_callback_data(self):
        """Test callback data format for tag toggles."""
        tags = [(99, "TestTag")]
        result = tag_select_keyboard(tags)

        for row in result.inline_keyboard:
            for button in row:
                if "TestTag" in button.text:
                    assert button.callback_data == "tag_toggle_99"


class TestConfirmationKeyboard:
    """Tests for confirmation_keyboard function."""

    def test_default_texts(self):
        """Test default confirm and cancel button texts."""
        result = confirmation_keyboard()

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "Confirm" in all_texts
        assert "Cancel" in all_texts

    def test_custom_texts(self):
        """Test custom button texts."""
        result = confirmation_keyboard(
            confirm_text="Yes, Delete",
            cancel_text="No, Keep",
        )

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "Yes, Delete" in all_texts
        assert "No, Keep" in all_texts

    def test_custom_callback_data(self):
        """Test custom callback data."""
        result = confirmation_keyboard(
            confirm_data="delete_confirm",
            cancel_data="delete_cancel",
        )

        callbacks = [btn.callback_data for row in result.inline_keyboard for btn in row]
        assert "delete_confirm" in callbacks
        assert "delete_cancel" in callbacks


class TestBackCancelKeyboard:
    """Tests for back_cancel_keyboard function."""

    def test_default_texts(self):
        """Test default back and cancel texts."""
        result = back_cancel_keyboard()

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "Back" in all_texts
        assert "Cancel" in all_texts

    def test_custom_texts(self):
        """Test custom button texts."""
        result = back_cancel_keyboard(
            back_text="Go Back",
            cancel_text="Exit",
        )

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "Go Back" in all_texts
        assert "Exit" in all_texts

    def test_custom_callback_data(self):
        """Test custom callback data."""
        result = back_cancel_keyboard(
            back_data="step_back",
            cancel_data="abort",
        )

        callbacks = [btn.callback_data for row in result.inline_keyboard for btn in row]
        assert "step_back" in callbacks
        assert "abort" in callbacks


class TestPaginationKeyboard:
    """Tests for pagination_keyboard function."""

    def test_shows_page_indicator(self):
        """Test that page indicator is shown."""
        result = pagination_keyboard(current_page=2, total_pages=5)

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "2/5" in all_texts

    def test_first_page_has_disabled_previous(self):
        """Test that first page has Previous pointing to noop."""
        result = pagination_keyboard(current_page=1, total_pages=5)

        for row in result.inline_keyboard:
            for button in row:
                if "Previous" in button.text:
                    assert "_noop" in button.callback_data

    def test_last_page_has_disabled_next(self):
        """Test that last page has Next pointing to noop."""
        result = pagination_keyboard(current_page=5, total_pages=5)

        for row in result.inline_keyboard:
            for button in row:
                if "Next" in button.text:
                    assert "_noop" in button.callback_data

    def test_middle_page_has_both_navigation(self):
        """Test that middle page has both Previous and Next enabled."""
        result = pagination_keyboard(current_page=3, total_pages=5, prefix="history")

        callbacks = [btn.callback_data for row in result.inline_keyboard for btn in row]
        assert "history_prev_2" in callbacks
        assert "history_next_4" in callbacks

    def test_custom_prefix(self):
        """Test that custom prefix is used in callback data."""
        result = pagination_keyboard(current_page=2, total_pages=5, prefix="trades")

        callbacks = [btn.callback_data for row in result.inline_keyboard for btn in row]
        # Should have trades_prev_1 since we're on page 2
        assert any("trades_" in cb for cb in callbacks)

    def test_has_back_to_menu_button(self):
        """Test that Back to Menu button is present."""
        result = pagination_keyboard(current_page=1, total_pages=1)

        all_texts = [btn.text for row in result.inline_keyboard for btn in row]
        assert "Back to Menu" in all_texts
