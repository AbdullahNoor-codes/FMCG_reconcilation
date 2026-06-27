"""
Engine 4 — Cost Reconciliation
Cross-references COGS, Logistics, and Marketing costs from the
Sales Sub-Ledger (File 1) against GL booked costs (File 2).
Detects cost leakage, margin erosion, and anomalous spending.
"""

import pandas as pd
import numpy as np


class CostReconciler:
    MARGIN_ALERT_THRESHOLD = 15.0   # Flag if profit margin drops below 15%
    COST_VARIANCE_THRESHOLD = 0.05  # 5% variance triggers a flag

    def __init__(self, sales_df: pd.DataFrame, gl_df: pd.DataFrame):
        self.sales = sales_df.copy()
        self.gl = gl_df.copy()
        self.results = []
        self.anomalies = []
        self.summary_data = {}

    def _prepare_sales(self):
        df = self.sales.copy()
        df["Order_Date"] = pd.to_datetime(df["Order_Date"], errors="coerce")
        df["Year"] = df["Order_Date"].dt.year
        df["Month"] = df["Order_Date"].dt.month
        for col in ["Gross_Sales_USD", "COGS_USD", "Logistics_Cost_USD",
                    "Marketing_Spend_USD", "Net_Revenue_USD", "Profit_USD", "Profit_Margin_Pct"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        return df

    def _prepare_gl(self):
        df = self.gl.copy()
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
        df["Month"] = pd.to_numeric(df["Month"], errors="coerce")
        for col in ["COGS_USD", "Logistics_Cost_USD", "Marketing_Spend_USD", "Profit_USD"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        return df

    def reconcile(self):
        sales = self._prepare_sales()
        gl = self._prepare_gl()

        # Aggregate sales costs by year/month/category
        agg = sales.groupby(["Year", "Month", "Product_Category"]).agg(
            sl_cogs=("COGS_USD", "sum"),
            sl_logistics=("Logistics_Cost_USD", "sum"),
            sl_marketing=("Marketing_Spend_USD", "sum"),
            sl_gross=("Gross_Sales_USD", "sum"),
            sl_profit=("Profit_USD", "sum"),
            avg_margin=("Profit_Margin_Pct", "mean"),
            order_count=("Order_ID", "count")
        ).reset_index()

        gl_renamed = gl.rename(columns={
            "COGS_USD": "gl_cogs",
            "Logistics_Cost_USD": "gl_logistics",
            "Marketing_Spend_USD": "gl_marketing",
            "Profit_USD": "gl_profit"
        })

        merged = agg.merge(gl_renamed, on=["Year", "Month", "Product_Category"], how="outer").fillna(0)

        rows = []
        anomalies = []

        for _, r in merged.iterrows():
            cogs_var = round(r["sl_cogs"] - r["gl_cogs"], 2)
            logistics_var = round(r["sl_logistics"] - r["gl_logistics"], 2)
            marketing_var = round(r["sl_marketing"] - r["gl_marketing"], 2)
            profit_var = round(r["sl_profit"] - r["gl_profit"], 2)

            cogs_var_pct = abs(cogs_var / r["gl_cogs"] * 100) if r["gl_cogs"] != 0 else 0
            total_cost_sl = r["sl_cogs"] + r["sl_logistics"] + r["sl_marketing"]
            total_cost_gl = r["gl_cogs"] + r["gl_logistics"] + r["gl_marketing"]
            total_cost_var = round(total_cost_sl - total_cost_gl, 2)

            # Status logic
            flags = []
            if abs(cogs_var_pct) > self.COST_VARIANCE_THRESHOLD * 100:
                flags.append("COGS_DRIFT")
            if r["avg_margin"] < self.MARGIN_ALERT_THRESHOLD and r["sl_gross"] > 0:
                flags.append("MARGIN_ALERT")
            if abs(logistics_var) > 5000:
                flags.append("LOGISTICS_SPIKE")
            if abs(marketing_var / r["sl_gross"] * 100) > 15 if r["sl_gross"] > 0 else False:
                flags.append("MARKETING_OVERSPEND")

            status = "FLAGGED" if flags else ("MATCHED" if abs(total_cost_var) < 1 else "VARIANCE")

            row = {
                "year": int(r["Year"]),
                "month": int(r["Month"]),
                "category": r["Product_Category"],
                "orders": int(r.get("order_count", 0)),
                "sl_cogs": round(r["sl_cogs"], 2),
                "gl_cogs": round(r["gl_cogs"], 2),
                "cogs_variance": cogs_var,
                "sl_logistics": round(r["sl_logistics"], 2),
                "gl_logistics": round(r["gl_logistics"], 2),
                "logistics_variance": logistics_var,
                "sl_marketing": round(r["sl_marketing"], 2),
                "gl_marketing": round(r["gl_marketing"], 2),
                "marketing_variance": marketing_var,
                "profit_variance": profit_var,
                "total_cost_variance": total_cost_var,
                "avg_margin_pct": round(r["avg_margin"], 2),
                "flags": ", ".join(flags) if flags else "NONE",
                "status": status
            }
            rows.append(row)

            if flags:
                anomalies.append({**row, "flag_detail": flags})

        self.results = rows
        self.anomalies = anomalies

        matched = sum(1 for r in rows if r["status"] == "MATCHED")
        flagged = len(anomalies)
        total_cogs_var = sum(abs(r["cogs_variance"]) for r in rows)
        total_logistics_var = sum(abs(r["logistics_variance"]) for r in rows)
        margin_alerts = sum(1 for r in rows if "MARGIN_ALERT" in r["flags"])

        self.summary_data = {
            "engine": "Cost Reconciliation (COGS + Logistics + Marketing)",
            "total_periods": len(rows),
            "matched": matched,
            "flagged": flagged,
            "match_rate": round(matched / len(rows) * 100, 2) if rows else 0,
            "total_cogs_variance_usd": round(total_cogs_var, 2),
            "total_logistics_variance_usd": round(total_logistics_var, 2),
            "margin_alerts": margin_alerts,
            "risk_level": "HIGH" if flagged > 10 else "MEDIUM" if flagged > 5 else "LOW"
        }
        return self.results

    def summary(self):
        if not self.results:
            self.reconcile()
        return self.summary_data

    def cost_breakdown_chart(self):
        """Total SL vs GL cost by category."""
        if not self.results:
            self.reconcile()
        cats = sorted(set(r["category"] for r in self.results))
        sl_cogs = [round(sum(r["sl_cogs"] for r in self.results if r["category"] == c), 2) for c in cats]
        gl_cogs = [round(sum(r["gl_cogs"] for r in self.results if r["category"] == c), 2) for c in cats]
        return {"labels": cats, "sl_cogs": sl_cogs, "gl_cogs": gl_cogs}

    def margin_trend_chart(self):
        """Average margin per month across all categories."""
        if not self.results:
            self.reconcile()
        monthly = {}
        counts = {}
        for r in self.results:
            key = f"{r['year']}-{str(r['month']).zfill(2)}"
            monthly[key] = monthly.get(key, 0) + r["avg_margin_pct"]
            counts[key] = counts.get(key, 0) + 1
        keys = sorted(monthly.keys())
        return {
            "labels": keys,
            "avg_margin": [round(monthly[k] / counts[k], 2) for k in keys]
        }

    def anomaly_summary(self):
        """Top anomalies for display."""
        if not self.results:
            self.reconcile()
        return sorted(self.anomalies, key=lambda x: abs(x["total_cost_variance"]), reverse=True)[:20]