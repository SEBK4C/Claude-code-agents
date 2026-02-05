"""
Tests for the AI chat handlers module.

This module tests:
- AI chat keyboard structure and button configuration
- Clear History button presence and callback data
- Button ordering in the keyboard
"""

import pytest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.ai_chat import ai_chat_keyboard


class TestAiChatKeyboard:
    """Tests for ai_chat_keyboard function."""

    def test_returns_inline_keyboard_markup(self):
        """Test that ai_chat_keyboard returns an InlineKeyboardMarkup."""
        result = ai_chat_keyboard()
        assert isinstance(result, InlineKeyboardMarkup)

    def test_ai_chat_keyboard_has_clear_history_button(self):
        """Test that Clear History button exists with correct callback_data."""
        result = ai_chat_keyboard()

        # Collect all buttons with their callback data
        buttons = []
        for row in result.inline_keyboard:
            for button in row:
                buttons.append((button.text, button.callback_data))

        # Find the Clear History button
        clear_history_buttons = [
            (text, data) for text, data in buttons if "Clear History" in text
        ]

        assert len(clear_history_buttons) == 1, "Should have exactly one Clear History button"
        text, callback_data = clear_history_buttons[0]
        assert callback_data == "ai_clear_history", "Clear History should have ai_clear_history callback_data"

    def test_ai_chat_keyboard_has_back_to_menu_button(self):
        """Test that Back to Menu button exists with correct callback_data."""
        result = ai_chat_keyboard()

        # Collect all buttons with their callback data
        buttons = []
        for row in result.inline_keyboard:
            for button in row:
                buttons.append((button.text, button.callback_data))

        # Find the Back to Menu button
        back_buttons = [
            (text, data) for text, data in buttons if text == "Back to Menu"
        ]

        assert len(back_buttons) == 1, "Should have exactly one Back to Menu button"
        text, callback_data = back_buttons[0]
        assert callback_data == "menu_main", "Back to Menu should have menu_main callback_data"

    def test_ai_chat_keyboard_button_order(self):
        """Test that Clear History is first row, Back to Menu is second row."""
        result = ai_chat_keyboard()

        # Should have exactly 2 rows
        assert len(result.inline_keyboard) == 2, "Keyboard should have exactly 2 rows"

        # First row should have Clear History
        first_row = result.inline_keyboard[0]
        assert len(first_row) == 1, "First row should have 1 button"
        assert first_row[0].text == "Clear History", "First button should be Clear History"
        assert first_row[0].callback_data == "ai_clear_history"

        # Second row should have Back to Menu
        second_row = result.inline_keyboard[1]
        assert len(second_row) == 1, "Second row should have 1 button"
        assert second_row[0].text == "Back to Menu", "Second button should be Back to Menu"
        assert second_row[0].callback_data == "menu_main"

    def test_ai_chat_keyboard_buttons_are_inline_keyboard_buttons(self):
        """Test that all buttons are InlineKeyboardButton instances."""
        result = ai_chat_keyboard()

        for row in result.inline_keyboard:
            for button in row:
                assert isinstance(button, InlineKeyboardButton)

    def test_ai_chat_keyboard_has_exactly_two_buttons(self):
        """Test that the keyboard has exactly two buttons total."""
        result = ai_chat_keyboard()

        total_buttons = sum(len(row) for row in result.inline_keyboard)
        assert total_buttons == 2, "Keyboard should have exactly 2 buttons"
