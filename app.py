"""
app.py — FMCG Auto-Reconciliation System
Flask app · 4 engines · live filters · loading overlay · history replay
"""

import os, json
import pandas as pd
from flask import (Flask, render_template, request, redirect,
                   url_for, flash, jsonify, send_file, session)

import database as db
from engines.engine1_revenue import RevenueReconciler
from engines.engine2_bank    import BankReconciler
from engines.engine3_budget  import BudgetReconciler
from engines.engine4_cost    import CostReconciler

app = Flask(__name__)
app.secret_key = "fmcg-recon-2026-secret"

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "data")
RUNS_DIR  = os.path.join(DATA_DIR, "runs")          # full results stored here
os.makedirs(RUNS_DIR, exist_ok=True)

FILES = {
    "sales":  "fmcg_sales_marketing_profitability_2023_2025.csv",
    "gl":     "general_ledger_summary.csv",
    "bank":   "bank_statement.csv",
    "budget": "regional_budget_targets.csv",
}

# In-memory cache — holds the currently viewed run's full results
_cache = {}

db.init_db()


# ── helpers ───────────────────────────────────────────────────────────────────

def load_data():
    data, missing = {}, []
    for key, fname in FILES.items():
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            missing.append(fname)
        else:
            data[key] = pd.read_csv(path, dtype=str, keep_default_na=False)
    return data, missing


def _filter_list(rows, filters):
    out = []
    for r in rows:
        match = True
        for field, val in filters.items():
            if val in (None, "", "all", []):
                continue
            rv = str(r.get(field, ""))
            if isinstance(val, list):
                if rv not in [str(v) for v in val]:
                    match = False; break
            else:
                if rv != str(val):
                    match = False; break
        if match:
            out.append(r)
    return out


def _unique(rows, field):
    seen, out = set(), []
    for r in rows:
        v = str(r.get(field, ""))
        if v and v not in seen:
            seen.add(v); out.append(v)
    return sorted(out)


def _build_cache(e1, e2, e3, e4, run_id):
    """Populate _cache from engine objects."""
    e2_years = sorted(set(m["sales_date"][:4] for m in e2.matches)
                    | set(r["sales_date"][:4] for r in e2.unmatched_sales))
    return {
        "run_id": run_id,
        "e1": {
            "summary": e1.summary(), "results": e1.results,
            "mismatches": e1.get_mismatches(),
            "chart_cat": e1.category_variance_chart(),
            "chart_monthly": e1.monthly_trend_chart(),
            "years": _unique(e1.results, "year"),
            "months": _unique(e1.results, "month"),
            "categories": _unique(e1.results, "category"),
            "statuses": _unique(e1.results, "status"),
        },
        "e2": {
            "summary": e2.summary(),
            "matches": e2.matches,
            "unmatched_sales": e2.unmatched_sales,
            "unmatched_bank": e2.unmatched_bank,
            "chart_daily": e2.daily_variance_chart(),
            "chart_monthly": e2.monthly_cashflow_chart(),
            "years": e2_years,
            "statuses": ["MATCHED", "MISSING_IN_BANK"],
        },
        "e3": {
            "summary": e3.summary(), "results": e3.results,
            "chart_region": e3.attainment_by_region_chart(),
            "chart_yearly": e3.yearly_trend_chart(),
            "roi": e3.roi_by_region(),
            "years": _unique(e3.results, "year"),
            "regions": _unique(e3.results, "region"),
            "performances": _unique(e3.results, "performance"),
        },
        "e4": {
            "summary": e4.summary(),
            "anomalies": e4.anomaly_summary(),
            "all_results": e4.results,
            "chart_cost": e4.cost_breakdown_chart(),
            "chart_margin": e4.margin_trend_chart(),
            "years": _unique(e4.results, "year"),
            "months": _unique(e4.results, "month"),
            "categories": _unique(e4.results, "category"),
            "flag_types": ["COGS_DRIFT","MARGIN_ALERT","LOGISTICS_SPIKE","MARKETING_OVERSPEND"],
        },
    }


def _save_run_to_disk(cache: dict, run_id: int):
    """Persist full run results as JSON so history replay works."""
    path = os.path.join(RUNS_DIR, f"run_{run_id}.json")
    # Convert to JSON-safe types
    try:
        with open(path, "w") as f:
            json.dump(cache, f, default=str)
    except Exception as ex:
        print(f"Warning: could not save run to disk: {ex}")


def _load_run_from_disk(run_id: int):
    """Load a past run's full results from disk."""
    path = os.path.join(RUNS_DIR, f"run_{run_id}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    runs = db.get_all_runs()
    data, missing = load_data()
    file_status = {k: os.path.exists(os.path.join(DATA_DIR, v)) for k, v in FILES.items()}
    active_run_id = _cache.get("run_id")
    return render_template("index.html", runs=runs[:5],
                           file_status=file_status, missing=missing,
                           active_run_id=active_run_id)


@app.route("/run", methods=["POST"])
def run_reconciliation():
    data, missing = load_data()
    if missing:
        flash(f"Missing files: {', '.join(missing)}")
        return redirect(url_for("index"))

    sales  = data["sales"]
    gl     = data["gl"]
    bank   = data["bank"]
    budget = data["budget"]

    e1 = RevenueReconciler(sales, gl);    e1.reconcile()
    e2 = BankReconciler(sales, bank);     e2.reconcile()
    e3 = BudgetReconciler(sales, budget); e3.reconcile()
    e4 = CostReconciler(sales, gl);       e4.reconcile()

    summaries = {
        "revenue": e1.summary(), "bank": e2.summary(),
        "budget":  e3.summary(), "cost": e4.summary()
    }
    run_id = db.save_run(summaries)

    global _cache
    _cache = _build_cache(e1, e2, e3, e4, run_id)

    # Save full results to disk for history replay
    _save_run_to_disk(_cache, run_id)

    return redirect(url_for("dashboard"))


@app.route("/history/load/<int:run_id>")
def load_historical_run(run_id):
    """
    Load a past run's full results into _cache so all engine
    pages show that run's data. Redirects to dashboard.
    """
    global _cache
    stored = _load_run_from_disk(run_id)
    if stored is None:
        flash(f"Full data for Run #{run_id} is not available. "
              f"Only runs made after this update are stored on disk.")
        return redirect(url_for("history"))

    _cache = stored
    _cache["run_id"] = run_id          # ensure int version is set
    flash(f"Now viewing Run #{run_id} — all pages show this run's data.")
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    if not _cache:
        flash("Run a reconciliation first or Load Existing reconciliation from History.")
        return redirect(url_for("index"))
    return render_template("dashboard.html",
                           e1=_cache["e1"], e2=_cache["e2"],
                           e3=_cache["e3"], e4=_cache["e4"],
                           run_id=_cache.get("run_id"),
                           active_run_id=_cache.get("run_id"))


@app.route("/engine/<int:num>")
def engine_detail(num):
    if not _cache:
        flash("Run a reconciliation first or Load Existing reconciliation from History.")
        return redirect(url_for("index"))
    templates = {1:"engine1.html", 2:"engine2.html",
                 3:"engine3.html", 4:"engine4.html"}
    tmpl = templates.get(num)
    if not tmpl:
        return redirect(url_for("dashboard"))
    return render_template(tmpl,
                           e1=_cache.get("e1"), e2=_cache.get("e2"),
                           e3=_cache.get("e3"), e4=_cache.get("e4"),
                           active_run_id=_cache.get("run_id"))


# ── filter API ────────────────────────────────────────────────────────────────

@app.route("/api/filter/e1")
def filter_e1():
    if not _cache: return jsonify({"error": "no data"}), 400
    f = {
        "year":     request.args.get("year", ""),
        "month":    request.args.get("month", ""),
        "category": request.args.get("category", ""),
        "status":   request.args.get("status", ""),
    }
    rows = _filter_list(_cache["e1"]["results"], f)
    matched    = sum(1 for r in rows if r["status"] == "MATCHED")
    mismatches = sum(1 for r in rows if r["status"] == "MISMATCH")
    total_var  = sum(abs(r["variance_gross"]) for r in rows)
    return jsonify({
        "rows": rows[:200], "count": len(rows),
        "matched": matched, "mismatches": mismatches,
        "total_variance": round(total_var, 2),
        "match_rate": round(matched / len(rows) * 100, 2) if rows else 0,
    })


@app.route("/api/filter/e2")
def filter_e2():
    if not _cache: return jsonify({"error": "no data"}), 400
    year   = request.args.get("year", "")
    status = request.args.get("status", "")

    matched_rows = list(_cache["e2"]["matches"])
    missing_rows = list(_cache["e2"]["unmatched_sales"])

    if year:
        matched_rows = [r for r in matched_rows if r["sales_date"].startswith(year)]
        missing_rows = [r for r in missing_rows if r["sales_date"].startswith(year)]

    if status == "MATCHED":
        missing_rows = []
    elif status == "MISSING_IN_BANK":
        matched_rows = []

    total_var   = sum(abs(r["variance"]) for r in matched_rows)
    missing_usd = sum(r["expected_amount"] for r in missing_rows)
    total       = len(matched_rows) + len(missing_rows)
    return jsonify({
        "matches": matched_rows[:200], "unmatched_sales": missing_rows[:100],
        "matched_count": len(matched_rows), "missing_count": len(missing_rows),
        "total_variance": round(total_var, 2),
        "missing_usd": round(missing_usd, 2),
        "match_rate": round(len(matched_rows) / max(total, 1) * 100, 2),
    })


@app.route("/api/filter/e3")
def filter_e3():
    if not _cache: return jsonify({"error": "no data"}), 400
    f = {
        "year":        request.args.get("year", ""),
        "region":      request.args.get("region", ""),
        "performance": request.args.get("performance", ""),
    }
    rows         = _filter_list(_cache["e3"]["results"], f)
    total_budget = sum(r["budget_revenue"] for r in rows)
    total_actual = sum(r["actual_revenue"] for r in rows)
    on_target    = sum(1 for r in rows if r["status"] == "ON_TARGET")
    return jsonify({
        "rows": rows, "count": len(rows),
        "total_budget": round(total_budget, 2),
        "total_actual": round(total_actual, 2),
        "total_variance": round(total_actual - total_budget, 2),
        "on_target": on_target,
        "attainment": round(total_actual / total_budget * 100, 2) if total_budget else 0,
    })


@app.route("/api/filter/e4")
def filter_e4():
    if not _cache: return jsonify({"error": "no data"}), 400
    year      = request.args.get("year", "")
    month     = request.args.get("month", "")
    category  = request.args.get("category", "")
    flag_type = request.args.get("flag_type", "")

    rows = list(_cache["e4"]["all_results"])
    if year:      rows = [r for r in rows if str(r["year"]) == year]
    if month:     rows = [r for r in rows if str(r["month"]) == month]
    if category:  rows = [r for r in rows if r["category"] == category]
    if flag_type: rows = [r for r in rows if flag_type in r.get("flags", "")]

    flagged       = [r for r in rows if r["status"] == "FLAGGED"]
    total_cogs_v  = sum(abs(r["cogs_variance"]) for r in rows)
    margin_alerts = sum(1 for r in rows if "MARGIN_ALERT" in r.get("flags", ""))
    return jsonify({
        "rows": sorted(rows, key=lambda r: abs(r["total_cost_variance"]), reverse=True)[:200],
        "count": len(rows), "flagged": len(flagged),
        "total_cogs_variance": round(total_cogs_v, 2),
        "margin_alerts": margin_alerts,
        "match_rate": round((len(rows) - len(flagged)) / max(len(rows), 1) * 100, 2),
    })


# ── other routes ──────────────────────────────────────────────────────────────

@app.route("/history")
def history():
    runs = db.get_all_runs()
    active_run_id = _cache.get("run_id")
    # Check which runs have full data on disk
    for r in runs:
        r["has_full_data"] = os.path.exists(
            os.path.join(RUNS_DIR, f"run_{r['id']}.json"))
    return render_template("history.html", runs=runs,
                           active_run_id=active_run_id)


@app.route("/download")
def download():
    if not _cache:
        flash("Run a reconciliation first or Load Existing reconciliation from History.")
        return redirect(url_for("index"))
    out = os.path.join(DATA_DIR, "reconciliation_report.xlsx")
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        pd.DataFrame(_cache["e1"]["results"]).to_excel(writer, sheet_name="E1_Revenue_Recon",   index=False)
        pd.DataFrame(_cache["e1"]["mismatches"]).to_excel(writer, sheet_name="E1_Mismatches",   index=False)
        pd.DataFrame(_cache["e2"]["matches"]).to_excel(writer, sheet_name="E2_Bank_Matched",    index=False)
        pd.DataFrame(_cache["e2"]["unmatched_sales"]).to_excel(writer, sheet_name="E2_Missing", index=False)
        pd.DataFrame(_cache["e3"]["results"]).to_excel(writer, sheet_name="E3_Budget_Variance", index=False)
        pd.DataFrame(_cache["e4"]["all_results"]).to_excel(writer, sheet_name="E4_Cost_All",    index=False)
        pd.DataFrame(_cache["e4"]["anomalies"]).to_excel(writer, sheet_name="E4_Anomalies",     index=False)
        pd.DataFrame([_cache[k]["summary"] for k in ["e1","e2","e3","e4"]]).to_excel(
            writer, sheet_name="All_Summaries", index=False)
    run_label = f"Run_{_cache.get('run_id','latest')}"
    return send_file(out, as_attachment=True,
                     download_name=f"FMCG_Reconciliation_{run_label}.xlsx")


if __name__ == "__main__":
    app.run(debug=True, port=5000)