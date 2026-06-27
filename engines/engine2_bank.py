"""
Engine 2 — Bank Reconciliation
Matches daily bank deposit settlements (File 3) against expected
net revenue from the Sales Sub-Ledger (File 1).
Flags missing deposits, excess deposits, and date timing differences.
"""

import pandas as pd
import numpy as np
from collections import defaultdict


class BankReconciler:
    DATE_TOLERANCE_DAYS = 3
    AMOUNT_TOLERANCE_PCT = 0.02  # 2% for settlement fees / FX

    def __init__(self, sales_df: pd.DataFrame, bank_df: pd.DataFrame):
        self.sales = sales_df.copy()
        self.bank = bank_df.copy()
        self.matches = []
        self.unmatched_bank = []
        self.unmatched_sales = []
        self.summary_data = {}

    def _prepare_sales(self):
        df = self.sales.copy()
        df["Order_Date"] = pd.to_datetime(df["Order_Date"], errors="coerce")
        df["Net_Revenue_USD"] = pd.to_numeric(df["Net_Revenue_USD"], errors="coerce").fillna(0)
        # Aggregate daily net revenue (what bank should have received each day)
        daily = df.groupby("Order_Date").agg(
            expected_amount=("Net_Revenue_USD", "sum"),
            order_count=("Order_ID", "count")
        ).reset_index()
        daily = daily.rename(columns={"Order_Date": "date"})
        daily["date"] = pd.to_datetime(daily["date"])
        daily["abs_amount"] = daily["expected_amount"].abs().round(2)
        return daily

    def _prepare_bank(self):
        df = self.bank.copy()
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
        df = df.rename(columns={"Date": "date", "Amount": "amount",
                                 "Type": "type", "Description": "description"})
        df["abs_amount"] = df["amount"].abs().round(2)
        df = df.reset_index(drop=True)
        return df

    def reconcile(self):
        sales_daily = self._prepare_sales()
        bank = self._prepare_bank()

        bank["used"] = False
        matched_pairs = []
        unmatched_sales_rows = []

        for _, srow in sales_daily.iterrows():
            best_idx = None
            best_rule = None
            best_diff = 999
            best_amt_diff = 999

            for bidx, brow in bank.iterrows():
                if brow["used"]:
                    continue

                date_diff = abs((srow["date"] - brow["date"]).days)
                if date_diff > self.DATE_TOLERANCE_DAYS:
                    continue

                # Check amount within tolerance
                if srow["abs_amount"] == 0:
                    continue
                amt_diff_pct = abs(srow["abs_amount"] - brow["abs_amount"]) / srow["abs_amount"]
                if amt_diff_pct > self.AMOUNT_TOLERANCE_PCT:
                    continue

                # Prefer exact date match, then closest
                if date_diff < best_diff or (date_diff == best_diff and amt_diff_pct < best_amt_diff):
                    best_idx = bidx
                    best_diff = date_diff
                    best_amt_diff = amt_diff_pct
                    if date_diff == 0:
                        best_rule = "RULE 1 — Exact date + amount"
                    else:
                        best_rule = f"RULE 2 — Amount match, {date_diff}d date diff"

            if best_idx is not None:
                bank.at[best_idx, "used"] = True
                matched_pairs.append({
                    "sales_date": str(srow["date"].date()),
                    "bank_date": str(bank.at[best_idx, "date"].date()),
                    "expected_amount": round(srow["expected_amount"], 2),
                    "bank_amount": round(bank.at[best_idx, "amount"], 2),
                    "variance": round(bank.at[best_idx, "amount"] - srow["expected_amount"], 2),
                    "date_diff_days": best_diff,
                    "orders": int(srow["order_count"]),
                    "rule": best_rule,
                    "status": "MATCHED"
                })
            else:
                unmatched_sales_rows.append({
                    "sales_date": str(srow["date"].date()),
                    "expected_amount": round(srow["expected_amount"], 2),
                    "orders": int(srow["order_count"]),
                    "status": "MISSING_IN_BANK"
                })

        unmatched_bank_rows = bank[~bank["used"]].copy()

        self.matches = matched_pairs
        self.unmatched_sales = unmatched_sales_rows
        self.unmatched_bank = unmatched_bank_rows.to_dict("records") if len(unmatched_bank_rows) else []

        total_sales = len(sales_daily)
        total_bank = len(bank)
        matched = len(matched_pairs)
        match_rate = round(matched / total_sales * 100, 2) if total_sales else 0

        total_variance = sum(abs(m["variance"]) for m in matched_pairs)
        missing_amount = sum(r["expected_amount"] for r in unmatched_sales_rows)
        excess_bank = sum(abs(r.get("amount", 0)) for r in self.unmatched_bank)

        self.summary_data = {
            "engine": "Bank Reconciliation (Sales vs Bank)",
            "total_sales_days": total_sales,
            "total_bank_entries": total_bank,
            "matched": matched,
            "unmatched_sales": len(unmatched_sales_rows),
            "unmatched_bank": len(self.unmatched_bank),
            "match_rate": match_rate,
            "total_variance_usd": round(total_variance, 2),
            "missing_from_bank_usd": round(missing_amount, 2),
            "excess_in_bank_usd": round(excess_bank, 2),
            "risk_level": "HIGH" if missing_amount > 100000 else "MEDIUM" if missing_amount > 20000 else "LOW"
        }
        return self.matches

    def summary(self):
        if not self.summary_data:
            self.reconcile()
        return self.summary_data

    def daily_variance_chart(self):
        """Returns matched pair dates and variances for scatter chart."""
        if not self.matches:
            self.reconcile()
        return {
            "dates": [m["sales_date"] for m in self.matches[:60]],
            "variances": [m["variance"] for m in self.matches[:60]]
        }

    def monthly_cashflow_chart(self):
        """Monthly actual vs expected cashflow."""
        if not self.matches:
            self.reconcile()
        monthly = {}
        for m in self.matches:
            key = m["sales_date"][:7]
            monthly.setdefault(key, {"expected": 0, "actual": 0})
            monthly[key]["expected"] += m["expected_amount"]
            monthly[key]["actual"] += m["bank_amount"]
        keys = sorted(monthly.keys())
        return {
            "labels": keys,
            "expected": [round(monthly[k]["expected"], 2) for k in keys],
            "actual": [round(monthly[k]["actual"], 2) for k in keys]
        }