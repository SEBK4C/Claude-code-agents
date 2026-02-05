"""
Tests for the configuration module.

This module tests:
- Configuration loading from environment variables
- Configuration validation
- Logging configuration
"""

import os
from unittest.mock import patch

import pytest

from config import (
    Config,
    DatabaseConfig,
    LoggingConfig,
    LongCatConfig,
    TelegramConfig,
    configure_logging,
    get_config,
    get_logger,
    reset_config,
)


class TestDatabaseConfig:
    """Tests for DatabaseConfig class."""

    def test_default_values(self):
        """Test that default values are set correctly."""
        config = DatabaseConfig()
        assert config.url == "sqlite+aiosqlite:///./journal.db"
        assert config.echo is False

    def test_custom_values(self):
        """Test custom values are accepted."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user:pass@localhost/db",
            echo=True,
        )
        assert config.url == "postgresql+asyncpg://user:pass@localhost/db"
        assert config.echo is True


class TestTelegramConfig:
    """Tests for TelegramConfig class."""

    def test_validate_with_token(self):
        """Test validation passes with a token."""
        config = TelegramConfig(token="test_token")
        assert config.validate() is True

    def test_validate_without_token(self):
        """Test validation fails without a token."""
        config = TelegramConfig(token="")
        assert config.validate() is False

    def test_validate_with_none_token(self):
        """Test validation handles empty string as falsy."""
        config = TelegramConfig(token="")
        assert config.validate() is False


class TestLongCatConfig:
    """Tests for LongCatConfig class."""

    def test_default_values(self):
        """Test that default values are set correctly."""
        config = LongCatConfig()
        assert config.api_url == "https://api.longcat.chat/openai"
        assert config.model == "LongCat-Flash-Thinking-2601"
        assert config.api_key == ""

    def test_validate_with_api_key(self):
        """Test validation passes with an API key."""
        config = LongCatConfig(api_key="test_key")
        assert config.validate() is True

    def test_validate_without_api_key(self):
        """Test validation fails without an API key."""
        config = LongCatConfig(api_key="")
        assert config.validate() is False


class TestLoggingConfig:
    """Tests for LoggingConfig class."""

    def test_default_values(self):
        """Test that default values are set correctly."""
        config = LoggingConfig()
        assert config.level == "INFO"
        assert config.format == "json"

    def test_get_level_valid_levels(self):
        """Test get_level returns correct logging constants."""
        import logging

        test_cases = [
            ("DEBUG", logging.DEBUG),
            ("INFO", logging.INFO),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
            ("CRITICAL", logging.CRITICAL),
        ]
        for level_str, expected in test_cases:
            config = LoggingConfig(level=level_str)
            assert config.get_level() == expected

    def test_get_level_case_insensitive(self):
        """Test get_level is case insensitive."""
        import logging

        config = LoggingConfig(level="debug")
        assert config.get_level() == logging.DEBUG

        config = LoggingConfig(level="Debug")
        assert config.get_level() == logging.DEBUG

    def test_get_level_invalid_defaults_to_info(self):
        """Test get_level defaults to INFO for invalid levels."""
        import logging

        config = LoggingConfig(level="INVALID")
        assert config.get_level() == logging.INFO


class TestConfig:
    """Tests for the main Config class."""

    def test_default_initialization(self):
        """Test Config initializes with default sub-configs."""
        config = Config()
        assert isinstance(config.database, DatabaseConfig)
        assert isinstance(config.telegram, TelegramConfig)
        assert isinstance(config.longcat, LongCatConfig)
        assert isinstance(config.logging, LoggingConfig)

    def test_from_env_loads_values(self):
        """Test Config.from_env loads from environment variables."""
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "env_telegram_token",
            "LONGCAT_API_KEY": "env_longcat_key",
            "LONGCAT_API_URL": "https://custom.api.url",
            "LONGCAT_MODEL": "custom-model",
            "DATABASE_URL": "sqlite+aiosqlite:///./custom.db",
            "LOG_LEVEL": "DEBUG",
            "LOG_FORMAT": "console",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = Config.from_env()

        assert config.telegram.token == "env_telegram_token"
        assert config.longcat.api_key == "env_longcat_key"
        assert config.longcat.api_url == "https://custom.api.url"
        assert config.longcat.model == "custom-model"
        assert config.database.url == "sqlite+aiosqlite:///./custom.db"
        assert config.logging.level == "DEBUG"
        assert config.logging.format == "console"

    def test_from_env_uses_defaults(self):
        """Test Config.from_env uses defaults for missing variables."""
        env_vars = {}  # Clear relevant env vars

        with patch.dict(os.environ, env_vars, clear=True):
            config = Config.from_env()

        assert config.database.url == "sqlite+aiosqlite:///./trade_journal.db"
        assert config.longcat.api_url == "https://api.longcat.chat/openai"
        assert config.longcat.model == "LongCat-Flash-Thinking-2601"

    def test_validate_returns_errors(self):
        """Test validate returns error list for invalid config."""
        config = Config(
            telegram=TelegramConfig(token=""),
            longcat=LongCatConfig(api_key=""),
        )
        errors = config.validate()

        assert len(errors) == 2
        assert "TELEGRAM_BOT_TOKEN" in errors[0]
        assert "LONGCAT_API_KEY" in errors[1]

    def test_validate_returns_empty_for_valid_config(self):
        """Test validate returns empty list for valid config."""
        config = Config(
            telegram=TelegramConfig(token="valid_token"),
            longcat=LongCatConfig(api_key="valid_key"),
        )
        errors = config.validate()

        assert len(errors) == 0

    def test_is_valid_true_for_valid_config(self):
        """Test is_valid returns True for valid configuration."""
        config = Config(
            telegram=TelegramConfig(token="valid_token"),
            longcat=LongCatConfig(api_key="valid_key"),
        )
        assert config.is_valid() is True

    def test_is_valid_false_for_invalid_config(self):
        """Test is_valid returns False for invalid configuration."""
        config = Config(
            telegram=TelegramConfig(token=""),
            longcat=LongCatConfig(api_key=""),
        )
        assert config.is_valid() is False


class TestLoggingSetup:
    """Tests for logging setup functions."""

    def test_configure_logging_json_format(self):
        """Test configure_logging sets up JSON format."""
        config = LoggingConfig(level="INFO", format="json")
        # Should not raise
        configure_logging(config)

    def test_configure_logging_console_format(self):
        """Test configure_logging sets up console format."""
        config = LoggingConfig(level="DEBUG", format="console")
        # Should not raise
        configure_logging(config)

    def test_get_logger_returns_bound_logger(self):
        """Test get_logger returns a configured logger."""
        configure_logging(LoggingConfig())
        logger = get_logger("test_module")

        # Logger should be callable for logging
        assert hasattr(logger, "info")
        assert hasattr(logger, "error")
        assert hasattr(logger, "debug")


class TestGlobalConfig:
    """Tests for global configuration management."""

    def test_get_config_returns_singleton(self):
        """Test get_config returns the same instance."""
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "test_token",
            "LONGCAT_API_KEY": "test_key",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config1 = get_config()
            config2 = get_config()

        assert config1 is config2

    def test_reset_config_clears_singleton(self):
        """Test reset_config allows reconfiguration."""
        env_vars = {
            "TELEGRAM_BOT_TOKEN": "first_token",
            "LONGCAT_API_KEY": "first_key",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config1 = get_config()

        reset_config()

        env_vars["TELEGRAM_BOT_TOKEN"] = "second_token"
        with patch.dict(os.environ, env_vars, clear=False):
            config2 = get_config()

        assert config1 is not config2
        assert config2.telegram.token == "second_token"
