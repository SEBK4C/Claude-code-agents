"""
Trade parser service for natural language trade input.

This module provides regex-based parsing for natural language trade messages,
converting them into structured trade data for the Telegram Trade Journal Bot.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional

from config import get_logger

logger = get_logger(__name__)


# Default trading tags that can be detected in messages
DEFAULT_TAGS = [
    "Breakout",
    "Reversal",
    "News",
    "Scalp",
    "Swing",
    "Trend",
    "Counter-trend",
    "Range",
]

# Known instruments for detection
KNOWN_INSTRUMENTS = [
    "DAX",
    "NASDAQ",
    "NAS100",
    "US100",
    "DE40",
    "SPX",
    "SP500",
    "US500",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "BTCUSD",
    "ETHUSD",
    "XAUUSD",
    "GOLD",
    "OIL",
    "USOIL",
    "DJI",
    "DOW",
    "FTSE",
    "UK100",
    "NIKKEI",
    "JP225",
]


class TradeAction(str, Enum):
    """Parsed trade action type."""

    OPEN = "open"
    CLOSE = "close"
    UNKNOWN = "unknown"


@dataclass
class ParsedTrade:
    """
    Result of parsing a natural language trade message.

    Contains all extracted trade fields and metadata about the parse result.
    """

    # Trade action
    action: TradeAction = TradeAction.UNKNOWN

    # Core trade fields
    instrument: Optional[str] = None
    direction: Optional[str] = None  # "long" or "short"
    entry_price: Optional[Decimal] = None
    exit_price: Optional[Decimal] = None
    sl_price: Optional[Decimal] = None
    tp_price: Optional[Decimal] = None
    lot_size: Optional[Decimal] = None

    # Metadata
    tags: list[str] = field(default_factory=list)
    notes: Optional[str] = None

    # Parse quality metrics
    confidence: float = 0.0
    missing_fields: list[str] = field(default_factory=list)
    raw_message: str = ""

    def is_valid_open_trade(self) -> bool:
        """Check if parsed data is sufficient for opening a trade."""
        return (
            self.action == TradeAction.OPEN
            and self.instrument is not None
            and self.direction is not None
            and self.entry_price is not None
        )

    def is_valid_close_trade(self) -> bool:
        """Check if parsed data is sufficient for closing a trade."""
        return (
            self.action == TradeAction.CLOSE
            and self.instrument is not None
            and self.exit_price is not None
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "action": self.action.value,
            "instrument": self.instrument,
            "direction": self.direction,
            "entry_price": str(self.entry_price) if self.entry_price else None,
            "exit_price": str(self.exit_price) if self.exit_price else None,
            "sl_price": str(self.sl_price) if self.sl_price else None,
            "tp_price": str(self.tp_price) if self.tp_price else None,
            "lot_size": str(self.lot_size) if self.lot_size else None,
            "tags": self.tags,
            "notes": self.notes,
            "confidence": self.confidence,
            "missing_fields": self.missing_fields,
        }


class TradeParser:
    """
    Parser for natural language trade messages.

    Uses regex patterns to extract trade information from user messages
    and calculates a confidence score based on fields successfully extracted.
    """

    # Regex patterns for trade parsing
    # Direction detection patterns
    LONG_PATTERNS = [
        r"\b(?:bought|buy|long|longed|going\s+long)\b",
    ]
    SHORT_PATTERNS = [
        r"\b(?:sold|sell|short|shorted|shorting|going\s+short)\b",
    ]

    # Close trade patterns
    CLOSE_PATTERNS = [
        r"\b(?:closed|close|exited|exit|out\s+of|took\s+profit|stopped\s+out)\b",
    ]

    # Price extraction patterns (capture group for the price)
    # Entry price: "at 18500", "entry 18500", "@18500", "entered at 18500"
    ENTRY_PATTERNS = [
        r"(?:at|@|entry|entered\s+at|entered|price)\s*[:=]?\s*(\d+(?:[.,]\d+)?)",
    ]

    # Exit price: "closed at 18550", "exit 18550", "out at 18550"
    EXIT_PATTERNS = [
        r"(?:closed\s+at|exit(?:ed)?\s+at|out\s+at|closed|exited|exit)\s*[:=]?\s*(\d+(?:[.,]\d+)?)",
    ]

    # Stop loss: "sl 18450", "stop 18450", "stop loss 18450", "stoploss 18450"
    SL_PATTERNS = [
        r"(?:sl|stop\s*loss|stoploss|stop)\s*[:=]?\s*(\d+(?:[.,]\d+)?)",
    ]

    # Take profit: "tp 18600", "target 18600", "take profit 18600"
    TP_PATTERNS = [
        r"(?:tp|take\s*profit|takeprofit|target|tgt)\s*[:=]?\s*(\d+(?:[.,]\d+)?)",
    ]

    # Lot size: "0.5 lots", "1 lot", "2 lots", "0.1 lot", "size 0.5"
    LOT_PATTERNS = [
        r"(\d+(?:[.,]\d+)?)\s*(?:lots?|lot)\b",
        r"(?:size|position|qty|quantity)\s*[:=]?\s*(\d+(?:[.,]\d+)?)",
    ]

    def __init__(
        self,
        instruments: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
    ):
        """
        Initialize the trade parser.

        Args:
            instruments: List of known instruments. Defaults to KNOWN_INSTRUMENTS.
            tags: List of tags to detect. Defaults to DEFAULT_TAGS.
        """
        self.instruments = instruments or KNOWN_INSTRUMENTS
        self.tags = tags or DEFAULT_TAGS

        # Build instrument detection pattern (case-insensitive)
        instrument_pattern = "|".join(re.escape(inst) for inst in self.instruments)
        self._instrument_regex = re.compile(
            rf"\b({instrument_pattern})\b", re.IGNORECASE
        )

        # Build tag detection pattern (case-insensitive)
        tag_pattern = "|".join(re.escape(tag) for tag in self.tags)
        self._tag_regex = re.compile(rf"\b({tag_pattern})\b", re.IGNORECASE)

        # Compile direction patterns
        self._long_regex = re.compile(
            "|".join(self.LONG_PATTERNS), re.IGNORECASE
        )
        self._short_regex = re.compile(
            "|".join(self.SHORT_PATTERNS), re.IGNORECASE
        )
        self._close_regex = re.compile(
            "|".join(self.CLOSE_PATTERNS), re.IGNORECASE
        )

        # Compile price patterns
        self._entry_regex = re.compile(
            "|".join(self.ENTRY_PATTERNS), re.IGNORECASE
        )
        self._exit_regex = re.compile(
            "|".join(self.EXIT_PATTERNS), re.IGNORECASE
        )
        self._sl_regex = re.compile("|".join(self.SL_PATTERNS), re.IGNORECASE)
        self._tp_regex = re.compile("|".join(self.TP_PATTERNS), re.IGNORECASE)
        self._lot_regex = re.compile("|".join(self.LOT_PATTERNS), re.IGNORECASE)

        logger.info(
            "TradeParser initialized",
            instruments_count=len(self.instruments),
            tags_count=len(self.tags),
        )

    def parse_trade_message(self, message: str) -> ParsedTrade:
        """
        Parse a natural language message into structured trade data.

        Args:
            message: The raw message from the user.

        Returns:
            ParsedTrade: Parsed trade data with confidence score.
        """
        result = ParsedTrade(raw_message=message)

        # Normalize message
        normalized = message.strip()

        # Detect action (open vs close)
        result.action = self._detect_action(normalized)

        # Extract instrument
        result.instrument = self._extract_instrument(normalized)

        # Extract direction
        result.direction = self._extract_direction(normalized)

        # Extract prices
        if result.action == TradeAction.CLOSE:
            # For close trades, try specific exit patterns first
            result.exit_price = self._extract_exit_price(normalized)
            # If no exit price found, fall back to generic "at X" pattern
            # since "closed DAX at 18550" means exit at 18550
            if result.exit_price is None:
                result.exit_price = self._extract_entry_price(normalized)
            # Entry price is not typically mentioned in close messages
            # (the trade already has an entry price stored)
        else:
            result.entry_price = self._extract_entry_price(normalized)

        # Extract SL/TP
        result.sl_price = self._extract_sl_price(normalized)
        result.tp_price = self._extract_tp_price(normalized)

        # Extract lot size
        result.lot_size = self._extract_lot_size(normalized)

        # Extract tags
        result.tags = self._extract_tags(normalized)

        # Calculate missing fields
        result.missing_fields = self._calculate_missing_fields(result)

        # Calculate confidence score
        result.confidence = self._calculate_confidence(result)

        logger.info(
            "Trade message parsed",
            action=result.action.value,
            instrument=result.instrument,
            direction=result.direction,
            confidence=result.confidence,
            missing_fields=result.missing_fields,
        )

        return result

    def _detect_action(self, message: str) -> TradeAction:
        """
        Detect whether the message is about opening or closing a trade.

        Args:
            message: Normalized message text.

        Returns:
            TradeAction: The detected action type.
        """
        # Check for close indicators first (they're more specific)
        if self._close_regex.search(message):
            return TradeAction.CLOSE

        # Check for open indicators
        if self._long_regex.search(message) or self._short_regex.search(message):
            return TradeAction.OPEN

        return TradeAction.UNKNOWN

    def _extract_instrument(self, message: str) -> Optional[str]:
        """
        Extract the trading instrument from the message.

        Args:
            message: Normalized message text.

        Returns:
            Optional[str]: The detected instrument or None.
        """
        match = self._instrument_regex.search(message)
        if match:
            # Normalize to uppercase
            return match.group(1).upper()
        return None

    def _extract_direction(self, message: str) -> Optional[str]:
        """
        Extract the trade direction (long/short) from the message.

        Args:
            message: Normalized message text.

        Returns:
            Optional[str]: "long", "short", or None.
        """
        # Check for long indicators
        if self._long_regex.search(message):
            return "long"

        # Check for short indicators
        if self._short_regex.search(message):
            return "short"

        return None

    def _extract_price(self, message: str, regex: re.Pattern) -> Optional[Decimal]:
        """
        Extract a price value using the given regex pattern.

        Args:
            message: Normalized message text.
            regex: Compiled regex pattern with a capture group for the price.

        Returns:
            Optional[Decimal]: The extracted price or None.
        """
        match = regex.search(message)
        if match:
            # Find the first non-None group (the price)
            for group in match.groups():
                if group:
                    try:
                        # Normalize decimal separator
                        price_str = group.replace(",", ".")
                        return Decimal(price_str)
                    except InvalidOperation:
                        pass
        return None

    def _extract_entry_price(self, message: str) -> Optional[Decimal]:
        """Extract entry price from message."""
        return self._extract_price(message, self._entry_regex)

    def _extract_exit_price(self, message: str) -> Optional[Decimal]:
        """Extract exit price from message."""
        return self._extract_price(message, self._exit_regex)

    def _extract_sl_price(self, message: str) -> Optional[Decimal]:
        """Extract stop loss price from message."""
        return self._extract_price(message, self._sl_regex)

    def _extract_tp_price(self, message: str) -> Optional[Decimal]:
        """Extract take profit price from message."""
        return self._extract_price(message, self._tp_regex)

    def _extract_lot_size(self, message: str) -> Optional[Decimal]:
        """Extract lot size from message."""
        return self._extract_price(message, self._lot_regex)

    def _extract_tags(self, message: str) -> list[str]:
        """
        Extract matching tags from the message.

        Args:
            message: Normalized message text.

        Returns:
            list[str]: List of matching tag names (properly capitalized).
        """
        matches = self._tag_regex.findall(message)
        if not matches:
            return []

        # Normalize tag capitalization to match our defaults
        tag_lookup = {tag.lower(): tag for tag in self.tags}
        return [tag_lookup.get(m.lower(), m) for m in matches]

    def _calculate_missing_fields(self, result: ParsedTrade) -> list[str]:
        """
        Calculate which required fields are missing.

        Args:
            result: The parsed trade data.

        Returns:
            list[str]: List of missing field names.
        """
        missing = []

        if result.action == TradeAction.CLOSE:
            # For close trades: need instrument and exit price
            if not result.instrument:
                missing.append("instrument")
            if not result.exit_price:
                missing.append("exit_price")
        else:
            # For open trades: need instrument, direction, entry price
            if not result.instrument:
                missing.append("instrument")
            if not result.direction:
                missing.append("direction")
            if not result.entry_price:
                missing.append("entry_price")
            # Lot size is commonly needed but not strictly required
            if not result.lot_size:
                missing.append("lot_size")

        return missing

    def _calculate_confidence(self, result: ParsedTrade) -> float:
        """
        Calculate a confidence score for the parse result.

        Higher scores indicate more complete and reliable parsing.

        Args:
            result: The parsed trade data.

        Returns:
            float: Confidence score between 0.0 and 1.0.
        """
        score = 0.0

        # Action detection (essential)
        if result.action != TradeAction.UNKNOWN:
            score += 0.2

        # Instrument (essential)
        if result.instrument:
            score += 0.2

        if result.action == TradeAction.CLOSE:
            # For close trades
            if result.exit_price:
                score += 0.3
            if result.direction:
                score += 0.15
            if result.entry_price:
                score += 0.15
        else:
            # For open trades
            if result.direction:
                score += 0.2
            if result.entry_price:
                score += 0.2
            if result.sl_price:
                score += 0.05
            if result.tp_price:
                score += 0.05
            if result.lot_size:
                score += 0.1

        # Tags (bonus)
        if result.tags:
            score += 0.05

        return min(score, 1.0)


# Module-level singleton instance
_trade_parser: Optional[TradeParser] = None


def get_trade_parser() -> TradeParser:
    """
    Get or create the global TradeParser instance.

    Returns:
        TradeParser: The global trade parser singleton.
    """
    global _trade_parser
    if _trade_parser is None:
        _trade_parser = TradeParser()
    return _trade_parser


def reset_trade_parser() -> None:
    """
    Reset the global TradeParser instance.

    Useful for testing or reconfiguration.
    """
    global _trade_parser
    _trade_parser = None
