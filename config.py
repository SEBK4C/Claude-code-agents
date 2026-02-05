"""
Configuration module for the Telegram Trade Journal Bot.

This module handles loading and validating environment variables,
providing a centralized configuration object for the application.
"""

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import structlog
from dotenv import load_dotenv


@dataclass
class DatabaseConfig:
    """Database configuration settings."""

    url: str = "sqlite+aiosqlite:///./journal.db"
    echo: bool = False  # Set to True to log SQL queries


@dataclass
class TelegramConfig:
    """Telegram bot configuration settings."""

    token: str = ""

    def validate(self) -> bool:
        """
        Validate that required Telegram configuration is present.

        Returns:
            bool: True if configuration is valid, False otherwise.
        """
        return bool(self.token)


@dataclass
class LongCatConfig:
    """LongCat API configuration settings."""

    api_key: str = ""
    api_url: str = "https://api.longcat.chat/openai"
    model: str = "LongCat-Flash-Thinking-2601"

    def validate(self) -> bool:
        """
        Validate that required LongCat configuration is present.

        Returns:
            bool: True if configuration is valid, False otherwise.
        """
        return bool(self.api_key)


# Instrument configuration for P&L calculation
# Maps instrument names to their trading specifications
INSTRUMENTS_CONFIG: dict[str, dict] = {
    "DAX": {
        "symbol": "^GDAXI",
        "currency": "EUR",
        "point_value": 1.0,
    },
    "NASDAQ": {
        "symbol": "^IXIC",
        "currency": "USD",
        "point_value": 1.0,
    },
}

# Base currency for P&L calculations
BASE_CURRENCY = "USD"

# Exchange rate cache TTL in seconds (1 minute for fresher rates)
EXCHANGE_RATE_CACHE_TTL = 60


def get_instrument_config(instrument: str) -> dict:
    """
    Get configuration for a specific trading instrument.

    Args:
        instrument: The instrument name (e.g., "DAX", "NASDAQ").

    Returns:
        dict: Instrument configuration with symbol, currency, and point_value.
              Returns a default config if instrument is not found.
    """
    return INSTRUMENTS_CONFIG.get(instrument.upper(), {
        "symbol": instrument,
        "currency": "USD",
        "point_value": 1.0,
    })


@dataclass
class LoggingConfig:
    """Logging configuration settings."""

    level: str = "INFO"
    format: str = "json"  # "json" or "console"

    def get_level(self) -> int:
        """
        Convert string log level to logging constant.

        Returns:
            int: The logging level constant.
        """
        levels = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        return levels.get(self.level.upper(), logging.INFO)


@dataclass
class Config:
    """
    Main application configuration.

    This class aggregates all configuration sections and provides
    validation and loading from environment variables.
    """

    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    longcat: LongCatConfig = field(default_factory=LongCatConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "Config":
        """
        Load configuration from environment variables.

        Args:
            env_file: Optional path to .env file. If not provided,
                      will look for .env in current directory.

        Returns:
            Config: A populated configuration object.
        """
        # Load environment variables from .env file
        if env_file:
            load_dotenv(env_file)
        else:
            load_dotenv()

        return cls(
            database=DatabaseConfig(
                url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./journal.db"),
                echo=os.getenv("DATABASE_ECHO", "").lower() == "true",
            ),
            telegram=TelegramConfig(
                token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            ),
            longcat=LongCatConfig(
                api_key=os.getenv("LONGCAT_API_KEY", ""),
                api_url=os.getenv("LONGCAT_API_URL", "https://api.longcat.chat/openai"),
                model=os.getenv("LONGCAT_MODEL", "LongCat-Flash-Thinking-2601"),
            ),
            logging=LoggingConfig(
                level=os.getenv("LOG_LEVEL", "INFO"),
                format=os.getenv("LOG_FORMAT", "json"),
            ),
        )

    def validate(self) -> list[str]:
        """
        Validate the configuration and return a list of errors.

        Returns:
            list[str]: A list of validation error messages. Empty if valid.
        """
        errors = []

        if not self.telegram.validate():
            errors.append("TELEGRAM_BOT_TOKEN is required but not set")

        if not self.longcat.validate():
            errors.append("LONGCAT_API_KEY is required but not set")

        return errors

    def is_valid(self) -> bool:
        """
        Check if the configuration is valid.

        Returns:
            bool: True if configuration is valid, False otherwise.
        """
        return len(self.validate()) == 0


def configure_logging(config: LoggingConfig) -> None:
    """
    Configure structured logging for the application.

    Args:
        config: The logging configuration settings.
    """
    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=config.get_level(),
    )

    # Determine processors based on format
    if config.format == "console":
        processors = [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(),
        ]
    else:
        # JSON format (default)
        processors = [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a configured logger instance.

    Args:
        name: The name for the logger (typically __name__).

    Returns:
        structlog.stdlib.BoundLogger: A configured logger instance.
    """
    return structlog.get_logger(name)


# Global configuration instance (lazy-loaded)
_config: Optional[Config] = None


def get_config() -> Config:
    """
    Get the global configuration instance.

    The configuration is loaded from environment variables on first access.

    Returns:
        Config: The global configuration instance.
    """
    global _config
    if _config is None:
        _config = Config.from_env()
        configure_logging(_config.logging)
    return _config


def reset_config() -> None:
    """
    Reset the global configuration instance.

    This is primarily useful for testing to allow reconfiguration.
    """
    global _config
    _config = None
