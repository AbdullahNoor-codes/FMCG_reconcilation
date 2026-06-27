"""
Engine 1 — Revenue Reconciliation
Compares order-level Sales Sub-Ledger (File 1) against monthly GL totals (File 2).
Detects booking errors, missing journal entries, and month-end mismatches.
"""

import pandas as pd
import numpy as np


class RevenueReconciler:
    TOLERANCE_PCT = 0.01  # 1% tolerance for rounding differences

    def __init__(self, sales_df: pd.DataFrame, gl_df: pd.DataFrame):
        self.sales = sales_df.copy()
        self.gl = gl_df.copy()
        self.results = []
        self.summary_data = {}

    def _prepare_sales(self):
        df = self.sales.copy()
        df["Order_Date"] = pd.to_datetime(df["Order_Date"], errors="coerce")
        df["Year"] = df["Order_Date"].dt.year
        df["Month"] = df["Order_Date"].dt.month
        for col in ["Gross_Sales_USD", "Net_Revenue_USD", "COGS_USD",
                    "Marketing_Spend_USD", "Logistics_Cost_USD", "Profit_USD"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        return df

    def _prepare_gl(self):
        df = self.gl.copy()
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
        df["Month"] = pd.to_numeric(df["Month"], errors="coerce")
        for col in ["Gross_Sales_USD", "Net_Revenue_USD", "COGS_USD",
                    "Marketing_Spend_USD", "Logistics_Cost_USD", "Profit_USD"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        return df

    def reconcile(self):
        sales = self._prepare_sales()
        gl = self._prepare_gl()

        # Aggregate sales by Year + Month + Product_Category
        agg = sales.groupby(["Year", "Month", "Product_Category"]).agg(
            sl_gross=("Gross_Sales_USD", "sum"),
            sl_net=("Net_Revenue_USD", "sum"),
            sl_cogs=("COGS_USD", "sum"),
            sl_mkt=("Marketing_Spend_USD", "sum"),
            sl_logistics=("Logistics_Cost_USD", "sum"),
            sl_profit=("Profit_USD", "sum"),
            order_count=("Order_ID", "count")
        ).reset_index()

        # Merge with GL
        gl_renamed = gl.rename(columns={
            "Gross_Sales_USD": "gl_gross",
            "Net_Revenue_USD": "gl_net",
            "COGS_USD": "gl_cogs",
            "Marketing_Spend_USD": "gl_mkt",
            "Logistics_Cost_USD": "gl_logistics",
            "Profit_USD": "gl_profit"
        })

        merged = agg.merge(gl_renamed, on=["Year", "Month", "Product_Category"], how="outer")
        merged = merged.fillna(0)

        rows = []
        for _, r in merged.iterrows():
            variance_gross = round(r["sl_gross"] - r["gl_gross"], 2)
            variance_net = round(r["sl_net"] - r["gl_net"], 2)
            variance_profit = round(r["sl_profit"] - r["gl_profit"], 2)

            pct_var = abs(variance_gross / r["gl_gross"] * 100) if r["gl_gross"] != 0 else 0

            if abs(variance_gross) < 0.01:
                status = "MATCHED"
            elif pct_var <= self.TOLERANCE_PCT * 100:
                status = "WITHIN_TOLERANCE"
            elif r["gl_gross"] == 0:
                status = "MISSING_IN_GL"
            elif r["sl_gross"] == 0:
                status = "MISSING_IN_SALES"
            else:
                status = "MISMATCH"

            rows.append({
                "year": int(r["Year"]),
                "month": int(r["Month"]),
                "category": r["Product_Category"],
                "orders": int(r.get("order_count", 0)),
                "sl_gross": round(r["sl_gross"], 2),
                "gl_gross": round(r["gl_gross"], 2),
                "variance_gross": variance_gross,
                "variance_net": round(variance_net, 2),
                "variance_profit": round(variance_profit, 2),
                "variance_pct": round(pct_var, 3),
                "status": status
            })

        self.results = rows

        matched = sum(1 for r in rows if r["status"] == "MATCHED")
        mismatches = sum(1 for r in rows if r["status"] == "MISMATCH")
        missing_gl = sum(1 for r in rows if r["status"] == "MISSING_IN_GL")
        total_variance = sum(abs(r["variance_gross"]) for r in rows)
        match_rate = round(matched / len(rows) * 100, 2) if rows else 0

        self.summary_data = {
            "engine": "Revenue Reconciliation (Sales vs GL)",
            "total_periods": len(rows),
            "matched": matched,
            "mismatches": mismatches,
            "missing_in_gl": missing_gl,
            "match_rate": match_rate,
            "total_variance_usd": round(total_variance, 2),
            "risk_level": "HIGH" if total_variance > 50000 else "MEDIUM" if total_variance > 10000 else "LOW"
        }
        return self.results

    def summary(self):
        if not self.results:
            self.reconcile()
        return self.summary_data

    def get_mismatches(self):
        return [r for r in self.results if r["status"] in ("MISMATCH", "MISSING_IN_GL", "MISSING_IN_SALES")]

    def category_variance_chart(self):
        """Returns data for category-level variance bar chart."""
        if not self.results:
            self.reconcile()
        cats = {}
        for r in self.results:
            c = r["category"]
            cats.setdefault(c, 0)
            cats[c] += abs(r["variance_gross"])
        return {"labels": list(cats.keys()), "values": [round(v, 2) for v in cats.values()]}

    def monthly_trend_chart(self):
        """Returns monthly aggregated variance for trend line."""
        if not self.results:
            self.reconcile()
        monthly = {}
        for r in self.results:
            key = f"{r['year']}-{str(r['month']).zfill(2)}"
            monthly.setdefault(key, {"sl": 0, "gl": 0})
            monthly[key]["sl"] += r["sl_gross"]
            monthly[key]["gl"] += r["gl_gross"]
        keys = sorted(monthly.keys())
        return {
            "labels": keys,
            "sl_values": [round(monthly[k]["sl"], 2) for k in keys],
            "gl_values": [round(monthly[k]["gl"], 2) for k in keys]
        }