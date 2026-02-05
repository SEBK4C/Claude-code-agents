"""
Services package for the Telegram Trade Journal Bot.

This package contains service classes for external integrations including:
- ai_service: LongCat API integration for AI-assisted features
- price_service: Real-time price fetching via yfinance
- price_monitor: Background price monitoring for SL/TP alerts
- analytics_service: Trading analytics calculations
- report_service: Chart generation for analytics
- trade_parser: Natural language trade parsing
- currency_service: Currency conversion for P&L calculations
"""

from services.ai_service import AIService, get_ai_service, reset_ai_service
from services.trade_parser import (
    DEFAULT_TAGS,
    KNOWN_INSTRUMENTS,
    ParsedTrade,
    TradeAction,
    TradeParser,
    get_trade_parser,
    reset_trade_parser,
)
from services.analytics_service import (
    AnalyticsResult,
    AnalyticsService,
    DayOfWeekBreakdown,
    EquityPoint,
    HourBreakdown,
    InstrumentBreakdown,
    get_analytics_service,
    reset_analytics_service,
)
from services.price_monitor import (
    AlertType,
    PriceAlert,
    PriceMonitor,
    get_price_monitor,
    reset_price_monitor,
    shutdown_price_monitor,
)
from services.price_service import (
    PriceResult,
    PriceService,
    get_price_service,
    reset_price_service,
)
from services.report_service import (
    ReportService,
    get_report_service,
    reset_report_service,
)
from services.reminder_service import (
    ReminderService,
    get_reminder_service,
    reset_reminder_service,
    shutdown_reminder_service,
)
from services.currency_service import (
    CurrencyService,
    ExchangeRateResult,
    get_currency_service,
    reset_currency_service,
)
from services.pnl_service import (
    PnLResult,
    PnLService,
    PositionSizeResult,
    RiskRewardResult,
    get_pnl_service,
    reset_pnl_service,
)

__all__ = [
    # Trade Parser
    "TradeParser",
    "ParsedTrade",
    "TradeAction",
    "DEFAULT_TAGS",
    "KNOWN_INSTRUMENTS",
    "get_trade_parser",
    "reset_trade_parser",
    # AI Service
    "AIService",
    "get_ai_service",
    "reset_ai_service",
    # Analytics Service
    "AnalyticsService",
    "AnalyticsResult",
    "InstrumentBreakdown",
    "DayOfWeekBreakdown",
    "HourBreakdown",
    "EquityPoint",
    "get_analytics_service",
    "reset_analytics_service",
    # Report Service
    "ReportService",
    "get_report_service",
    "reset_report_service",
    # Price Service
    "PriceService",
    "PriceResult",
    "get_price_service",
    "reset_price_service",
    # Price Monitor
    "PriceMonitor",
    "PriceAlert",
    "AlertType",
    "get_price_monitor",
    "shutdown_price_monitor",
    "reset_price_monitor",
    # Reminder Service
    "ReminderService",
    "get_reminder_service",
    "reset_reminder_service",
    "shutdown_reminder_service",
    # Currency Service
    "CurrencyService",
    "ExchangeRateResult",
    "get_currency_service",
    "reset_currency_service",
    # P&L Service
    "PnLService",
    "PnLResult",
    "RiskRewardResult",
    "PositionSizeResult",
    "get_pnl_service",
    "reset_pnl_service",
]
