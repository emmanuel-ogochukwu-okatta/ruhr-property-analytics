"""
05_generate_experiment.py
-------------------------
Creates the data for an A/B test (randomised pilot) on preventive heating checks.

Business question
    Most heating faults arrive between October and March (finding #1). If a
    contractor services the heating system of a building in September, do we
    get fewer heating tickets in the following heating season, and does the
    saving cover the cost of the check?

Design
    * Unit of randomisation: the BUILDING (one heating system per building).
      Flats in the same building share a boiler, so randomising flats would
      mix treated and untreated tenants on one system.
    * 120 buildings, stratified by building age band, then split 50/50 at
      random into Treatment (preventive check in Sept 2025) and Control.
    * Pre-period: real heating tickets per building from the 2023/24 and
      2024/25 heating seasons (taken from data/clean/fact_ticket.csv).
    * Experiment period: heating season 2025/26 (1 Oct 2025 - 31 Mar 2026).

The experiment outcomes are SIMULATED. A known "true" effect is planted
(stronger in older buildings) so we can check that the analysis in
06_ab_test_analysis.py recovers it. The analysis script never reads the
planted values.

Output
    data/experiment/ab_assignment.csv   one row per building (group, pre-period)
    data/experiment/ab_tickets.csv      one row per heating ticket in 2025/26

Run:  python python/05_generate_experiment.py
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean"
OUT = ROOT / "data" / "experiment"
OUT.mkdir(parents=True, exist_ok=True)

rng = np.random.default_rng(2025)

# Planted true effect = relative reduction in heating tickets (hidden from the analysis)
TRUE_EFFECT = {"pre-1970": 0.40, "1970-1989": 0.30, "1990-2004": 0.15, "2005+": 0.10}

prop = pd.read_csv(CLEAN / "dim_property.csv")
tk = pd.read_csv(CLEAN / "fact_ticket.csv", parse_dates=["created_at"])

# ---------------- Pre-period: real heating tickets, two full seasons ----------------
heat = tk[tk["category"] == "Heating"].copy()
in_pre = heat["created_at"].between("2023-10-01", "2025-03-31 23:59")
pre = (heat[in_pre].groupby("property_id").size()
       .rename("pre_tickets").reset_index())

b = prop[["property_id", "city", "building_age_band", "year_built", "units_count"]].merge(
    pre, on="property_id", how="left").fillna({"pre_tickets": 0})
b["pre_tickets"] = b["pre_tickets"].astype(int)
b["pre_rate_per_unit"] = b["pre_tickets"] / (2 * b["units_count"])  # per unit per season

# ---------------- Stratified randomisation ----------------
groups = []
for band, g in b.groupby("building_age_band"):
    ids = g["property_id"].sample(frac=1, random_state=int(rng.integers(1e9))).tolist()
    # alternate after shuffling -> equal split per stratum (odd stratum: random extra)
    start = rng.integers(2)
    for i, pid in enumerate(ids):
        groups.append((pid, "Treatment" if (i + start) % 2 == 0 else "Control"))
b = b.merge(pd.DataFrame(groups, columns=["property_id", "group"]), on="property_id")
b["check_date"] = np.where(b["group"] == "Treatment", "2025-09-15", "")

# ---------------- Simulate 2025/26 heating season ----------------
# Expected tickets = mostly the building's own history (a weak boiler stays weak),
# slightly shrunk towards its age band, with season-to-season noise (negative binomial).
band_rate = b.groupby("building_age_band")["pre_rate_per_unit"].transform("mean")
expected_rate = 0.8 * b["pre_rate_per_unit"] + 0.2 * band_rate
effect = b["building_age_band"].map(TRUE_EFFECT)
lam = expected_rate * b["units_count"] * np.where(b["group"] == "Treatment", 1 - effect, 1.0)
lam = lam * rng.gamma(shape=12, scale=1 / 12, size=len(b))  # extra building-level noise
b["post_tickets"] = rng.poisson(lam)

# Ticket-level rows: date, priority and repair cost drawn from real heating tickets
real_costs = heat["repair_cost_eur"].dropna().to_numpy()
season_days = pd.date_range("2025-10-01", "2026-03-31", freq="D")
day_weight = np.where(season_days.month.isin([12, 1, 2]), 1.6, 1.0)  # colder months busier
day_weight = day_weight / day_weight.sum()

rows = []
for r in b.itertuples():
    for _ in range(r.post_tickets):
        # treated buildings: fewer emergencies (serviced boilers break less badly)
        p_emerg = 0.15 if r.group == "Treatment" else 0.22
        priority = rng.choice(["Emergency", "High", "Normal", "Low"],
                              p=[p_emerg, 0.40, 0.32, 0.28 - p_emerg])
        cost = float(rng.choice(real_costs)) * (1.6 if priority == "Emergency" else 1.0)
        rows.append({
            "property_id": r.property_id,
            "created_date": season_days[rng.choice(len(season_days), p=day_weight)].strftime("%Y-%m-%d"),
            "priority": priority,
            "repair_cost_eur": round(cost, 2),
        })
tickets = pd.DataFrame(rows).sort_values(["created_date", "property_id"]).reset_index(drop=True)
tickets.insert(0, "ticket_id", [f"X{i:05d}" for i in range(1, len(tickets) + 1)])
tickets = tickets.merge(b[["property_id", "group"]], on="property_id")

assignment = b[["property_id", "city", "building_age_band", "year_built", "units_count",
                "group", "check_date", "pre_tickets", "pre_rate_per_unit"]]
assignment.to_csv(OUT / "ab_assignment.csv", index=False)
tickets.to_csv(OUT / "ab_tickets.csv", index=False)

print(f"Buildings: {len(b)}  ->  {b['group'].value_counts().to_dict()}")
print(f"Heating tickets 2025/26: {len(tickets)}")
print(f"Saved to {OUT.relative_to(ROOT)}/")
