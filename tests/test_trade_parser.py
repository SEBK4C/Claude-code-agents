"""
Tests for the trade parser service.

This module tests:
- Natural language trade message parsing
- Instrument detection
- Direction detection (long/short)
- Price extraction (entry, exit, SL, TP)
- Lot size extraction
- Tag detection
- Confidence scoring
"""

from decimal import Decimal

import pytest

from services.trade_parser import (
    DEFAULT_TAGS,
    KNOWN_INSTRUMENTS,
    ParsedTrade,
    TradeAction,
    TradeParser,
    get_trade_parser,
    reset_trade_parser,
)


@pytest.fixture
def parser():
    """Provide a fresh TradeParser instance for each test."""
    return TradeParser()


@pytest.fixture(autouse=True)
def reset_parser_singleton():
    """Reset the global parser singleton before and after each test."""
    reset_trade_parser()
    yield
    reset_trade_parser()


class TestTradeParserInit:
    """Tests for TradeParser initialization."""

    def test_default_instruments(self, parser):
        """Test that default instruments are loaded."""
        assert len(parser.instruments) > 0
        assert "DAX" in parser.instruments
        assert "NASDAQ" in parser.instruments
        assert "EURUSD" in parser.instruments

    def test_default_tags(self, parser):
        """Test that default tags are loaded."""
        assert len(parser.tags) > 0
        assert "Breakout" in parser.tags
        assert "Reversal" in parser.tags
        assert "Scalp" in parser.tags

    def test_custom_instruments(self):
        """Test initialization with custom instruments."""
        custom_instruments = ["AAPL", "TSLA", "MSFT"]
        parser = TradeParser(instruments=custom_instruments)
        assert parser.instruments == custom_instruments

    def test_custom_tags(self):
        """Test initialization with custom tags."""
        custom_tags = ["Custom1", "Custom2"]
        parser = TradeParser(tags=custom_tags)
        assert parser.tags == custom_tags


class TestActionDetection:
    """Tests for trade action detection (open vs close)."""

    def test_detect_open_from_bought(self, parser):
        """Test detection of open action from 'bought'."""
        result = parser.parse_trade_message("Bought DAX at 18500")
        assert result.action == TradeAction.OPEN

    def test_detect_open_from_long(self, parser):
        """Test detection of open action from 'long'."""
        result = parser.parse_trade_message("Long NASDAQ at 19000")
        assert result.action == TradeAction.OPEN

    def test_detect_open_from_short(self, parser):
        """Test detection of open action from 'short'."""
        result = parser.parse_trade_message("Short DAX at 18500")
        assert result.action == TradeAction.OPEN

    def test_detect_close_from_closed(self, parser):
        """Test detection of close action from 'closed'."""
        result = parser.parse_trade_message("Closed my DAX long at 18550")
        assert result.action == TradeAction.CLOSE

    def test_detect_close_from_exited(self, parser):
        """Test detection of close action from 'exited'."""
        result = parser.parse_trade_message("Exited NASDAQ at 19200")
        assert result.action == TradeAction.CLOSE

    def test_detect_close_from_stopped_out(self, parser):
        """Test detection of close action from 'stopped out'."""
        result = parser.parse_trade_message("Stopped out of DAX at 18400")
        assert result.action == TradeAction.CLOSE

    def test_unknown_action(self, parser):
        """Test that ambiguous messages result in unknown action."""
        result = parser.parse_trade_message("DAX looks good today")
        assert result.action == TradeAction.UNKNOWN


class TestInstrumentDetection:
    """Tests for instrument detection."""

    def test_detect_dax(self, parser):
        """Test DAX instrument detection."""
        result = parser.parse_trade_message("Bought DAX at 18500")
        assert result.instrument == "DAX"

    def test_detect_nasdaq(self, parser):
        """Test NASDAQ instrument detection."""
        result = parser.parse_trade_message("Short NASDAQ at 19000")
        assert result.instrument == "NASDAQ"

    def test_detect_eurusd(self, parser):
        """Test EURUSD instrument detection."""
        result = parser.parse_trade_message("Long EURUSD at 1.0850")
        assert result.instrument == "EURUSD"

    def test_case_insensitive_detection(self, parser):
        """Test that instrument detection is case-insensitive."""
        result = parser.parse_trade_message("Bought dax at 18500")
        assert result.instrument == "DAX"

    def test_no_instrument(self, parser):
        """Test handling of messages without known instruments."""
        result = parser.parse_trade_message("Bought something at 100")
        assert result.instrument is None


class TestDirectionDetection:
    """Tests for trade direction detection."""

    def test_detect_long_from_bought(self, parser):
        """Test long detection from 'bought'."""
        result = parser.parse_trade_message("Bought DAX at 18500")
        assert result.direction == "long"

    def test_detect_long_from_buy(self, parser):
        """Test long detection from 'buy'."""
        result = parser.parse_trade_message("Buy DAX at 18500")
        assert result.direction == "long"

    def test_detect_long_from_going_long(self, parser):
        """Test long detection from 'going long'."""
        result = parser.parse_trade_message("Going long on DAX at 18500")
        assert result.direction == "long"

    def test_detect_short_from_sold(self, parser):
        """Test short detection from 'sold'."""
        result = parser.parse_trade_message("Sold DAX at 18500")
        assert result.direction == "short"

    def test_detect_short_from_short(self, parser):
        """Test short detection from 'short'."""
        result = parser.parse_trade_message("Short DAX at 18500")
        assert result.direction == "short"

    def test_detect_short_from_shorting(self, parser):
        """Test short detection from 'shorting'."""
        result = parser.parse_trade_message("Shorting NASDAQ at 19000")
        assert result.direction == "short"


class TestPriceExtraction:
    """Tests for price extraction."""

    def test_extract_entry_price_with_at(self, parser):
        """Test entry price extraction with 'at' keyword."""
        result = parser.parse_trade_message("Bought DAX at 18500")
        assert result.entry_price == Decimal("18500")

    def test_extract_entry_price_with_symbol(self, parser):
        """Test entry price extraction with @ symbol."""
        result = parser.parse_trade_message("Long DAX @18500")
        assert result.entry_price == Decimal("18500")

    def test_extract_entry_price_with_decimal(self, parser):
        """Test entry price extraction with decimal."""
        result = parser.parse_trade_message("Long EURUSD at 1.0850")
        assert result.entry_price == Decimal("1.0850")

    def test_extract_exit_price(self, parser):
        """Test exit price extraction."""
        result = parser.parse_trade_message("Closed DAX at 18550")
        assert result.exit_price == Decimal("18550")

    def test_extract_sl_price(self, parser):
        """Test stop loss price extraction."""
        result = parser.parse_trade_message("Bought DAX at 18500 sl 18450")
        assert result.sl_price == Decimal("18450")

    def test_extract_sl_with_stop_loss(self, parser):
        """Test stop loss extraction with 'stop loss' keyword."""
        result = parser.parse_trade_message("Long DAX at 18500 stop loss 18450")
        assert result.sl_price == Decimal("18450")

    def test_extract_tp_price(self, parser):
        """Test take profit price extraction."""
        result = parser.parse_trade_message("Bought DAX at 18500 tp 18600")
        assert result.tp_price == Decimal("18600")

    def test_extract_tp_with_target(self, parser):
        """Test take profit extraction with 'target' keyword."""
        result = parser.parse_trade_message("Long DAX at 18500 target 18600")
        assert result.tp_price == Decimal("18600")


class TestLotSizeExtraction:
    """Tests for lot size extraction."""

    def test_extract_lot_size_with_lots(self, parser):
        """Test lot size extraction with 'lots' keyword."""
        result = parser.parse_trade_message("Bought DAX at 18500 0.5 lots")
        assert result.lot_size == Decimal("0.5")

    def test_extract_lot_size_with_lot(self, parser):
        """Test lot size extraction with 'lot' keyword."""
        result = parser.parse_trade_message("Long DAX at 18500 1 lot")
        assert result.lot_size == Decimal("1")

    def test_extract_lot_size_integer(self, parser):
        """Test lot size extraction with integer."""
        result = parser.parse_trade_message("Short NASDAQ at 19000 2 lots")
        assert result.lot_size == Decimal("2")


class TestTagExtraction:
    """Tests for tag extraction."""

    def test_extract_single_tag(self, parser):
        """Test extraction of a single tag."""
        result = parser.parse_trade_message("Bought DAX at 18500 breakout")
        assert "Breakout" in result.tags

    def test_extract_multiple_tags(self, parser):
        """Test extraction of multiple tags."""
        result = parser.parse_trade_message(
            "Short NASDAQ at 19000 reversal scalp"
        )
        assert "Reversal" in result.tags
        assert "Scalp" in result.tags

    def test_case_insensitive_tags(self, parser):
        """Test that tag detection is case-insensitive."""
        result = parser.parse_trade_message("Long DAX at 18500 BREAKOUT")
        assert "Breakout" in result.tags


class TestCompleteMessages:
    """Tests for complete trade message parsing."""

    def test_full_open_trade_message(self, parser):
        """Test parsing a complete open trade message."""
        result = parser.parse_trade_message(
            "Bought DAX at 18500, SL 18450, TP 18600, 0.5 lots breakout"
        )
        assert result.action == TradeAction.OPEN
        assert result.instrument == "DAX"
        assert result.direction == "long"
        assert result.entry_price == Decimal("18500")
        assert result.sl_price == Decimal("18450")
        assert result.tp_price == Decimal("18600")
        assert result.lot_size == Decimal("0.5")
        assert "Breakout" in result.tags
        assert result.confidence >= 0.7

    def test_short_trade_message(self, parser):
        """Test parsing a short trade message."""
        result = parser.parse_trade_message(
            "Short NASDAQ 19200 sl 19250 tp 19100 1 lot"
        )
        assert result.action == TradeAction.OPEN
        assert result.instrument == "NASDAQ"
        assert result.direction == "short"
        assert result.sl_price == Decimal("19250")
        assert result.tp_price == Decimal("19100")
        assert result.lot_size == Decimal("1")

    def test_close_trade_message(self, parser):
        """Test parsing a close trade message."""
        result = parser.parse_trade_message("Closed my DAX long at 18550")
        assert result.action == TradeAction.CLOSE
        assert result.instrument == "DAX"
        assert result.direction == "long"
        assert result.exit_price == Decimal("18550")


class TestConfidenceScoring:
    """Tests for confidence score calculation."""

    def test_high_confidence_open(self, parser):
        """Test high confidence for complete open trade."""
        result = parser.parse_trade_message(
            "Bought DAX at 18500 sl 18450 tp 18600 0.5 lots"
        )
        assert result.confidence >= 0.8

    def test_medium_confidence_open(self, parser):
        """Test medium confidence for partial open trade."""
        result = parser.parse_trade_message("Bought DAX at 18500")
        # With action, instrument, direction, and entry price, confidence is 0.8
        assert result.confidence >= 0.6

    def test_low_confidence(self, parser):
        """Test low confidence for unclear message."""
        result = parser.parse_trade_message("DAX looks interesting")
        assert result.confidence < 0.5

    def test_high_confidence_close(self, parser):
        """Test high confidence for close trade."""
        result = parser.parse_trade_message("Closed DAX at 18550")
        assert result.confidence >= 0.5


class TestMissingFields:
    """Tests for missing field detection."""

    def test_missing_instrument(self, parser):
        """Test detection of missing instrument."""
        result = parser.parse_trade_message("Bought at 18500")
        assert "instrument" in result.missing_fields

    def test_missing_direction(self, parser):
        """Test detection of missing direction."""
        result = parser.parse_trade_message("DAX at 18500")
        assert "direction" in result.missing_fields

    def test_missing_entry_price(self, parser):
        """Test detection of missing entry price."""
        result = parser.parse_trade_message("Bought DAX")
        assert "entry_price" in result.missing_fields

    def test_missing_lot_size(self, parser):
        """Test detection of missing lot size."""
        result = parser.parse_trade_message("Bought DAX at 18500")
        assert "lot_size" in result.missing_fields

    def test_no_missing_required_for_complete(self, parser):
        """Test no critical missing fields for complete message."""
        result = parser.parse_trade_message(
            "Bought DAX at 18500 1 lot"
        )
        # Should only have optional fields missing
        assert "instrument" not in result.missing_fields
        assert "direction" not in result.missing_fields
        assert "entry_price" not in result.missing_fields


class TestParsedTrade:
    """Tests for ParsedTrade dataclass."""

    def test_is_valid_open_trade(self):
        """Test is_valid_open_trade method."""
        trade = ParsedTrade(
            action=TradeAction.OPEN,
            instrument="DAX",
            direction="long",
            entry_price=Decimal("18500"),
        )
        assert trade.is_valid_open_trade()

    def test_is_valid_open_trade_missing_direction(self):
        """Test is_valid_open_trade with missing direction."""
        trade = ParsedTrade(
            action=TradeAction.OPEN,
            instrument="DAX",
            direction=None,
            entry_price=Decimal("18500"),
        )
        assert not trade.is_valid_open_trade()

    def test_is_valid_close_trade(self):
        """Test is_valid_close_trade method."""
        trade = ParsedTrade(
            action=TradeAction.CLOSE,
            instrument="DAX",
            exit_price=Decimal("18550"),
        )
        assert trade.is_valid_close_trade()

    def test_is_valid_close_trade_missing_exit(self):
        """Test is_valid_close_trade with missing exit price."""
        trade = ParsedTrade(
            action=TradeAction.CLOSE,
            instrument="DAX",
            exit_price=None,
        )
        assert not trade.is_valid_close_trade()

    def test_to_dict(self):
        """Test to_dict serialization."""
        trade = ParsedTrade(
            action=TradeAction.OPEN,
            instrument="DAX",
            direction="long",
            entry_price=Decimal("18500"),
            tags=["Breakout"],
        )
        result = trade.to_dict()
        assert result["action"] == "open"
        assert result["instrument"] == "DAX"
        assert result["direction"] == "long"
        assert result["entry_price"] == "18500"
        assert "Breakout" in result["tags"]


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_trade_parser_returns_same_instance(self):
        """Test that get_trade_parser returns the same instance."""
        parser1 = get_trade_parser()
        parser2 = get_trade_parser()
        assert parser1 is parser2

    def test_reset_trade_parser(self):
        """Test that reset_trade_parser creates new instance."""
        parser1 = get_trade_parser()
        reset_trade_parser()
        parser2 = get_trade_parser()
        assert parser1 is not parser2


class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""

    def test_empty_message(self, parser):
        """Test handling of empty message."""
        result = parser.parse_trade_message("")
        assert result.action == TradeAction.UNKNOWN
        assert result.confidence == 0.0

    def test_whitespace_only_message(self, parser):
        """Test handling of whitespace-only message."""
        result = parser.parse_trade_message("   \n\t  ")
        assert result.action == TradeAction.UNKNOWN

    def test_very_long_message(self, parser):
        """Test handling of very long message."""
        long_msg = "Bought DAX at 18500 " + "x" * 1000
        result = parser.parse_trade_message(long_msg)
        assert result.action == TradeAction.OPEN
        assert result.instrument == "DAX"

    def test_special_characters(self, parser):
        """Test handling of special characters."""
        result = parser.parse_trade_message("Bought DAX! at 18500$$$")
        assert result.instrument == "DAX"

    def test_comma_decimal_separator(self, parser):
        """Test handling of comma as decimal separator."""
        result = parser.parse_trade_message("Long EURUSD at 1,0850")
        assert result.entry_price == Decimal("1.0850")
