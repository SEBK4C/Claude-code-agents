"""
Export handlers for the Telegram Trade Journal Bot.

This module provides:
- CSV export with account and date range filtering
- JSON export with metadata and nested data
- PDF report generation with charts and trade tables
"""

import csv
import io
import json
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import get_logger
from database.db import get_session
from database.models import Account, Strategy, Tag, Trade, TradeStatus, TradeTag, User
from handlers.accounts import get_user_accounts, get_user_by_telegram_id
from services.analytics_service import get_analytics_service
from services.report_service import get_report_service
from utils.helpers import format_currency, format_datetime
from utils.keyboards import back_cancel_keyboard, back_to_menu_keyboard

logger = get_logger(__name__)

# Conversation states
EXPORT_FORMAT = 0
EXPORT_ACCOUNT = 1
EXPORT_DATE_RANGE = 2

# Context keys
EXPORT_KEY = "export_wizard"

# Export directory
EXPORT_DIR = Path("exports")


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder for Decimal types."""

    def default(self, obj: Any) -> Any:
        """Convert Decimal to float for JSON serialization."""
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        return super().default(obj)


def export_format_keyboard() -> InlineKeyboardMarkup:
    """
    Create keyboard for selecting export format.

    Returns:
        InlineKeyboardMarkup: Export format selection keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton("CSV", callback_data="export_format_csv"),
            InlineKeyboardButton("JSON", callback_data="export_format_json"),
        ],
        [
            InlineKeyboardButton("PDF Report", callback_data="export_format_pdf"),
        ],
        [
            InlineKeyboardButton("Back to Menu", callback_data="menu_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def export_account_keyboard(accounts: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """
    Create keyboard for selecting account filter.

    Args:
        accounts: List of (account_id, account_name) tuples.

    Returns:
        InlineKeyboardMarkup: Account selection keyboard.
    """
    keyboard = []

    keyboard.append([
        InlineKeyboardButton("All Accounts", callback_data="export_account_all"),
    ])

    for account_id, account_name in accounts:
        keyboard.append([
            InlineKeyboardButton(account_name, callback_data=f"export_account_{account_id}"),
        ])

    keyboard.append([
        InlineKeyboardButton("Cancel", callback_data="export_cancel"),
    ])

    return InlineKeyboardMarkup(keyboard)


def export_date_range_keyboard() -> InlineKeyboardMarkup:
    """
    Create keyboard for selecting date range.

    Returns:
        InlineKeyboardMarkup: Date range selection keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton("This Week", callback_data="export_range_week"),
            InlineKeyboardButton("This Month", callback_data="export_range_month"),
        ],
        [
            InlineKeyboardButton("Last 3 Months", callback_data="export_range_3months"),
            InlineKeyboardButton("This Year", callback_data="export_range_year"),
        ],
        [
            InlineKeyboardButton("All Time", callback_data="export_range_all"),
        ],
        [
            InlineKeyboardButton("Cancel", callback_data="export_cancel"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_date_range(range_key: str) -> tuple[Optional[date], Optional[date]]:
    """
    Get start and end dates for a date range key.

    Args:
        range_key: The range key (week, month, 3months, year, all).

    Returns:
        tuple: (start_date, end_date) - None for all time.
    """
    today = date.today()

    if range_key == "week":
        start = today - timedelta(days=today.weekday())
        return start, today
    elif range_key == "month":
        start = today.replace(day=1)
        return start, today
    elif range_key == "3months":
        start = today - timedelta(days=90)
        return start, today
    elif range_key == "year":
        start = today.replace(month=1, day=1)
        return start, today
    else:  # all
        return None, None


async def get_trades_for_export(
    session: AsyncSession,
    user_id: int,
    account_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[Trade]:
    """
    Fetch trades for export with all related data.

    Args:
        session: Database session.
        user_id: Internal user ID.
        account_id: Optional account filter.
        start_date: Optional start date filter.
        end_date: Optional end date filter.

    Returns:
        list[Trade]: List of trades with strategy and tags loaded.
    """
    # Get user's account IDs
    if account_id:
        account_ids = [account_id]
    else:
        accounts_result = await session.execute(
            select(Account.id)
            .where(Account.user_id == user_id)
            .where(Account.is_active == True)
        )
        account_ids = [row[0] for row in accounts_result.fetchall()]

    if not account_ids:
        return []

    # Build query
    query = (
        select(Trade)
        .options(
            selectinload(Trade.strategy),
            selectinload(Trade.trade_tags).selectinload(TradeTag.tag),
            selectinload(Trade.account),
        )
        .where(Trade.account_id.in_(account_ids))
        .where(Trade.status == TradeStatus.CLOSED)
    )

    if start_date:
        query = query.where(Trade.closed_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.where(Trade.closed_at <= datetime.combine(end_date, datetime.max.time()))

    query = query.order_by(Trade.closed_at)

    result = await session.execute(query)
    return list(result.scalars().all())


def generate_csv_export(trades: list[Trade]) -> bytes:
    """
    Generate CSV export bytes from trades.

    Args:
        trades: List of trades to export.

    Returns:
        bytes: UTF-8 encoded CSV data.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow([
        "id",
        "account",
        "instrument",
        "direction",
        "entry_price",
        "exit_price",
        "sl",
        "tp",
        "lot_size",
        "pnl",
        "pnl_percent",
        "strategy",
        "tags",
        "notes",
        "opened_at",
        "closed_at",
    ])

    # Write data rows
    for trade in trades:
        tags = ",".join([tt.tag.name for tt in trade.trade_tags]) if trade.trade_tags else ""
        strategy = trade.strategy.name if trade.strategy else ""
        account_name = trade.account.name if trade.account else ""

        writer.writerow([
            trade.id,
            account_name,
            trade.instrument,
            trade.direction.value,
            str(trade.entry_price),
            str(trade.exit_price) if trade.exit_price else "",
            str(trade.sl_price) if trade.sl_price else "",
            str(trade.tp_price) if trade.tp_price else "",
            str(trade.lot_size),
            str(trade.pnl) if trade.pnl else "",
            str(trade.pnl_percent) if trade.pnl_percent else "",
            strategy,
            tags,
            trade.notes or "",
            trade.opened_at.isoformat() if trade.opened_at else "",
            trade.closed_at.isoformat() if trade.closed_at else "",
        ])

    return output.getvalue().encode("utf-8")


async def generate_json_export(
    session: AsyncSession,
    trades: list[Trade],
    user_id: int,
    account_id: Optional[int] = None,
) -> bytes:
    """
    Generate JSON export bytes from trades with metadata.

    Args:
        session: Database session.
        trades: List of trades to export.
        user_id: Internal user ID.
        account_id: Optional account filter.

    Returns:
        bytes: UTF-8 encoded JSON data.
    """
    # Build metadata
    metadata = {
        "export_date": datetime.utcnow().isoformat(),
        "trade_count": len(trades),
        "export_type": "trade_journal",
        "version": "1.0",
    }

    # Get account summaries
    if account_id:
        account_result = await session.execute(
            select(Account).where(Account.id == account_id)
        )
        accounts = [account_result.scalar_one_or_none()]
        accounts = [a for a in accounts if a]
    else:
        accounts_result = await session.execute(
            select(Account)
            .where(Account.user_id == user_id)
            .where(Account.is_active == True)
        )
        accounts = list(accounts_result.scalars().all())

    account_summaries = []
    for account in accounts:
        if account:
            total_pnl = sum(
                t.pnl for t in trades
                if t.account_id == account.id and t.pnl
            )
            account_summaries.append({
                "id": account.id,
                "name": account.name,
                "broker": account.broker,
                "currency": account.currency,
                "starting_balance": float(account.starting_balance),
                "current_balance": float(account.current_balance),
                "total_pnl": float(total_pnl) if total_pnl else 0,
            })

    # Build trades array
    trades_data = []
    for trade in trades:
        trade_dict = {
            "id": trade.id,
            "account_id": trade.account_id,
            "account_name": trade.account.name if trade.account else None,
            "instrument": trade.instrument,
            "direction": trade.direction.value,
            "entry_price": float(trade.entry_price),
            "exit_price": float(trade.exit_price) if trade.exit_price else None,
            "sl_price": float(trade.sl_price) if trade.sl_price else None,
            "tp_price": float(trade.tp_price) if trade.tp_price else None,
            "lot_size": float(trade.lot_size),
            "pnl": float(trade.pnl) if trade.pnl else None,
            "pnl_percent": float(trade.pnl_percent) if trade.pnl_percent else None,
            "status": trade.status.value,
            "opened_at": trade.opened_at.isoformat() if trade.opened_at else None,
            "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
            "notes": trade.notes,
            "strategy": {
                "id": trade.strategy.id,
                "name": trade.strategy.name,
                "description": trade.strategy.description,
            } if trade.strategy else None,
            "tags": [
                {"id": tt.tag.id, "name": tt.tag.name}
                for tt in trade.trade_tags
            ] if trade.trade_tags else [],
        }
        trades_data.append(trade_dict)

    # Combine into export object
    export_data = {
        "metadata": metadata,
        "accounts": account_summaries,
        "trades": trades_data,
    }

    return json.dumps(export_data, indent=2, cls=DecimalEncoder).encode("utf-8")


def generate_pdf_export(
    trades: list[Trade],
    analytics_data: Any,
    equity_chart: Optional[bytes] = None,
    account_name: str = "All Accounts",
    date_range_desc: str = "All Time",
) -> bytes:
    """
    Generate PDF report bytes from trades and analytics.

    Args:
        trades: List of trades to export.
        analytics_data: Analytics result for metrics.
        equity_chart: Optional equity curve chart bytes.
        account_name: Account name for title.
        date_range_desc: Date range description.

    Returns:
        bytes: PDF file bytes.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from reportlab.platypus import (
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()

    # Title style
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        spaceAfter=30,
        alignment=1,  # Center
    )

    subtitle_style = ParagraphStyle(
        "CustomSubtitle",
        parent=styles["Normal"],
        fontSize=12,
        spaceAfter=10,
        alignment=1,
    )

    # Page 1: Title page
    elements.append(Spacer(1, 2 * inch))
    elements.append(Paragraph("Trade Journal Report", title_style))
    elements.append(Paragraph(f"Account: {account_name}", subtitle_style))
    elements.append(Paragraph(f"Period: {date_range_desc}", subtitle_style))
    elements.append(Paragraph(
        f"Generated: {datetime.utcnow().strftime('%B %d, %Y %H:%M UTC')}",
        subtitle_style,
    ))
    elements.append(Spacer(1, 1 * inch))

    # Account summary
    if analytics_data:
        summary_data = [
            ["Metric", "Value"],
            ["Total Trades", str(analytics_data.total_trades)],
            ["Winning Trades", str(analytics_data.winning_trades)],
            ["Losing Trades", str(analytics_data.losing_trades)],
            ["Win Rate", f"{analytics_data.win_rate}%"],
            ["Net P&L", f"${analytics_data.net_profit}"],
            ["Profit Factor", str(analytics_data.profit_factor)],
            ["Max Drawdown", f"${analytics_data.max_drawdown}"],
        ]

        summary_table = Table(summary_data, colWidths=[2.5 * inch, 2.5 * inch])
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 12),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(summary_table)

    # Page break
    from reportlab.platypus import PageBreak
    elements.append(PageBreak())

    # Page 2: Key metrics dashboard
    elements.append(Paragraph("Key Metrics Dashboard", styles["Heading1"]))
    elements.append(Spacer(1, 0.5 * inch))

    if analytics_data:
        metrics_data = [
            ["Win/Loss Metrics", "Risk Metrics", "Streak Metrics"],
            [
                f"Win Rate: {analytics_data.win_rate}%",
                f"Max DD: ${analytics_data.max_drawdown}",
                f"Best Streak: {analytics_data.best_streak}",
            ],
            [
                f"Avg Win: ${analytics_data.average_win}",
                f"Max DD %: {analytics_data.max_drawdown_percent}%",
                f"Worst Streak: {analytics_data.worst_streak}",
            ],
            [
                f"Avg Loss: ${analytics_data.average_loss}",
                f"Profit Factor: {analytics_data.profit_factor}",
                f"Current: {analytics_data.current_streak}",
            ],
            [
                f"Avg R:R: {analytics_data.average_rr}",
                f"Expectancy: ${analytics_data.expectancy}",
                "",
            ],
        ]

        metrics_table = Table(metrics_data, colWidths=[2.2 * inch, 2.2 * inch, 2.2 * inch])
        metrics_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.darkgreen),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(metrics_table)

    # Page break
    elements.append(PageBreak())

    # Page 3: Equity curve chart (if available)
    if equity_chart:
        elements.append(Paragraph("Equity Curve", styles["Heading1"]))
        elements.append(Spacer(1, 0.3 * inch))

        # Convert bytes to image
        chart_buffer = io.BytesIO(equity_chart)
        img = Image(chart_buffer, width=6 * inch, height=3.6 * inch)
        elements.append(img)
        elements.append(PageBreak())

    # Page 4+: Trade table (paginated)
    elements.append(Paragraph("Trade History", styles["Heading1"]))
    elements.append(Spacer(1, 0.3 * inch))

    if trades:
        # Create trade table with pagination (20 trades per page)
        trades_per_page = 20

        for page_start in range(0, len(trades), trades_per_page):
            page_trades = trades[page_start:page_start + trades_per_page]

            trade_data = [["#", "Instrument", "Dir", "Entry", "Exit", "P&L", "Date"]]

            for trade in page_trades:
                pnl_str = f"${trade.pnl}" if trade.pnl else "N/A"
                date_str = trade.closed_at.strftime("%m/%d") if trade.closed_at else "N/A"

                trade_data.append([
                    str(trade.id),
                    trade.instrument[:10],
                    trade.direction.value[:1].upper(),
                    str(trade.entry_price)[:10],
                    str(trade.exit_price)[:10] if trade.exit_price else "N/A",
                    pnl_str[:12],
                    date_str,
                ])

            trade_table = Table(
                trade_data,
                colWidths=[0.5 * inch, 1.2 * inch, 0.5 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch, 0.8 * inch],
            )
            trade_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ]))
            elements.append(trade_table)

            if page_start + trades_per_page < len(trades):
                elements.append(PageBreak())
                elements.append(Paragraph("Trade History (continued)", styles["Heading1"]))
                elements.append(Spacer(1, 0.3 * inch))
    else:
        elements.append(Paragraph("No trades found for the selected period.", styles["Normal"]))

    # Build PDF
    doc.build(elements)

    buffer.seek(0)
    return buffer.getvalue()


async def handle_export_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle the export menu callback - show format selection.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return ConversationHandler.END

    await query.answer()

    # Initialize export wizard state
    context.user_data[EXPORT_KEY] = {}

    await query.edit_message_text(
        "Export Trade Data\n"
        "=" * 25 + "\n\n"
        "Select export format:",
        reply_markup=export_format_keyboard(),
    )

    return EXPORT_FORMAT


async def handle_export_format(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle export format selection.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return ConversationHandler.END

    await query.answer()

    # Extract format
    export_format = query.data.replace("export_format_", "")
    context.user_data[EXPORT_KEY]["format"] = export_format

    # Get user accounts
    telegram_id = update.effective_user.id

    async with get_session() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            await query.edit_message_text(
                "Please use /start first to register.",
                reply_markup=back_to_menu_keyboard(),
            )
            return ConversationHandler.END

        accounts = await get_user_accounts(session, user.id)

        if not accounts:
            await query.edit_message_text(
                "No accounts found. Create an account first.",
                reply_markup=back_to_menu_keyboard(),
            )
            return ConversationHandler.END

        account_tuples = [(acc_id, name) for acc_id, name, _, _ in accounts]

    await query.edit_message_text(
        f"Export Format: {export_format.upper()}\n\n"
        "Select account to export:",
        reply_markup=export_account_keyboard(account_tuples),
    )

    return EXPORT_ACCOUNT


async def handle_export_account(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle export account selection.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END

    await query.answer()

    if query.data == "export_account_all":
        context.user_data[EXPORT_KEY]["account_id"] = None
        context.user_data[EXPORT_KEY]["account_name"] = "All Accounts"
    else:
        account_id_str = query.data.replace("export_account_", "")
        try:
            account_id = int(account_id_str)
            context.user_data[EXPORT_KEY]["account_id"] = account_id

            # Get account name
            async with get_session() as session:
                result = await session.execute(
                    select(Account.name).where(Account.id == account_id)
                )
                name = result.scalar_one_or_none()
                context.user_data[EXPORT_KEY]["account_name"] = name or f"Account #{account_id}"
        except ValueError:
            return EXPORT_ACCOUNT

    export_format = context.user_data[EXPORT_KEY].get("format", "csv")
    account_name = context.user_data[EXPORT_KEY].get("account_name", "All Accounts")

    await query.edit_message_text(
        f"Export Format: {export_format.upper()}\n"
        f"Account: {account_name}\n\n"
        "Select date range:",
        reply_markup=export_date_range_keyboard(),
    )

    return EXPORT_DATE_RANGE


async def handle_export_date_range(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle date range selection and execute export.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END to finish.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user or not query.message:
        return ConversationHandler.END

    await query.answer("Generating export...")

    # Extract date range
    range_key = query.data.replace("export_range_", "")
    start_date, end_date = get_date_range(range_key)

    export_data = context.user_data.get(EXPORT_KEY, {})
    export_format = export_data.get("format", "csv")
    account_id = export_data.get("account_id")
    account_name = export_data.get("account_name", "All Accounts")

    telegram_id = update.effective_user.id

    # Date range description
    date_range_desc = range_key.replace("_", " ").title()
    if range_key == "3months":
        date_range_desc = "Last 3 Months"
    elif range_key == "all":
        date_range_desc = "All Time"

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "User not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            # Fetch trades
            trades = await get_trades_for_export(
                session,
                user.id,
                account_id,
                start_date,
                end_date,
            )

            if not trades:
                await query.edit_message_text(
                    "No trades found for the selected criteria.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            # Generate timestamp for filename
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

            # Ensure export directory exists
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)

            # Generate export based on format
            if export_format == "csv":
                export_bytes = generate_csv_export(trades)
                filename = f"trades_export_{timestamp}.csv"
                mime_type = "text/csv"

            elif export_format == "json":
                export_bytes = await generate_json_export(
                    session, trades, user.id, account_id
                )
                filename = f"trades_export_{timestamp}.json"
                mime_type = "application/json"

            elif export_format == "pdf":
                # Get analytics for PDF
                analytics_service = get_analytics_service()
                analytics = await analytics_service.calculate_analytics(
                    user_id=user.id,
                    account_id=account_id,
                    start_date=start_date,
                    end_date=end_date,
                )

                # Generate equity chart if available
                equity_chart = None
                if analytics.equity_curve:
                    report_service = get_report_service()
                    equity_chart = report_service.generate_equity_curve(analytics)

                export_bytes = generate_pdf_export(
                    trades,
                    analytics,
                    equity_chart,
                    account_name,
                    date_range_desc,
                )
                filename = f"trade_report_{timestamp}.pdf"
                mime_type = "application/pdf"

            else:
                await query.edit_message_text(
                    "Unknown export format.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            # Save to exports directory
            file_path = EXPORT_DIR / filename
            with open(file_path, "wb") as f:
                f.write(export_bytes)

            # Delete the menu message
            try:
                await query.message.delete()
            except Exception:
                pass

            # Send file as document
            await query.message.chat.send_document(
                document=InputFile(
                    io.BytesIO(export_bytes),
                    filename=filename,
                ),
                caption=(
                    f"Trade Journal Export\n"
                    f"Format: {export_format.upper()}\n"
                    f"Account: {account_name}\n"
                    f"Period: {date_range_desc}\n"
                    f"Trades: {len(trades)}"
                ),
            )

            # Send success message
            await query.message.chat.send_message(
                f"Export complete! {len(trades)} trades exported.\n"
                f"File saved to: {file_path}",
                reply_markup=back_to_menu_keyboard(),
            )

            logger.info(
                "Export completed",
                telegram_id=telegram_id,
                format=export_format,
                trade_count=len(trades),
                filename=filename,
            )

    except Exception as e:
        logger.error("Export failed", error=str(e), telegram_id=telegram_id)
        await query.edit_message_text(
            f"Export failed: {str(e)}",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(EXPORT_KEY, None)
    return ConversationHandler.END


async def handle_export_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Cancel the export wizard.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END to finish.
    """
    context.user_data.pop(EXPORT_KEY, None)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Export cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )

    return ConversationHandler.END


# Export ConversationHandler
export_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(handle_export_menu, pattern="^menu_export$"),
    ],
    states={
        EXPORT_FORMAT: [
            CallbackQueryHandler(handle_export_format, pattern="^export_format_"),
        ],
        EXPORT_ACCOUNT: [
            CallbackQueryHandler(handle_export_account, pattern="^export_account_"),
        ],
        EXPORT_DATE_RANGE: [
            CallbackQueryHandler(handle_export_date_range, pattern="^export_range_"),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(handle_export_cancel, pattern="^(export_cancel|cancel|menu_main)$"),
    ],
    per_message=False,
)
