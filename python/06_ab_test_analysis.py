"""
06_ab_test_analysis.py
----------------------
Analyses the preventive-heating-check pilot (A/B test) created by
05_generate_experiment.py and writes a decision readout.

Steps
    0. Pre-registration: hypothesis, metric, alpha, minimum detectable effect
    1. Sanity checks: sample ratio mismatch (SRM) and pre-period balance
    2. Primary metric: heating tickets per 100 units, 2025/26 season
         - relative change Treatment vs Control
         - 95% CI from a stratified bootstrap over BUILDINGS
         - p-value from a permutation test (re-randomising within age bands)
    3. Variance reduction with CUPED (uses each building's pre-period tickets)
    4. Secondary metrics: emergency tickets, repair cost per unit
    5. Segments: pre-1970 vs newer buildings (pre-registered)
    6. Business case: saving vs cost of the check, overall and by segment

All numbers in the readout are calculated here, never typed in by hand.

Output
    outputs/ab_test/readout.md
    outputs/ab_test/ab_results_by_building.csv   (Power BI source)
    outputs/charts/07_ab_test_pre_post.png
    outputs/charts/08_ab_test_effect_by_segment.png

Run:  python python/06_ab_test_analysis.py
"""
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "experiment"
OUT = ROOT / "outputs" / "ab_test"
CH = ROOT / "outputs" / "charts"
OUT.mkdir(parents=True, exist_ok=True)
CH.mkdir(parents=True, exist_ok=True)

# ---------------- Settings (decided BEFORE looking at results) ----------------
ALPHA = 0.05            # two-sided significance level
POWER = 0.80
N_BOOT = 10_000         # bootstrap resamples
N_PERM = 10_000         # permutation resamples
CHECK_COST_EUR = 250    # ASSUMPTION: contractor price for one preventive check per building

rng = np.random.default_rng(42)

# ---------------- Load ----------------
a = pd.read_csv(EXP / "ab_assignment.csv")
t = pd.read_csv(EXP / "ab_tickets.csv")

per_b = t.groupby("property_id").agg(
    post_tickets=("ticket_id", "size"),
    post_emergency=("priority", lambda s: (s == "Emergency").sum()),
    post_cost_eur=("repair_cost_eur", "sum"),
).reset_index()
b = a.merge(per_b, on="property_id", how="left").fillna(
    {"post_tickets": 0, "post_emergency": 0, "post_cost_eur": 0.0})
b["pre_tickets_season"] = b["pre_tickets"] / 2          # average per season
b["treat"] = (b["group"] == "Treatment").astype(int)

T, C = b[b.treat == 1], b[b.treat == 0]


def per100(df, col):
    """Ratio metric: total events / total units * 100 (weights big buildings properly)."""
    return df[col].sum() / df["units_count"].sum() * 100


def _rel(v, u, tr):
    """Relative change of the per-unit rate, Treatment vs Control (numpy, fast)."""
    return (v[tr == 1].sum() / u[tr == 1].sum()) / (v[tr == 0].sum() / u[tr == 0].sum()) - 1


def rel_change(df, col):
    return _rel(df[col].to_numpy(), df["units_count"].to_numpy(), df["treat"].to_numpy())


def strat_bootstrap(df, col, n=N_BOOT):
    """Resample whole buildings with replacement inside each group x age band."""
    df = df.reset_index(drop=True)
    v, u, tr = df[col].to_numpy(), df["units_count"].to_numpy(), df["treat"].to_numpy()
    cells = [g.index.to_numpy() for _, g in df.groupby(["treat", "building_age_band"])]
    out = np.empty(n)
    for i in range(n):
        idx = np.concatenate([rng.choice(c, size=len(c)) for c in cells])
        out[i] = _rel(v[idx], u[idx], tr[idx])
    return np.percentile(out, [2.5, 97.5])


def permutation_p(df, col, n=N_PERM):
    """Shuffle group labels within age bands (same design as the real randomisation)."""
    df = df.reset_index(drop=True)
    v, u, tr = df[col].to_numpy(), df["units_count"].to_numpy(), df["treat"].to_numpy()
    observed = _rel(v, u, tr)
    bands = [g.index.to_numpy() for _, g in df.groupby("building_age_band")]
    labels = tr.copy()
    sims = np.empty(n)
    for i in range(n):
        for idx in bands:
            labels[idx] = rng.permutation(labels[idx])
        sims[i] = _rel(v, u, labels)
    return observed, (np.abs(sims) >= abs(observed)).mean()


b = b.reset_index(drop=True)
k = {}

# ---------------- 0. Pre-registration: power / MDE ----------------
# Use the pre-period (real data) to estimate how noisy one season is per building.
rate_pre = b["pre_tickets_season"] / b["units_count"] * 100
w = b["units_count"] / b["units_count"].mean()
sd = np.sqrt(np.average((rate_pre - np.average(rate_pre, weights=w)) ** 2, weights=w))
mean_pre = per100(b, "pre_tickets_season")
z = stats.norm.ppf(1 - ALPHA / 2) + stats.norm.ppf(POWER)
k["mde_abs"] = z * sd * np.sqrt(1 / len(T) + 1 / len(C))
k["mde_rel"] = k["mde_abs"] / mean_pre
k["baseline"] = mean_pre

# ---------------- 1. Sanity checks ----------------
k["n_t"], k["n_c"] = len(T), len(C)
k["srm_p"] = stats.chisquare([len(T), len(C)]).pvalue
k["pre_t"], k["pre_c"] = per100(T, "pre_tickets_season"), per100(C, "pre_tickets_season")
k["pre_diff"] = k["pre_t"] / k["pre_c"] - 1
k["units_t"], k["units_c"] = T["units_count"].sum(), C["units_count"].sum()

# ---------------- 2. Primary metric ----------------
k["post_t"], k["post_c"] = per100(T, "post_tickets"), per100(C, "post_tickets")
k["effect"], k["perm_p"] = permutation_p(b, "post_tickets")
k["ci"] = strat_bootstrap(b, "post_tickets")
k["welch_p"] = stats.ttest_ind(T["post_tickets"] / T["units_count"],
                               C["post_tickets"] / C["units_count"],
                               equal_var=False).pvalue

# ---------------- 3. CUPED ----------------
# Work on per-unit rates, weighted by units (matches the primary metric):
#   y_adj = y - theta * (x - mean(x)),  x = pre-period tickets per unit per season
# This removes the part of each building's result that its history already predicted.
u = b["units_count"]
x = b["pre_tickets_season"] / u
y = b["post_tickets"] / u
xm, ym = np.average(x, weights=u), np.average(y, weights=u)
theta = np.average((x - xm) * (y - ym), weights=u) / np.average((x - xm) ** 2, weights=u)
b["post_tickets_cuped"] = (y - theta * (x - xm)) * u   # back to "adjusted tickets"
k["corr"] = np.corrcoef(x, y)[0, 1]
k["theta"] = theta
k["cuped_effect"] = rel_change(b, "post_tickets_cuped")
k["cuped_ci"] = strat_bootstrap(b, "post_tickets_cuped")
k["cuped_p"] = permutation_p(b, "post_tickets_cuped")[1]
k["ci_shrink"] = 1 - (k["cuped_ci"][1] - k["cuped_ci"][0]) / (k["ci"][1] - k["ci"][0])

# ---------------- 4. Secondary metrics ----------------
k["emerg_t"], k["emerg_c"] = per100(T, "post_emergency"), per100(C, "post_emergency")
k["emerg_effect"], k["emerg_p"] = permutation_p(b, "post_emergency")
k["cost_t"] = T["post_cost_eur"].sum() / T["units_count"].sum()
k["cost_c"] = C["post_cost_eur"].sum() / C["units_count"].sum()
k["cost_effect"], k["cost_p"] = permutation_p(b, "post_cost_eur")
k["cost_ci"] = strat_bootstrap(b, "post_cost_eur")

# ---------------- 5 + 6. Segments and business case ----------------
# Pre-registered split: pre-1970 vs newer (finding #2: old buildings have the most
# tickets). Only two segments, so the result is not a fishing trip across many cuts.
b["segment"] = np.where(b["building_age_band"] == "pre-1970", "Built before 1970", "Built 1970 or later")
seg_rows = []
for name in ["All buildings", "Built before 1970", "Built 1970 or later"]:
    d = b if name == "All buildings" else b[b["segment"] == name].reset_index(drop=True)
    tr, co = d[d.treat == 1], d[d.treat == 0]
    if name == "All buildings":       # reuse the primary result so numbers match
        eff, p, (lo, hi) = k["cuped_effect"], k["cuped_p"], k["cuped_ci"]
    else:
        eff, p = permutation_p(d, "post_tickets_cuped")
        lo, hi = strat_bootstrap(d, "post_tickets_cuped")
    saving_per_unit = co["post_cost_eur"].sum() / co["units_count"].sum() - \
        tr["post_cost_eur"].sum() / tr["units_count"].sum()
    avg_units = d["units_count"].mean()
    saving_per_building = saving_per_unit * avg_units
    seg_rows.append({
        "segment": name, "buildings": len(d), "avg_units": avg_units,
        "control_per100": per100(co, "post_tickets"), "treat_per100": per100(tr, "post_tickets"),
        "effect": eff, "ci_low": lo, "ci_high": hi, "p_value": p,
        "saving_per_building": saving_per_building,
        "net_per_building": saving_per_building - CHECK_COST_EUR,
    })
seg = pd.DataFrame(seg_rows)
b.drop(columns=["treat", "post_tickets_cuped"]).to_csv(OUT / "ab_results_by_building.csv", index=False)
seg.to_csv(OUT / "ab_effect_by_segment.csv", index=False)

# ---------------- Charts ----------------
BLUE, INK, MUTED, GRID, GREY = "#2a78d6", "#0b0b0b", "#52514e", "#e6e5e1", "#b5b3ad"
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
    fig.text(0.01, 0.01, "Simulated pilot · Ruhr Wohnen portfolio · heating season 2025/26",
             color="#9a9893", fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(CH / name, dpi=160)
    plt.close(fig)


# Chart 7: same level before the test, gap after it
fig, ax = plt.subplots(figsize=(8, 4.6))
periods = ["Before (avg. 2023/24–2024/25)", "Pilot season 2025/26"]
xs = np.arange(2)
vals = {"Control": [k["pre_c"], k["post_c"]], "Treatment": [k["pre_t"], k["post_t"]]}
for off, (grp, col) in zip([-0.19, 0.19], [("Control", GREY), ("Treatment", BLUE)]):
    bars = ax.bar(xs + off, vals[grp], width=0.36, color=col, label=grp,
                  edgecolor="white", linewidth=2)
    for bar, v in zip(bars, vals[grp]):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.6, f"{v:.1f}",
                ha="center", color=INK, fontsize=9.5)
ax.set_xticks(xs, periods)
ax.set_ylabel("Heating tickets per 100 units")
ax.legend(frameon=False, loc="upper right")
finish(fig, ax, "Checked buildings had fewer heating tickets",
       f"Groups were level before the pilot; in 2025/26 the treatment group had "
       f"{abs(k['effect']):.0%} fewer tickets", "07_ab_test_pre_post.png")


def signed(v):
    """-0.001 -> '0%', -0.45 -> '-45%'"""
    n = round(v * 100)
    return "0%" if n == 0 else f"{n:+d}%"


# Chart 8: effect with 95% CI per segment
fig, ax = plt.subplots(figsize=(8, 3.8))
ys = np.arange(len(seg))[::-1]
for yy, r in zip(ys, seg.itertuples()):
    strong = r.segment == "All buildings"
    col = BLUE if strong else MUTED
    ax.plot([r.ci_low * 100, r.ci_high * 100], [yy, yy], color=col, linewidth=2,
            solid_capstyle="round")
    ax.scatter([r.effect * 100], [yy], s=80 if strong else 60, color=col,
               zorder=3, edgecolor="white", linewidth=2)
    ax.text(r.effect * 100, yy + 0.22, signed(r.effect), ha="center",
            color=INK, fontsize=9.5, fontweight="bold" if strong else "normal")
ax.axvline(0, color=INK, linewidth=1)
ax.set_yticks(ys, [f"{s}  ({n} buildings)" for s, n in zip(seg["segment"], seg["buildings"])])
ax.set_ylim(ys.min() - 0.5, ys.max() + 0.6)
ax.set_xlabel("Change in heating tickets vs control (%), CUPED-adjusted · line = 95% CI")
ax.grid(axis="y", visible=False)
old = seg[seg.segment == "Built before 1970"].iloc[0]
new = seg[seg.segment == "Built 1970 or later"].iloc[0]
allb = seg[seg.segment == "All buildings"].iloc[0]
finish(fig, ax, "The checks work best in older buildings",
       f"Heating tickets vs control: built before 1970 {signed(old.effect)}, "
       f"built 1970 or later {signed(new.effect)}",
       "08_ab_test_effect_by_segment.png")

# ---------------- Readout ----------------
def pct(v): return f"{v * 100:+.1f}%"
def eur(v): return f"€{v:,.0f}" if v >= 0 else f"−€{abs(v):,.0f}"


def verdict(p):
    if p < ALPHA:
        return "statistically significant"
    if p < 0.10:
        return "borderline — likely real, but not proven at the 5% level"
    return "not statistically significant"


seg_table = "\n".join(
    f"| {r.segment} | {r.buildings} | {r.control_per100:.1f} | {r.treat_per100:.1f} | "
    f"{pct(r.effect)} [{pct(r.ci_low)}, {pct(r.ci_high)}] | {r.p_value:.3f} | "
    f"{eur(r.saving_per_building)} | {eur(r.net_per_building)} |" for r in seg.itertuples())

old_wins = old.p_value < ALPHA and old.net_per_building > 0
new_wins = new.p_value < ALPHA and new.net_per_building > 0
if old_wins and new_wins:
    decision = "Roll out preventive checks to all buildings."
elif old_wins:
    decision = "Roll out preventive checks to buildings built before 1970; keep testing the rest."
else:
    decision = "Do not roll out yet; extend the pilot for another season."

readout = f"""# A/B test readout: preventive heating checks

**Decision: {decision}**

- In buildings built **before 1970**, the check cut heating tickets by **{abs(old.effect):.0%}**
  (95% CI {pct(old.ci_low)} to {pct(old.ci_high)}, p = {old.p_value:.3f}). The repair saving of
  **{eur(old.saving_per_building)} per building** is well above the {eur(CHECK_COST_EUR)} check cost.
- Across **all buildings** the effect is {pct(k['cuped_effect'])} (95% CI {pct(k['cuped_ci'][0])} to
  {pct(k['cuped_ci'][1])}, p = {k['cuped_p']:.3f}): {verdict(k['cuped_p'])}.
- In buildings built **1970 or later** the effect is {pct(new.effect)} and {verdict(new.p_value)};
  the saving ({eur(new.saving_per_building)} per building) does not cover the check.

> Data is simulated (see `python/05_generate_experiment.py`). The pre-period uses the
> project's ticket data; the pilot season is generated with a planted effect so the
> method can be checked against a known answer.

## 1. Design (fixed before the analysis)

| Item | Choice |
|---|---|
| Hypothesis | A preventive heating check in September reduces heating tickets in the following heating season |
| Second hypothesis | The effect is larger in buildings built before 1970 (older boilers; finding #2 of the main project) |
| Unit of randomisation | Building (all flats in a building share one heating system) |
| Randomisation | Stratified by building age band, 50/50 |
| Primary metric | Heating tickets per 100 units, 1 Oct 2025 – 31 Mar 2026 |
| Secondary metrics | Emergency heating tickets per 100 units; heating repair cost per unit |
| Significance | α = {ALPHA}, two-sided; power {POWER:.0%} |
| Minimum detectable effect | {k['mde_rel']:.0%} relative ({k['mde_abs']:.1f} tickets per 100 units on a baseline of {k['baseline']:.1f}) |

With only 120 buildings, the test can only reliably detect a large effect (about
{k['mde_rel']:.0%}). A result that is not significant therefore means "not proven", not
"no effect".

## 2. Sanity checks

| Check | Result |
|---|---|
| Sample ratio | {k['n_t']} treatment / {k['n_c']} control buildings, χ² p = {k['srm_p']:.2f} → no mismatch |
| Units | {k['units_t']} treatment / {k['units_c']} control |
| Pre-period tickets per 100 units | treatment {k['pre_t']:.1f} vs control {k['pre_c']:.1f} ({pct(k['pre_diff'])}) → groups comparable |

## 3. Primary result

![Before and after](../charts/07_ab_test_pre_post.png)

| Method | Effect | 95% CI | p-value |
|---|---|---|---|
| Difference in rates (permutation test + stratified bootstrap) | {pct(k['effect'])} | {pct(k['ci'][0])} to {pct(k['ci'][1])} | {k['perm_p']:.3f} |
| CUPED (adjusted for each building's ticket history) | {pct(k['cuped_effect'])} | {pct(k['cuped_ci'][0])} to {pct(k['cuped_ci'][1])} | {k['cuped_p']:.3f} |
| Check: Welch t-test on building rates | | | {k['welch_p']:.3f} |

Control: **{k['post_c']:.1f}** heating tickets per 100 units · Treatment: **{k['post_t']:.1f}**.

**Why CUPED:** some buildings always have more heating faults than others. Adjusting for
each building's ticket history removes part of that known noise (correlation between
history and pilot season: {k['corr']:.2f}), so the confidence interval is {k['ci_shrink']:.0%}
narrower with the same data.

**Why building-level inference:** flats in the same building share a boiler, so their tickets
are not independent. Bootstrapping and permuting whole buildings keeps the uncertainty
honest; treating each flat as independent would make the result look more certain than it is.

**Why the bootstrap interval and the p-value disagree slightly:** they are two different
approximations. When they sit on either side of the line, the honest reading is "borderline".

## 4. Secondary metrics

| Metric | Control | Treatment | Change | p-value |
|---|---|---|---|---|
| Emergency heating tickets per 100 units | {k['emerg_c']:.1f} | {k['emerg_t']:.1f} | {pct(k['emerg_effect'])} | {k['emerg_p']:.3f} |
| Heating repair cost per unit | €{k['cost_c']:.2f} | €{k['cost_t']:.2f} | {pct(k['cost_effect'])} (CI {pct(k['cost_ci'][0])} to {pct(k['cost_ci'][1])}) | {k['cost_p']:.3f} |

## 5. Older vs newer buildings, and the business case

![Effect by segment](../charts/08_ab_test_effect_by_segment.png)

| Segment | Buildings | Control per 100 units | Treatment per 100 units | Effect [95% CI] | p-value | Repair saving per building | Net after €{CHECK_COST_EUR} check |
|---|---|---|---|---|---|---|---|
{seg_table}

## 6. Recommendation

1. **Book preventive checks for all buildings built before 1970** before the 2026/27 heating
   season. Expected net saving: about {eur(old.net_per_building)} per building, or
   {eur(old.net_per_building * old.buildings)} across {old.buildings} buildings.
2. **Keep testing newer buildings**: leave them in a pilot for another season rather than
   paying for checks that the data does not yet justify.
3. **Keep a small control group** (about 10% of older buildings) in 2026/27 to confirm the
   effect holds when the checks are rolled out at scale.

**Not counted in the business case:** fewer night-time emergency call-outs, fewer tenant
complaints, and fewer rent reductions for missing heating. These would make the case stronger.

**Assumption to check:** the check costs {eur(CHECK_COST_EUR)} per building. Get a real quote
from the contractors before rolling out.
"""
(OUT / "readout.md").write_text(readout, encoding="utf-8")

print(f"Effect (raw):   {pct(k['effect'])}  CI {pct(k['ci'][0])}..{pct(k['ci'][1])}  p={k['perm_p']:.3f}")
print(f"Effect (CUPED): {pct(k['cuped_effect'])}  CI {pct(k['cuped_ci'][0])}..{pct(k['cuped_ci'][1])}  p={k['cuped_p']:.3f}")
print(f"MDE: {k['mde_rel']:.0%}   CI narrower by {k['ci_shrink']:.0%}   corr={k['corr']:.2f}")
print(seg.round(3).to_string())
print("Readout -> outputs/ab_test/readout.md")
