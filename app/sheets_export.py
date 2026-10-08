"""Google Sheets export — sends daily profit & performance summary to a
Google Sheets spreadsheet for offline long-term portfolio review.

Uses the gspread library with a Google Service Account for authentication.
The user must:
  1. Create a service account in Google Cloud Console
  2. Enable the Google Sheets API
  3. Share the target spreadsheet with the service account email
  4. Provide the service account email, private key, and spreadsheet ID
     via the dashboard secrets

A background thread automatically exports the daily summary once per day.
Manual export is also available via the /api/sheets/export endpoint.
"""
import os
import threading
import time
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    Config, TradeLog, Opportunity, BotHeartbeat, AccountSnapshot,
    Log, Notification, CapitalTransaction, PerformanceSnapshot,
    TradeMode, BotName, BotState, ACTIVE_BOTS,
)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_export_state = {
    "last_export": None,
    "last_error": "",
    "auto_enabled": False,
    "thread": None,
}


def get_export_status() -> dict:
    return {
        "last_export": _export_state["last_export"],
        "last_error": _export_state["last_error"],
        "auto_enabled": _export_state["auto_enabled"],
        "configured": _is_configured(),
    }


def _is_configured() -> bool:
    return bool(
        os.environ.get("GOOGLE_SPREADSHEET_ID")
        and os.environ.get("GOOGLE_SERVICE_ACCOUNT_EMAIL")
        and os.environ.get("GOOGLE_PRIVATE_KEY")
    )


# ---------------------------------------------------------------------------
# Build the daily summary row
# ---------------------------------------------------------------------------

def _build_summary(db: Session) -> dict:
    """Collect today's performance data into a flat dict for spreadsheet export."""
    cfg = db.query(Config).first()
    if not cfg:
        return {}

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_trades = db.query(TradeLog).filter(TradeLog.executed_at >= today_start).all()

    all_trades = db.query(TradeLog).order_by(TradeLog.executed_at).all()
    paper_trades = [t for t in all_trades if t.mode == TradeMode.paper]
    real_trades = [t for t in all_trades if t.mode == TradeMode.real]

    total_profit = round(sum(t.actual_profit for t in today_trades), 4)
    wins = [t for t in today_trades if t.actual_profit > 0]
    losses = [t for t in today_trades if t.actual_profit <= 0]

    # Per-pair breakdown today
    by_pair = {}
    for t in today_trades:
        key = t.pair or "unknown"
        by_pair.setdefault(key, {"count": 0, "pnl": 0.0, "wins": 0})
        by_pair[key]["count"] += 1
        by_pair[key]["pnl"] += t.actual_profit
        if t.actual_profit > 0:
            by_pair[key]["wins"] += 1

    # All-time stats
    all_pnl = round(sum(t.actual_profit for t in all_trades), 4)
    all_wins = sum(1 for t in all_trades if t.actual_profit > 0)
    all_win_rate = round(all_wins / len(all_trades) * 100, 2) if all_trades else 0

    paper_pnl = round(sum(t.actual_profit for t in paper_trades), 4)
    real_pnl = round(sum(t.actual_profit for t in real_trades), 4)

    # Gas costs
    total_gas = round(sum(t.gas_cost_usd or 0 for t in today_trades), 4)
    total_slippage = round(sum(t.slippage_cost or 0 for t in today_trades), 4)

    # Best/worst pair today
    best_pair = max(by_pair.items(), key=lambda x: x[1]["pnl"]) if by_pair else None
    worst_pair = min(by_pair.items(), key=lambda x: x[1]["pnl"]) if by_pair else None

    # Bot status
    bots = db.query(BotHeartbeat).filter(BotHeartbeat.bot.in_(ACTIVE_BOTS)).all()
    active_bots = sum(1 for b in bots if b.state == BotState.running and not b.paused)

    balance = cfg.current_balance_paper if not cfg.is_real_execution else cfg.current_balance_real
    return_pct = round((balance - cfg.starting_capital) / cfg.starting_capital * 100, 2) if cfg.starting_capital else 0

    return {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "mode": "REAL" if cfg.is_real_execution else "PAPER",
        "is_running": cfg.is_running,
        "is_aggressive": cfg.is_aggressive,
        "balance": round(balance, 2),
        "starting_capital": cfg.starting_capital,
        "return_pct": return_pct,
        "today_profit": total_profit,
        "today_trades": len(today_trades),
        "today_wins": len(wins),
        "today_losses": len(losses),
        "today_win_rate": round(len(wins) / len(today_trades) * 100, 2) if today_trades else 0,
        "today_gas": total_gas,
        "today_slippage": total_slippage,
        "best_pair": best_pair[0] if best_pair else "",
        "best_pair_pnl": round(best_pair[1]["pnl"], 4) if best_pair else 0,
        "worst_pair": worst_pair[0] if worst_pair else "",
        "worst_pair_pnl": round(worst_pair[1]["pnl"], 4) if worst_pair else 0,
        "all_time_trades": len(all_trades),
        "all_time_pnl": all_pnl,
        "all_time_win_rate": all_win_rate,
        "paper_pnl": paper_pnl,
        "real_pnl": real_pnl,
        "active_bots": active_bots,
        "total_bots": len(ACTIVE_BOTS),
        "pairs_traded_today": len(by_pair),
    }


# ---------------------------------------------------------------------------
# Google Sheets write
# ---------------------------------------------------------------------------

SHEET_HEADERS = [
    "Date", "Timestamp", "Mode", "Running", "Aggressive",
    "Balance", "Starting Capital", "Return %",
    "Today Profit", "Today Trades", "Today Wins", "Today Losses", "Today Win Rate %",
    "Today Gas", "Today Slippage",
    "Best Pair", "Best Pair P/L", "Worst Pair", "Worst Pair P/L",
    "All-Time Trades", "All-Time P/L", "All-Time Win Rate %",
    "Paper P/L", "Real P/L",
    "Active Bots", "Total Bots", "Pairs Traded Today",
]


def _get_client():
    """Create an authorized gspread client from environment variables."""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info({
        "type": "service_account",
        "client_email": os.environ["GOOGLE_SERVICE_ACCOUNT_EMAIL"],
        "private_key": os.environ["GOOGLE_PRIVATE_KEY"].replace("\\n", "\n"),
        "token_uri": "https://oauth2.googleapis.com/token",
    }, scopes=scopes)
    return gspread.authorize(creds)


def export_to_sheets(db: Session) -> dict:
    """Export the daily summary to Google Sheets. Creates the sheet/headers if needed."""
    if not _is_configured():
        return {"ok": False, "error": "Google Sheets not configured. Set GOOGLE_SPREADSHEET_ID, GOOGLE_SERVICE_ACCOUNT_EMAIL, and GOOGLE_PRIVATE_KEY."}

    try:
        client = _get_client()
        spreadsheet_id = os.environ["GOOGLE_SPREADSHEET_ID"]
        ss = client.open_by_key(spreadsheet_id)

        # Use or create a "Daily Summary" worksheet
        try:
            sheet = ss.worksheet("Daily Summary")
        except Exception:
            sheet = ss.add_worksheet("Daily Summary", rows=1000, cols=30)
            sheet.append_row(SHEET_HEADERS)

        # Check if headers exist (row 1)
        first_row = sheet.row_values(1)
        if not first_row or first_row[0] != "Date":
            sheet.update("A1", [SHEET_HEADERS])

        summary = _build_summary(db)
        if not summary:
            return {"ok": False, "error": "No config/data to export"}

        row = [
            summary["date"], summary["timestamp"], summary["mode"],
            "Yes" if summary["is_running"] else "No",
            "Yes" if summary["is_aggressive"] else "No",
            summary["balance"], summary["starting_capital"], summary["return_pct"],
            summary["today_profit"], summary["today_trades"],
            summary["today_wins"], summary["today_losses"], summary["today_win_rate"],
            summary["today_gas"], summary["today_slippage"],
            summary["best_pair"], summary["best_pair_pnl"],
            summary["worst_pair"], summary["worst_pair_pnl"],
            summary["all_time_trades"], summary["all_time_pnl"], summary["all_time_win_rate"],
            summary["paper_pnl"], summary["real_pnl"],
            summary["active_bots"], summary["total_bots"], summary["pairs_traded_today"],
        ]

        sheet.append_row(row)

        _export_state["last_export"] = datetime.utcnow().isoformat()
        _export_state["last_error"] = ""

        db.add(Log(
            bot="system", level="info",
            message=f"📊 Exported daily summary to Google Sheets (row {sheet.row_count})",
        ))
        db.add(Notification(
            type="success", title="📊 Google Sheets Export",
            message=f"Daily summary exported to Google Sheets. {summary['today_trades']} trades, profit ${summary['today_profit']:.2f}.",
        ))
        db.commit()

        return {"ok": True, "row_count": sheet.row_count, "summary": summary}

    except Exception as e:
        _export_state["last_error"] = str(e)
        return {"ok": False, "error": str(e)}


def test_sheets_connection() -> dict:
    """Test the Google Sheets connection without writing data."""
    if not _is_configured():
        return {"ok": False, "error": "Not configured", "configured": False}

    try:
        client = _get_client()
        spreadsheet_id = os.environ["GOOGLE_SPREADSHEET_ID"]
        ss = client.open_by_key(spreadsheet_id)
        return {
            "ok": True,
            "configured": True,
            "spreadsheet_title": ss.title,
            "sheets": [w.title for w in ss.worksheets()],
        }
    except Exception as e:
        return {"ok": False, "configured": True, "error": str(e)}


# ---------------------------------------------------------------------------
# Background auto-export thread
# ---------------------------------------------------------------------------

def _auto_export_loop():
    """Background thread: exports daily summary once per day at ~00:30 UTC."""
    last_export_day = None
    while _export_state["auto_enabled"]:
        try:
            now = datetime.utcnow()
            # Export once per day, after midnight UTC
            today = now.strftime("%Y-%m-%d")
            if now.hour >= 0 and now.minute >= 30 and today != last_export_day:
                db = SessionLocal()
                try:
                    result = export_to_sheets(db)
                    if result.get("ok"):
                        last_export_day = today
                    else:
                        print(f"[sheets_export] Auto-export failed: {result.get('error')}")
                finally:
                    db.close()
        except Exception as e:
            print(f"[sheets_export] Auto-export error: {e}")

        time.sleep(300)  # check every 5 minutes


def start_auto_export():
    """Start the automatic daily export background thread."""
    if _export_state["auto_enabled"]:
        return {"ok": False, "error": "Auto-export already running"}
    _export_state["auto_enabled"] = True
    t = threading.Thread(target=_auto_export_loop, daemon=True)
    _export_state["thread"] = t
    t.start()
    return {"ok": True, "message": "Auto daily export started"}


def stop_auto_export():
    """Stop the automatic daily export."""
    _export_state["auto_enabled"] = False
    return {"ok": True, "message": "Auto export stopped"}
