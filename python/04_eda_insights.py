"""
04_eda_insights.py
------------------
Exploratory analysis in pandas: computes the headline KPIs, saves six charts
to outputs/charts/ and writes outputs/insights.md with the findings and
recommendations (numbers are calculated, never typed in by hand).

Run:  python python/04_eda_insights.py
"""
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean"
OUT = ROOT / "outputs"
CH = OUT / "charts"
CH.mkdir(parents=True, exist_ok=True)

# Palette: one main colour, one highlight colour, recessive greys
BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e6e5e1"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
    "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "figure.facecolor": "white", "axes.facecolor": "white",
})

def finish(fig, ax, title, subtitle, name):
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color=INK, pad=24)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, color=MUTED, fontsize=9.5)
    fig.text(0.01, 0.01, "Synthetic data · Ruhr Wohnen portfolio 2023–2025",
             color="#9a9893", fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(CH / name, dpi=160)
    plt.close(fig)

prop = pd.read_csv(CLEAN / "dim_property.csv")
unit = pd.read_csv(CLEAN / "dim_unit.csv").merge(prop, on="property_id")
con = pd.read_csv(CLEAN / "dim_contractor.csv")
tk = pd.read_csv(CLEAN / "fact_ticket.csv", parse_dates=["created_at", "closed_at"])
pay = pd.read_csv(CLEAN / "fact_rent_payment.csv", parse_dates=["month"])
um = pd.read_csv(CLEAN / "fact_unit_month.csv", parse_dates=["month"])
ten = pd.read_csv(CLEAN / "fact_tenancy.csv", parse_dates=["start_date", "end_date"])

N_UNITS, YEARS = len(unit), 3
k = {}  # headline numbers used in insights.md

# ---------------- Portfolio KPIs ----------------
k["units"] = N_UNITS
k["properties"] = len(prop)
k["occupancy"] = um["occupied_days"].sum() / um["days_in_month"].sum() * 100
k["lost_rent"] = um["lost_rent_eur"].sum()
k["collection"] = pay["amount_paid_eur"].sum() / pay["amount_due_eur"].sum() * 100
k["arrears"] = pay["arrears_eur"].sum()
k["tickets"] = len(tk)
k["repair_cost"] = tk["repair_cost_eur"].sum()
valid = tk[tk["resolution_hours"].notna()]
k["sla"] = (valid["sla_met"] == "Yes").mean() * 100
active = ten[ten["end_date"].isna()].merge(unit[["unit_id", "size_sqm"]], on="unit_id")
k["rent_sqm"] = active["monthly_rent_eur"].sum() / active["size_sqm"].sum()

# ---------------- Chart 1: occupancy trend ----------------
occ_m = um.groupby("month").apply(lambda d: d["occupied_days"].sum() / d["days_in_month"].sum() * 100,
                                  include_groups=False)
fig, ax = plt.subplots(figsize=(9, 4))
ax.plot(occ_m.index, occ_m.values, color=BLUE, lw=2)
ax.set_ylim(95, 100)
ax.set_ylabel("Occupancy %")
last = occ_m.index[-1]
ax.annotate(f"{occ_m.iloc[-1]:.1f}%", (last, occ_m.iloc[-1]), xytext=(6, 0),
            textcoords="offset points", va="center", color=INK, fontsize=9)
finish(fig, ax, "Portfolio occupancy stays around 98%",
       "Share of unit-days let, by month", "01_occupancy_trend.png")

# ---------------- Chart 2: heating seasonality ----------------
heat = tk[tk["category"] == "Heating"].groupby(tk["created_at"].dt.month).size() / YEARS
heat = heat.reindex(range(1, 13), fill_value=0)
season = [m in (10, 11, 12, 1, 2, 3) for m in heat.index]
k["heat_season_share"] = heat[season].sum() / heat.sum() * 100
fig, ax = plt.subplots(figsize=(9, 4))
ax.bar(range(12), heat.values, color=[BLUE if s else "#a9c7ef" for s in season], width=0.7)
ax.set_xticks(range(12), ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
ax.set_ylabel("Heating tickets per year")
ax.grid(axis="x", visible=False)
finish(fig, ax, f"{k['heat_season_share']:.0f}% of heating tickets arrive Oct–Mar",
       "Average heating tickets per calendar month (dark = heating season)", "02_heating_seasonality.png")

# ---------------- Chart 3: tickets by building age ----------------
order = ["pre-1970", "1970-1989", "1990-2004", "2005+"]
t_band = tk.merge(prop[["property_id", "building_age_band"]], on="property_id") \
           .groupby("building_age_band").size()
u_band = unit.groupby("building_age_band").size()
rate = (t_band / u_band / YEARS * 100).reindex(order)
k["rate_old"], k["rate_new"] = rate["pre-1970"], rate["2005+"]
fig, ax = plt.subplots(figsize=(9, 4))
bars = ax.bar(order, rate.values, color=BLUE, width=0.6)
ax.bar_label(bars, fmt="%.0f", padding=3, color=INK, fontsize=9)
ax.set_ylabel("Tickets per 100 units / year")
ax.grid(axis="x", visible=False)
finish(fig, ax, f"Pre-1970 buildings need {k['rate_old']/k['rate_new']:.1f}× more repairs than new ones",
       "Repair tickets per 100 units per year, by year built", "03_tickets_by_building_age.png")

# ---------------- Chart 4: contractor SLA ----------------
perf = valid.merge(con, on="contractor_id").groupby(["contractor_name", "trade"]).agg(
    tickets=("ticket_id", "count"),
    sla=("sla_met", lambda s: (s == "Yes").mean() * 100),
    hours=("resolution_hours", "mean")).reset_index().sort_values("sla")
worst = perf.iloc[0]
k["worst_con"], k["worst_sla"], k["worst_trade"] = worst["contractor_name"], worst["sla"], worst["trade"]
peer = perf[(perf["trade"] == worst["trade"]) & (perf["contractor_name"] != worst["contractor_name"])].iloc[0]
k["peer_con"], k["peer_sla"] = peer["contractor_name"], peer["sla"]
k["worst_hours"], k["peer_hours"] = worst["hours"], peer["hours"]
fig, ax = plt.subplots(figsize=(9, 4.4))
labels = perf["contractor_name"] + "  (" + perf["trade"] + ")"
cols = [ORANGE if n == worst["contractor_name"] else BLUE for n in perf["contractor_name"]]
bars = ax.barh(labels, perf["sla"], color=cols, height=0.6)
ax.bar_label(bars, fmt="%.0f%%", padding=3, color=INK, fontsize=9)
ax.set_xlim(0, 100)
ax.set_xlabel("Tickets closed within SLA %")
ax.grid(axis="y", visible=False)
finish(fig, ax, f"{worst['contractor_name']} misses SLA on most heating & plumbing jobs",
       "Share of closed tickets resolved within the priority SLA", "04_contractor_sla.png")

# ---------------- Chart 5: payment problems by city ----------------
pc = pay.merge(unit[["unit_id", "city"]], on="unit_id").groupby("city").agg(
    due=("amount_due_eur", "sum"), paid=("amount_paid_eur", "sum"),
    late=("payment_status", lambda s: (s != "On time").mean() * 100)).reset_index()
pc["collection"] = pc["paid"] / pc["due"] * 100
pc = pc.sort_values("late")
k["worst_city"], k["worst_city_late"] = pc.iloc[-1]["city"], pc.iloc[-1]["late"]
k["best_city"], k["best_city_late"] = pc.iloc[0]["city"], pc.iloc[0]["late"]
k["worst_city_coll"] = pc.iloc[-1]["collection"]
arr_by_ten = pay.groupby("tenancy_id")["arrears_eur"].sum().sort_values(ascending=False)
k["top10_arrears_share"] = arr_by_ten.head(int(len(arr_by_ten) * 0.10)).sum() / arr_by_ten.sum() * 100
fig, ax = plt.subplots(figsize=(9, 4))
cols = [ORANGE if c == k["worst_city"] else BLUE for c in pc["city"]]
bars = ax.barh(pc["city"], pc["late"], color=cols, height=0.6)
ax.bar_label(bars, fmt="%.1f%%", padding=3, color=INK, fontsize=9)
ax.set_xlabel("Rent payments late, partial or missed %")
ax.grid(axis="y", visible=False)
finish(fig, ax, f"{k['worst_city']} has the most rent payment problems",
       "Share of monthly rent payments not received on time, 2023–2025", "05_payment_problems_by_city.png")

# ---------------- Chart 6: lost rent by energy class ----------------
ue = um.merge(unit[["unit_id", "energy_class"]], on="unit_id").groupby("energy_class").agg(
    lost=("lost_rent_eur", "sum"), units=("unit_id", "nunique")).reset_index()
ue["per_unit"] = ue["lost"] / ue["units"]
ue = ue[ue["energy_class"] != "Unknown"]
k["lost_A"] = ue.loc[ue.energy_class == "A", "per_unit"].iloc[0]
k["lost_FG"] = (ue[ue.energy_class.isin(["F", "G"])]["lost"].sum()
                / ue[ue.energy_class.isin(["F", "G"])]["units"].sum())
k["lost_FG_total"] = ue[ue.energy_class.isin(["F", "G"])]["lost"].sum()
fig, ax = plt.subplots(figsize=(9, 4))
bars = ax.bar(ue["energy_class"], ue["per_unit"], color=BLUE, width=0.6)
ax.bar_label(bars, fmt="€%.0f", padding=3, color=INK, fontsize=9)
ax.set_ylabel("Lost rent per unit (EUR, 3 yrs)")
ax.set_xlabel("Energy class")
ax.grid(axis="x", visible=False)
finish(fig, ax, "Poor energy classes lose more rent to vacancy",
       "Rent lost while units stood empty, per unit, 2023–2025", "06_lost_rent_by_energy_class.png")

# ---------------- insights.md ----------------
eur = lambda x: f"€{x:,.0f}"
md = f"""# Key Findings — Ruhr Wohnen Portfolio (2023–2025)

*All figures are calculated by `python/04_eda_insights.py` from the cleaned data. The dataset is synthetic.*

## Headline KPIs

| KPI | Value |
|---|---:|
| Properties / units | {k['properties']} / {k['units']:,} |
| Average occupancy | {k['occupancy']:.1f}% |
| Rent lost to vacancy | {eur(k['lost_rent'])} |
| Rent collection rate | {k['collection']:.2f}% |
| Unpaid rent (arrears) | {eur(k['arrears'])} |
| Repair tickets | {k['tickets']:,} |
| Repair spend (recorded) | {eur(k['repair_cost'])} |
| Tickets closed within SLA | {k['sla']:.1f}% |
| Average rent, current tenants | €{k['rent_sqm']:.2f} per m² |

## Findings and recommendations

1. **Heating demand is seasonal and predictable.** {k['heat_season_share']:.0f}% of heating tickets arrive between October and March.
   → *Book contractor capacity and boiler servicing in September, before the peak.*

2. **Old buildings drive the repair workload.** Pre-1970 buildings generate {k['rate_old']:.0f} tickets per 100 units a year, versus {k['rate_new']:.0f} in buildings from 2005 onwards.
   → *Prioritise the highest cost-per-unit properties (SQL query Q8) for planned modernisation instead of repeated reactive repairs.*

3. **One contractor is a clear bottleneck.** {k['worst_con']} ({k['worst_trade']}) closes only {k['worst_sla']:.0f}% of tickets within SLA, against {k['peer_sla']:.0f}% for {k['peer_con']} in the same trade (average {k['worst_hours']:.0f} vs {k['peer_hours']:.0f} hours).
   → *Review the service agreement and shift urgent heating work to the faster contractor.*

4. **Payment problems concentrate in one city.** In {k['worst_city']}, {k['worst_city_late']:.1f}% of monthly payments are late, partial or missed (collection rate {k['worst_city_coll']:.2f}%), against {k['best_city_late']:.1f}% in {k['best_city']}. Across the portfolio, 10% of tenancies account for {k['top10_arrears_share']:.0f}% of all unpaid rent (see SQL query Q9).
   → *Start early-contact reminders after the first missed payment and offer instalment plans.*

5. **Energy efficiency affects income, not just costs.** Units in energy classes F–G lost {eur(k['lost_FG'])} each to vacancy over three years, versus {eur(k['lost_A'])} for class A — {eur(k['lost_FG_total'])} in total.
   → *Include vacancy loss in the business case for energy upgrades.*

## Charts

![Occupancy](charts/01_occupancy_trend.png)
![Heating seasonality](charts/02_heating_seasonality.png)
![Tickets by building age](charts/03_tickets_by_building_age.png)
![Contractor SLA](charts/04_contractor_sla.png)
![Payment problems by city](charts/05_payment_problems_by_city.png)
![Lost rent by energy class](charts/06_lost_rent_by_energy_class.png)
"""
(OUT / "insights.md").write_text(md, encoding="utf-8")
for key, val in k.items():
    print(f"{key:20s} {val}")
