"""
Database package for the Telegram Trade Journal Bot.

This package provides:
- SQLAlchemy 2.0 async models (models.py)
- Database connection and session management (db.py)
- Database migrations and seeding (migrations.py)
"""

from database.db import get_session, init_db
from database.models import (
    Account,
    Base,
    Reminder,
    Strategy,
    Tag,
    Trade,
    TradeTag,
    Transaction,
    User,
)

__all__ = [
    # Models
    "Base",
    "Account",
    "Trade",
    "TradeTag",
    "Tag",
    "Strategy",
    "Transaction",
    "Reminder",
    "User",
    # Database functions
    "get_session",
    "init_db",
]
