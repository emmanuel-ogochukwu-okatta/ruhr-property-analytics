"""
02_clean_and_validate.py
------------------------
Reads the messy exports in data/raw/, fixes the data-quality problems,
builds a star schema ready for Power BI, and writes a data-quality report.

Output (data/clean/):
  dim_property.csv, dim_unit.csv, dim_contractor.csv, dim_date.csv
  fact_tenancy.csv, fact_rent_payment.csv, fact_ticket.csv, fact_unit_month.csv
Report:
  outputs/data_quality_report.md

Run:  python python/02_clean_and_validate.py
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, CLEAN, OUT = ROOT / "data" / "raw", ROOT / "data" / "clean", ROOT / "outputs"
CLEAN.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

START, END = pd.Timestamp("2023-01-01"), pd.Timestamp("2025-12-31")
log = []  # (check, rows affected, action)

def note(check, n, action):
    log.append((check, int(n), action))
    print(f"[{n:>5}] {check} -> {action}")

# --------------------------------------------------------------------------
# Properties: standardise city names, fill missing energy class
# --------------------------------------------------------------------------
prop = pd.read_csv(RAW / "properties.csv")
CITY_MAP = {"essen": "Essen", "bochum": "Bochum", "dortmund": "Dortmund",
            "duisburg": "Duisburg", "gelsenkirchen": "Gelsenkirchen", "ge": "Gelsenkirchen",
            "mülheim": "Mülheim", "muelheim": "Mülheim", "mülheim an der ruhr": "Mülheim"}
before = prop["city"].copy()
prop["city"] = prop["city"].str.strip().str.lower().map(CITY_MAP)
note("Inconsistent city spellings (case, spaces, 'GE', 'Muelheim')",
     (before != prop["city"]).sum(), "mapped to 6 standard city names")
assert prop["city"].notna().all(), "unmapped city found"

n = prop["energy_class"].isna().sum()
prop["energy_class"] = prop["energy_class"].fillna("Unknown")
note("Missing energy class", n, "labelled 'Unknown' (not guessed)")

# --------------------------------------------------------------------------
# Units / contractors (clean already, but validate keys)
# --------------------------------------------------------------------------
unit = pd.read_csv(RAW / "units.csv")
con = pd.read_csv(RAW / "contractors.csv")
assert unit["unit_id"].is_unique and set(unit["property_id"]) <= set(prop["property_id"])
note("Units with unknown property_id", 0, "none found (key check passed)")

# --------------------------------------------------------------------------
# Tenancies
# --------------------------------------------------------------------------
ten = pd.read_csv(RAW / "tenancies.csv", parse_dates=["start_date", "end_date"])
assert set(ten["unit_id"]) <= set(unit["unit_id"])
overlap = (ten.sort_values(["unit_id", "start_date"])
              .assign(prev_end=lambda d: d.groupby("unit_id")["end_date"].shift())
              .query("prev_end.notna() and start_date <= prev_end"))
note("Overlapping tenancies on the same unit", len(overlap), "none expected; checked")
ten["is_active_end_2025"] = ten["end_date"].isna()

# --------------------------------------------------------------------------
# Maintenance tickets
# --------------------------------------------------------------------------
tk = pd.read_csv(RAW / "maintenance_tickets.csv")
n0 = len(tk)
tk = tk.drop_duplicates(subset="ticket_id", keep="first")
note("Duplicate ticket_id rows (system re-export)", n0 - len(tk), "removed, first occurrence kept")

# Mixed ISO and German (dd.mm.yyyy) date formats
german = tk["created_at"].str.match(r"^\d{2}\.\d{2}\.\d{4}")
iso_parsed = pd.to_datetime(tk["created_at"], format="%Y-%m-%d %H:%M", errors="coerce")
ger_parsed = pd.to_datetime(tk["created_at"], format="%d.%m.%Y %H:%M", errors="coerce")
tk["created_at"] = iso_parsed.fillna(ger_parsed)
assert tk["created_at"].notna().all(), "unparsed created_at values remain"
tk["closed_at"] = pd.to_datetime(tk["closed_at"], format="%Y-%m-%d %H:%M")
note("German-format dates (dd.mm.yyyy) mixed with ISO dates", german.sum(), "parsed to one datetime format")

before = tk["category"].copy()
tk["category"] = tk["category"].replace({"heating": "Heating", "Mould/Damp": "Damp & Mould"})
note("Inconsistent ticket category labels", (before != tk["category"]).sum(), "mapped to standard categories")

bad_dates = tk["closed_at"] < tk["created_at"]
note("Closed date before created date", bad_dates.sum(),
     "closed_at set to blank, flagged; excluded from resolution-time KPIs")
tk.loc[bad_dates, "closed_at"] = pd.NaT
tk["dq_flag"] = np.where(bad_dates, "closed_before_created", "")

neg = tk["repair_cost_eur"] < 0
note("Negative repair costs (credit notes keyed wrongly)", neg.sum(), "converted to positive value, flagged")
tk.loc[neg, "repair_cost_eur"] = tk.loc[neg, "repair_cost_eur"].abs()
tk.loc[neg, "dq_flag"] = "negative_cost_fixed"

miss = (tk["status"] == "Closed") & tk["repair_cost_eur"].isna()
note("Closed tickets with missing cost", miss.sum(),
     "left blank (not imputed) so cost totals are not invented; flagged")
tk.loc[miss, "dq_flag"] = tk.loc[miss, "dq_flag"].where(tk.loc[miss, "dq_flag"] != "", "missing_cost")

assert tk["ticket_id"].is_unique, "ticket_id still duplicated after cleaning"

SLA_H = {"Emergency": 24, "High": 72, "Normal": 240, "Low": 480}
tk["sla_hours"] = tk["priority"].map(SLA_H)
tk["resolution_hours"] = ((tk["closed_at"] - tk["created_at"]).dt.total_seconds() / 3600).round(1)
tk["sla_met"] = np.where(tk["resolution_hours"].notna(),
                         (tk["resolution_hours"] <= tk["sla_hours"]).map({True: "Yes", False: "No"}), "")
tk["created_date"] = tk["created_at"].dt.date
tk["closed_date"] = tk["closed_at"].dt.date

# --------------------------------------------------------------------------
# Rent payments
# --------------------------------------------------------------------------
pay = pd.read_csv(RAW / "rent_payments.csv", parse_dates=["month", "paid_date"])
assert set(pay["tenancy_id"]) <= set(ten["tenancy_id"])
pay["days_late"] = (pay["paid_date"] - (pay["month"] + pd.Timedelta(days=3))).dt.days.clip(lower=0)
pay["arrears_eur"] = (pay["amount_due_eur"] - pay["amount_paid_eur"]).round(2)
pay["payment_status"] = np.select(
    [pay["amount_paid_eur"] == 0, pay["arrears_eur"] > 0, pay["days_late"] > 0],
    ["Missed", "Partial", "Late"], "On time")
pay = pay.merge(ten[["tenancy_id", "unit_id"]], on="tenancy_id", how="left")
note("Rent payments missing or partial", (pay["arrears_eur"] > 0).sum(), "kept; arrears_eur column added")

# --------------------------------------------------------------------------
# Unit x month occupancy (vacancy days and lost rent) — makes vacancy KPIs
# simple in Power BI without complex DAX
# --------------------------------------------------------------------------
days = pd.date_range(START, END, freq="D")
rows = []
for uid, g in ten.sort_values("start_date").groupby("unit_id"):
    occ = np.zeros(len(days), dtype=bool)
    ref_rent = np.full(len(days), np.nan)
    for t in g.itertuples():
        s = max(t.start_date, START)
        e = min(t.end_date, END) if pd.notna(t.end_date) else END
        if e < START or s > END:
            continue
        i0, i1 = (s - START).days, (e - START).days
        occ[i0:i1 + 1] = True
        ref_rent[i0:i1 + 1] = t.monthly_rent_eur
    # reference rent on vacant days: last known rent, else next known rent
    rr = pd.Series(ref_rent).ffill().bfill().values
    df = pd.DataFrame({"day": days, "occ": occ, "rent": rr})
    df["month"] = df["day"].dt.to_period("M").dt.to_timestamp()
    df["dim"] = df["day"].dt.days_in_month
    df["lost"] = np.where(~df["occ"], df["rent"] / df["dim"], 0.0)
    agg = df.groupby("month").agg(days_in_month=("dim", "first"),
                                  occupied_days=("occ", "sum"),
                                  lost_rent_eur=("lost", "sum")).reset_index()
    agg["unit_id"] = uid
    rows.append(agg)
um = pd.concat(rows, ignore_index=True)
um["vacant_days"] = um["days_in_month"] - um["occupied_days"]
um["lost_rent_eur"] = um["lost_rent_eur"].round(2)
um = um[["unit_id", "month", "days_in_month", "occupied_days", "vacant_days", "lost_rent_eur"]]

# --------------------------------------------------------------------------
# Date dimension (Power BI best practice: one shared calendar)
# --------------------------------------------------------------------------
cal = pd.DataFrame({"date": pd.date_range("2010-01-01", "2026-12-31", freq="D")})
cal["year"] = cal["date"].dt.year
cal["quarter"] = "Q" + cal["date"].dt.quarter.astype(str)
cal["month_num"] = cal["date"].dt.month
cal["month_name"] = cal["date"].dt.strftime("%b")
cal["year_month"] = cal["date"].dt.strftime("%Y-%m")
cal["is_heating_season"] = cal["month_num"].isin([10, 11, 12, 1, 2, 3])

# --------------------------------------------------------------------------
# Save star schema
# --------------------------------------------------------------------------
prop.to_csv(CLEAN / "dim_property.csv", index=False)
unit.to_csv(CLEAN / "dim_unit.csv", index=False)
con.to_csv(CLEAN / "dim_contractor.csv", index=False)
cal.to_csv(CLEAN / "dim_date.csv", index=False, date_format="%Y-%m-%d")
ten.to_csv(CLEAN / "fact_tenancy.csv", index=False, date_format="%Y-%m-%d")
pay.to_csv(CLEAN / "fact_rent_payment.csv", index=False, date_format="%Y-%m-%d")
tk.to_csv(CLEAN / "fact_ticket.csv", index=False, date_format="%Y-%m-%d %H:%M")
um.to_csv(CLEAN / "fact_unit_month.csv", index=False, date_format="%Y-%m-%d")

# --------------------------------------------------------------------------
# Data quality report
# --------------------------------------------------------------------------
lines = ["# Data Quality Report", "",
         "Generated by `python/02_clean_and_validate.py`.", "",
         "| Check | Rows affected | Action taken |", "|---|---:|---|"]
lines += [f"| {c} | {n:,} | {a} |" for c, n, a in log]
lines += ["", "## Clean tables", "", "| Table | Rows |", "|---|---:|"]
for f in sorted(CLEAN.glob("*.csv")):
    lines.append(f"| {f.stem} | {sum(1 for _ in open(f, encoding='utf-8')) - 1:,} |")
(OUT / "data_quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\nClean tables written to data/clean/ and report to outputs/data_quality_report.md")
