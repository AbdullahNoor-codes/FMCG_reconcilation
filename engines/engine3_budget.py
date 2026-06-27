"""
Engine 3 — Budget vs Actual Reconciliation
Compares actual net revenue from the Sales Sub-Ledger (File 1)
against corporate budget targets (File 4) by Region and Year.
Provides variance analysis, attainment %, and performance flags.
"""

import pandas as pd
import numpy as np


class BudgetReconciler:
    def __init__(self, sales_df: pd.DataFrame, budget_df: pd.DataFrame):
        self.sales = sales_df.copy()
        self.budget = budget_df.copy()
        self.results = []
        self.summary_data = {}

    def _prepare_sales(self):
        df = self.sales.copy()
        df["Net_Revenue_USD"] = pd.to_numeric(df["Net_Revenue_USD"], errors="coerce").fillna(0)
        df["Profit_USD"] = pd.to_numeric(df["Profit_USD"], errors="coerce").fillna(0)
        df["Marketing_Spend_USD"] = pd.to_numeric(df["Marketing_Spend_USD"], errors="coerce").fillna(0)
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
        agg = df.groupby(["Year", "Region"]).agg(
            actual_revenue=("Net_Revenue_USD", "sum"),
            actual_profit=("Profit_USD", "sum"),
            actual_marketing=("Marketing_Spend_USD", "sum"),
            order_count=("Order_ID", "count")
        ).reset_index()
        return agg

    def _prepare_budget(self):
        df = self.budget.copy()
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
        df["Budgeted_Revenue_USD"] = pd.to_numeric(df["Budgeted_Revenue_USD"], errors="coerce").fillna(0)
        return df

    def reconcile(self):
        sales_agg = self._prepare_sales()
        budget = self._prepare_budget()

        merged = budget.merge(sales_agg, on=["Year", "Region"], how="left")
        merged["actual_revenue"] = merged["actual_revenue"].fillna(0)
        merged["actual_profit"] = merged["actual_profit"].fillna(0)
        merged["actual_marketing"] = merged["actual_marketing"].fillna(0)
        merged["order_count"] = merged["order_count"].fillna(0)

        rows = []
        for _, r in merged.iterrows():
            budget_rev = r["Budgeted_Revenue_USD"]
            actual_rev = r["actual_revenue"]
            variance = round(actual_rev - budget_rev, 2)
            variance_pct = round(variance / budget_rev * 100, 2) if budget_rev != 0 else 0
            attainment = round(actual_rev / budget_rev * 100, 2) if budget_rev != 0 else 0

            if attainment >= 100:
                status = "ON_TARGET"
                performance = "EXCEEDED"
            elif attainment >= 90:
                status = "NEAR_TARGET"
                performance = "NEAR_TARGET"
            elif attainment >= 75:
                status = "BELOW_TARGET"
                performance = "UNDERPERFORMING"
            else:
                status = "CRITICAL"
                performance = "CRITICAL_MISS"

            rows.append({
                "year": int(r["Year"]),
                "region": r["Region"],
                "budget_revenue": round(budget_rev, 2),
                "actual_revenue": round(actual_rev, 2),
                "variance_usd": variance,
                "variance_pct": variance_pct,
                "attainment_pct": attainment,
                "actual_profit": round(r["actual_profit"], 2),
                "actual_marketing": round(r["actual_marketing"], 2),
                "order_count": int(r["order_count"]),
                "marketing_roi": round(actual_rev / r["actual_marketing"], 2) if r["actual_marketing"] > 0 else 0,
                "status": status,
                "performance": performance
            })

        self.results = rows

        on_target = sum(1 for r in rows if r["status"] == "ON_TARGET")
        critical = sum(1 for r in rows if r["status"] == "CRITICAL")
        total_budget = sum(r["budget_revenue"] for r in rows)
        total_actual = sum(r["actual_revenue"] for r in rows)
        overall_attainment = round(total_actual / total_budget * 100, 2) if total_budget else 0
        total_variance = round(total_actual - total_budget, 2)

        self.summary_data = {
            "engine": "Budget vs Actual Reconciliation",
            "total_periods": len(rows),
            "on_target": on_target,
            "critical_misses": critical,
            "overall_attainment_pct": overall_attainment,
            "total_budget_usd": round(total_budget, 2),
            "total_actual_usd": round(total_actual, 2),
            "total_variance_usd": total_variance,
            "risk_level": "HIGH" if critical > 2 else "MEDIUM" if critical > 0 else "LOW"
        }
        return self.results

    def summary(self):
        if not self.results:
            self.reconcile()
        return self.summary_data

    def attainment_by_region_chart(self):
        """Attainment % per region for the latest year."""
        if not self.results:
            self.reconcile()
        latest_year = max(r["year"] for r in self.results)
        latest = [r for r in self.results if r["year"] == latest_year]
        return {
            "labels": [r["region"] for r in latest],
            "attainment": [r["attainment_pct"] for r in latest],
            "budget": [r["budget_revenue"] for r in latest],
            "actual": [r["actual_revenue"] for r in latest]
        }

    def yearly_trend_chart(self):
        """Year-over-year budget vs actual total."""
        if not self.results:
            self.reconcile()
        years = sorted(set(r["year"] for r in self.results))
        budget_by_year = {}
        actual_by_year = {}
        for r in self.results:
            y = r["year"]
            budget_by_year[y] = budget_by_year.get(y, 0) + r["budget_revenue"]
            actual_by_year[y] = actual_by_year.get(y, 0) + r["actual_revenue"]
        return {
            "labels": [str(y) for y in years],
            "budget": [round(budget_by_year[y], 2) for y in years],
            "actual": [round(actual_by_year[y], 2) for y in years]
        }

    def roi_by_region(self):
        """Marketing ROI per region."""
        if not self.results:
            self.reconcile()
        latest_year = max(r["year"] for r in self.results)
        latest = [r for r in self.results if r["year"] == latest_year]
        return {
            "labels": [r["region"] for r in latest],
            "roi": [r["marketing_roi"] for r in latest]
        }