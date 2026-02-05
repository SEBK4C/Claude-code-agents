"""
Tests for export handlers.

Tests cover:
- CSV export generation
- JSON export generation
- PDF export generation
- Export conversation flow
"""

import csv
import io
import json
from datetime import datetime, time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database.models import Account, Strategy, Tag, Trade, TradeDirection, TradeStatus, TradeTag, User
from handlers.export import (
    DecimalEncoder,
    generate_csv_export,
    generate_json_export,
    get_date_range,
)


class TestDecimalEncoder:
    """Tests for the DecimalEncoder class."""

    def test_encodes_decimal_to_float(self):
        """Test that Decimal values are encoded as floats."""
        encoder = DecimalEncoder()
        data = {"value": Decimal("123.45")}
        result = json.dumps(data, cls=DecimalEncoder)
        assert '"value": 123.45' in result

    def test_encodes_datetime(self):
        """Test that datetime values are encoded as ISO format strings."""
        encoder = DecimalEncoder()
        dt = datetime(2024, 1, 15, 14, 30, 0)
        data = {"timestamp": dt}
        result = json.dumps(data, cls=DecimalEncoder)
        assert "2024-01-15T14:30:00" in result

    def test_passes_through_standard_types(self):
        """Test that standard JSON types are handled normally."""
        data = {"string": "test", "number": 42, "array": [1, 2, 3]}
        result = json.dumps(data, cls=DecimalEncoder)
        parsed = json.loads(result)
        assert parsed == data


class TestGetDateRange:
    """Tests for the get_date_range function."""

    def test_week_range(self):
        """Test week date range calculation."""
        start, end = get_date_range("week")
        assert start is not None
        assert end is not None
        assert start <= end
        # Start should be a Monday
        assert start.weekday() == 0

    def test_month_range(self):
        """Test month date range calculation."""
        start, end = get_date_range("month")
        assert start is not None
        assert end is not None
        # Start should be first of month
        assert start.day == 1

    def test_3months_range(self):
        """Test 3 months date range calculation."""
        start, end = get_date_range("3months")
        assert start is not None
        assert end is not None
        # Should be approximately 90 days apart
        diff = (end - start).days
        assert 85 <= diff <= 95

    def test_year_range(self):
        """Test year date range calculation."""
        start, end = get_date_range("year")
        assert start is not None
        assert end is not None
        # Start should be January 1
        assert start.month == 1
        assert start.day == 1

    def test_all_range(self):
        """Test all time range returns None values."""
        start, end = get_date_range("all")
        assert start is None
        assert end is None


class TestGenerateCsvExport:
    """Tests for CSV export generation."""

    def test_generates_csv_with_header(self):
        """Test that CSV includes proper header row."""
        # Create mock trade
        mock_account = MagicMock()
        mock_account.name = "Test Account"

        mock_trade = MagicMock()
        mock_trade.id = 1
        mock_trade.account = mock_account
        mock_trade.instrument = "EURUSD"
        mock_trade.direction = TradeDirection.LONG
        mock_trade.entry_price = Decimal("1.1000")
        mock_trade.exit_price = Decimal("1.1050")
        mock_trade.sl_price = Decimal("1.0950")
        mock_trade.tp_price = Decimal("1.1100")
        mock_trade.lot_size = Decimal("1.0")
        mock_trade.pnl = Decimal("50.00")
        mock_trade.pnl_percent = Decimal("0.45")
        mock_trade.strategy = None
        mock_trade.trade_tags = []
        mock_trade.notes = "Test trade"
        mock_trade.opened_at = datetime(2024, 1, 15, 10, 0, 0)
        mock_trade.closed_at = datetime(2024, 1, 15, 14, 0, 0)

        result = generate_csv_export([mock_trade])

        # Parse CSV
        reader = csv.reader(io.StringIO(result.decode("utf-8")))
        rows = list(reader)

        # Check header
        assert rows[0] == [
            "id", "account", "instrument", "direction", "entry_price",
            "exit_price", "sl", "tp", "lot_size", "pnl", "pnl_percent",
            "strategy", "tags", "notes", "opened_at", "closed_at"
        ]

        # Check data row
        assert rows[1][0] == "1"
        assert rows[1][1] == "Test Account"
        assert rows[1][2] == "EURUSD"
        assert rows[1][3] == "long"

    def test_handles_empty_trades(self):
        """Test CSV generation with no trades."""
        result = generate_csv_export([])

        reader = csv.reader(io.StringIO(result.decode("utf-8")))
        rows = list(reader)

        # Should only have header
        assert len(rows) == 1

    def test_handles_trades_with_tags(self):
        """Test CSV includes comma-separated tags."""
        mock_account = MagicMock()
        mock_account.name = "Test"

        mock_tag1 = MagicMock()
        mock_tag1.name = "breakout"
        mock_tag2 = MagicMock()
        mock_tag2.name = "trend"

        mock_trade_tag1 = MagicMock()
        mock_trade_tag1.tag = mock_tag1
        mock_trade_tag2 = MagicMock()
        mock_trade_tag2.tag = mock_tag2

        mock_trade = MagicMock()
        mock_trade.id = 1
        mock_trade.account = mock_account
        mock_trade.instrument = "DAX"
        mock_trade.direction = TradeDirection.SHORT
        mock_trade.entry_price = Decimal("18000")
        mock_trade.exit_price = Decimal("17900")
        mock_trade.sl_price = None
        mock_trade.tp_price = None
        mock_trade.lot_size = Decimal("0.5")
        mock_trade.pnl = Decimal("100.00")
        mock_trade.pnl_percent = Decimal("0.55")
        mock_trade.strategy = None
        mock_trade.trade_tags = [mock_trade_tag1, mock_trade_tag2]
        mock_trade.notes = None
        mock_trade.opened_at = datetime(2024, 1, 15, 10, 0, 0)
        mock_trade.closed_at = datetime(2024, 1, 15, 14, 0, 0)

        result = generate_csv_export([mock_trade])

        reader = csv.reader(io.StringIO(result.decode("utf-8")))
        rows = list(reader)

        # Tags should be comma-separated
        assert rows[1][12] == "breakout,trend"


class TestGenerateJsonExport:
    """Tests for JSON export generation."""

    @pytest.mark.asyncio
    async def test_json_structure(self):
        """Test JSON export has correct structure."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

        result = await generate_json_export(mock_session, [], user_id=1)
        data = json.loads(result.decode("utf-8"))

        assert "metadata" in data
        assert "accounts" in data
        assert "trades" in data
        assert data["metadata"]["trade_count"] == 0

    @pytest.mark.asyncio
    async def test_json_metadata_fields(self):
        """Test JSON metadata contains required fields."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

        result = await generate_json_export(mock_session, [], user_id=1)
        data = json.loads(result.decode("utf-8"))

        assert "export_date" in data["metadata"]
        assert "trade_count" in data["metadata"]
        assert "export_type" in data["metadata"]
        assert "version" in data["metadata"]


class TestExportConversation:
    """Tests for export conversation handlers."""

    @pytest.mark.asyncio
    async def test_export_menu_shows_formats(self):
        """Test export menu displays format options."""
        from handlers.export import export_format_keyboard

        keyboard = export_format_keyboard()
        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert "CSV" in buttons
        assert "JSON" in buttons
        assert "PDF Report" in buttons

    def test_export_account_keyboard_includes_all_accounts(self):
        """Test account selection includes All Accounts option."""
        from handlers.export import export_account_keyboard

        accounts = [(1, "Account 1"), (2, "Account 2")]
        keyboard = export_account_keyboard(accounts)

        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert "All Accounts" in buttons
        assert "Account 1" in buttons
        assert "Account 2" in buttons

    def test_export_date_range_keyboard_options(self):
        """Test date range keyboard has all options."""
        from handlers.export import export_date_range_keyboard

        keyboard = export_date_range_keyboard()
        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.text)

        assert "This Week" in buttons
        assert "This Month" in buttons
        assert "Last 3 Months" in buttons
        assert "This Year" in buttons
        assert "All Time" in buttons
