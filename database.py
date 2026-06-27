"""
database.py — SQLite persistence for reconciliation run history.
Stores summary results from all 4 engines for audit trail and trending.
"""

import sqlite3
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "recon_history.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT,
            run_label TEXT,
            e1_match_rate REAL, e1_variance REAL, e1_risk TEXT,
            e2_match_rate REAL, e2_missing_usd REAL, e2_risk TEXT,
            e3_attainment REAL, e3_variance REAL, e3_risk TEXT,
            e4_flagged INTEGER, e4_cogs_var REAL, e4_risk TEXT,
            total_records INTEGER,
            notes TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_run(summaries: dict, label: str = "Manual Run"):
    conn = get_conn()
    c = conn.cursor()
    e1 = summaries.get("revenue", {})
    e2 = summaries.get("bank", {})
    e3 = summaries.get("budget", {})
    e4 = summaries.get("cost", {})
    total = (e1.get("total_periods", 0) + e2.get("total_sales_days", 0) +
             e3.get("total_periods", 0) + e4.get("total_periods", 0))
    c.execute("""
        INSERT INTO runs
        (run_date, run_label,
         e1_match_rate, e1_variance, e1_risk,
         e2_match_rate, e2_missing_usd, e2_risk,
         e3_attainment, e3_variance, e3_risk,
         e4_flagged, e4_cogs_var, e4_risk,
         total_records, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        label,
        e1.get("match_rate"), e1.get("total_variance_usd"), e1.get("risk_level"),
        e2.get("match_rate"), e2.get("missing_from_bank_usd"), e2.get("risk_level"),
        e3.get("overall_attainment_pct"), e3.get("total_variance_usd"), e3.get("risk_level"),
        e4.get("flagged"), e4.get("total_cogs_variance_usd"), e4.get("risk_level"),
        total, ""
    ))
    conn.commit()
    run_id = c.lastrowid
    conn.close()
    return run_id


def get_all_runs():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM runs ORDER BY id DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_run(run_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM runs WHERE id=?", (run_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None