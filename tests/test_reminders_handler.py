"""
Tests for reminder handlers.

Tests cover:
- Reminder menu display
- Reminder view/toggle/delete
- Add reminder flow
- Keyboard generation
"""

from datetime import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers.reminders import (
    MAX_REMINDERS,
    get_next_reminder_time,
    is_default_reminder,
    reminder_confirm_delete_keyboard,
    reminder_detail_keyboard,
    reminders_menu_keyboard,
)
from services.reminder_service import DEFAULT_REMINDERS


class TestIsDefaultReminder:
    """Tests for is_default_reminder function."""

    def test_recognizes_morning_default(self):
        """Test 08:00 is recognized as default."""
        assert is_default_reminder(time(8, 0)) is True

    def test_recognizes_session_default(self):
        """Test 10:00 is recognized as default."""
        assert is_default_reminder(time(10, 0)) is True

    def test_recognizes_review_default(self):
        """Test 15:00 is recognized as default."""
        assert is_default_reminder(time(15, 0)) is True

    def test_rejects_non_default(self):
        """Test custom time is not recognized as default."""
        assert is_default_reminder(time(9, 30)) is False
        assert is_default_reminder(time(12, 0)) is False
        assert is_default_reminder(time(20, 0)) is False


class TestGetNextReminderTime:
    """Tests for get_next_reminder_time function."""

    def test_returns_none_for_empty_list(self):
        """Test returns None when no reminders."""
        result = get_next_reminder_time([])
        assert result is None

    def test_returns_none_when_all_disabled(self):
        """Test returns None when all reminders disabled."""
        reminders = [
            (1, time(8, 0), False),
            (2, time(10, 0), False),
        ]
        result = get_next_reminder_time(reminders)
        assert result is None

    def test_returns_next_enabled_reminder(self):
        """Test returns next enabled reminder."""
        # Use times that should be in the future
        reminders = [
            (1, time(8, 0), True),
            (2, time(23, 59), True),  # Late time
        ]
        result = get_next_reminder_time(reminders)
        assert result is not None
        assert isinstance(result[0], time)
        assert isinstance(result[1], str)


class TestRemindersMenuKeyboard:
    """Tests for reminders_menu_keyboard function."""

    def test_shows_reminder_with_status(self):
        """Test keyboard shows reminder with ON/OFF status."""
        reminders = [
            (1, time(8, 0), True),
            (2, time(10, 0), False),
        ]
        keyboard = reminders_menu_keyboard(reminders)

        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert any("[ON]" in b and "08:00" in b for b in buttons)
        assert any("[OFF]" in b and "10:00" in b for b in buttons)

    def test_shows_add_button_when_under_limit(self):
        """Test Add Reminder button shown when under limit."""
        reminders = [(1, time(8, 0), True)]
        keyboard = reminders_menu_keyboard(reminders, show_add=True)

        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert "+ Add Reminder" in buttons

    def test_hides_add_button_at_limit(self):
        """Test Add Reminder hidden at max limit."""
        reminders = [(i, time(i, 0), True) for i in range(MAX_REMINDERS)]
        keyboard = reminders_menu_keyboard(reminders, show_add=True)

        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert "+ Add Reminder" not in buttons

    def test_hides_add_button_when_disabled(self):
        """Test Add Reminder hidden when show_add=False."""
        reminders = [(1, time(8, 0), True)]
        keyboard = reminders_menu_keyboard(reminders, show_add=False)

        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert "+ Add Reminder" not in buttons

    def test_includes_back_button(self):
        """Test keyboard includes back button."""
        reminders = []
        keyboard = reminders_menu_keyboard(reminders)

        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert "Back to Menu" in buttons


class TestReminderDetailKeyboard:
    """Tests for reminder_detail_keyboard function."""

    def test_shows_disable_when_enabled(self):
        """Test shows Disable button when reminder is enabled."""
        keyboard = reminder_detail_keyboard(1, is_enabled=True)

        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert "Disable" in buttons

    def test_shows_enable_when_disabled(self):
        """Test shows Enable button when reminder is disabled."""
        keyboard = reminder_detail_keyboard(1, is_enabled=False)

        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert "Enable" in buttons

    def test_shows_delete_for_non_default(self):
        """Test Delete button shown for non-default reminders."""
        keyboard = reminder_detail_keyboard(1, is_enabled=True, is_default=False)

        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert "Delete" in buttons

    def test_hides_delete_for_default(self):
        """Test Delete button hidden for default reminders."""
        keyboard = reminder_detail_keyboard(1, is_enabled=True, is_default=True)

        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert "Delete" not in buttons

    def test_includes_back_button(self):
        """Test keyboard includes back button."""
        keyboard = reminder_detail_keyboard(1, is_enabled=True)

        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert "Back to Reminders" in buttons


class TestReminderConfirmDeleteKeyboard:
    """Tests for reminder_confirm_delete_keyboard function."""

    def test_has_yes_and_no_buttons(self):
        """Test keyboard has confirmation and cancel buttons."""
        keyboard = reminder_confirm_delete_keyboard(1)

        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert "Yes, Delete" in buttons
        assert "No, Keep It" in buttons

    def test_buttons_have_correct_callbacks(self):
        """Test buttons have correct callback data."""
        keyboard = reminder_confirm_delete_keyboard(1)

        callbacks = []
        for row in keyboard.inline_keyboard:
            for button in row:
                callbacks.append(button.callback_data)

        assert "reminder_confirm_delete_1" in callbacks
        assert "reminder_view_1" in callbacks


class TestMaxRemindersConstant:
    """Tests for MAX_REMINDERS constant."""

    def test_max_reminders_is_10(self):
        """Test max reminders limit is 10."""
        assert MAX_REMINDERS == 10

    def test_max_reminders_allows_defaults(self):
        """Test max is larger than number of defaults."""
        assert MAX_REMINDERS >= len(DEFAULT_REMINDERS)
