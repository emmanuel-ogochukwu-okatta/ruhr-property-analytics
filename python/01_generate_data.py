"""
01_generate_data.py
-------------------
Generates a SYNTHETIC dataset for a fictional residential housing company
("Ruhr Wohnen GmbH") managing ~1,200 flats across six Ruhr-area cities.

The data is invented, but modelled on how a German residential property
manager actually works: properties, units, tenancies, monthly rent
(Nettokaltmiete), repair tickets and contractors.

Realistic messiness is injected on purpose (duplicates, inconsistent city
names, German date formats, missing / invalid values) so the cleaning step
in 02_clean_and_validate.py has real work to do.

Run:  python python/01_generate_data.py
"""
from pathlib import Path
import numpy as np
import pandas as pd

SEED = 42
rng = np.random.default_rng(SEED)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

START = pd.Timestamp("2023-01-01")
END = pd.Timestamp("2025-12-31")

# --------------------------------------------------------------------------
# City assumptions (typical Ruhr ranges for older housing stock, rounded)
# rent_sqm      = average Nettokaltmiete EUR per m2 for re-lets
# moveout_p     = yearly probability a tenant moves out
# late_p        = monthly probability a payment is late
# miss_p        = monthly probability a payment is missed / partial
# --------------------------------------------------------------------------
CITIES = {
    "Essen":         dict(rent_sqm=7.40, moveout_p=0.085, late_p=0.06, miss_p=0.020, w=0.24),
    "Bochum":        dict(rent_sqm=7.00, moveout_p=0.090, late_p=0.06, miss_p=0.022, w=0.18),
    "Dortmund":      dict(rent_sqm=7.60, moveout_p=0.080, late_p=0.05, miss_p=0.018, w=0.20),
    "Duisburg":      dict(rent_sqm=6.60, moveout_p=0.100, late_p=0.08, miss_p=0.032, w=0.14),
    "Gelsenkirchen": dict(rent_sqm=6.10, moveout_p=0.115, late_p=0.10, miss_p=0.045, w=0.14),
    "Mülheim":       dict(rent_sqm=7.30, moveout_p=0.075, late_p=0.05, miss_p=0.015, w=0.10),
}
DISTRICTS = {
    "Essen": ["Rüttenscheid", "Altenessen", "Steele", "Frohnhausen", "Borbeck"],
    "Bochum": ["Wattenscheid", "Langendreer", "Ehrenfeld", "Hamme"],
    "Dortmund": ["Nordstadt", "Hörde", "Eving", "Huckarde", "Scharnhorst"],
    "Duisburg": ["Marxloh", "Hochfeld", "Rheinhausen", "Meiderich"],
    "Gelsenkirchen": ["Buer", "Ückendorf", "Horst", "Bismarck"],
    "Mülheim": ["Styrum", "Dümpten", "Heißen"],
}
STREETS = ["Lindenstraße", "Bergstraße", "Schulstraße", "Gartenstraße", "Ringstraße",
           "Kirchstraße", "Am Bahnhof", "Hauptstraße", "Wiesenweg", "Zechenstraße",
           "Kokereistraße", "Ahornweg", "Birkenallee", "Hüttenstraße", "Talstraße"]

# --------------------------------------------------------------------------
# 1. Properties
# --------------------------------------------------------------------------
N_PROPS = 120
city_names = list(CITIES)
city_w = np.array([CITIES[c]["w"] for c in city_names])
prop_city = rng.choice(city_names, N_PROPS, p=city_w / city_w.sum())

# Ruhr stock is dominated by post-war buildings
year_built = np.concatenate([
    rng.integers(1950, 1975, int(N_PROPS * 0.55)),
    rng.integers(1975, 1995, int(N_PROPS * 0.30)),
    rng.integers(1995, 2018, N_PROPS - int(N_PROPS * 0.55) - int(N_PROPS * 0.30)),
])
rng.shuffle(year_built)

def energy_class(y):
    if y < 1970:  return rng.choice(["E", "F", "G"], p=[0.35, 0.40, 0.25])
    if y < 1990:  return rng.choice(["C", "D", "E", "F"], p=[0.15, 0.40, 0.35, 0.10])
    if y < 2005:  return rng.choice(["B", "C", "D"], p=[0.25, 0.50, 0.25])
    return rng.choice(["A", "B", "C"], p=[0.40, 0.45, 0.15])

properties = pd.DataFrame({
    "property_id": [f"P{i:03d}" for i in range(1, N_PROPS + 1)],
    "city": prop_city,
    "district": [rng.choice(DISTRICTS[c]) for c in prop_city],
    "address": [f"{rng.choice(STREETS)} {rng.integers(1, 120)}" for _ in range(N_PROPS)],
    "year_built": year_built,
    "energy_class": [energy_class(y) for y in year_built],
    "has_elevator": [bool(rng.random() < (0.15 if y < 1975 else 0.55)) for y in year_built],
    "units_count": rng.integers(4, 19, N_PROPS),
})
properties["building_age_band"] = pd.cut(
    properties["year_built"], [0, 1969, 1989, 2004, 2100],
    labels=["pre-1970", "1970-1989", "1990-2004", "2005+"]).astype(str)

# --------------------------------------------------------------------------
# 2. Units
# --------------------------------------------------------------------------
unit_rows = []
for p in properties.itertuples():
    for u in range(1, p.units_count + 1):
        rooms = int(rng.choice([1, 2, 3, 4], p=[0.12, 0.38, 0.38, 0.12]))
        size = round(float(rng.normal(28 + rooms * 18, 6)), 1)
        size = max(size, 25.0)
        unit_rows.append(dict(
            unit_id=f"{p.property_id}-U{u:02d}",
            property_id=p.property_id,
            floor=int(min((u - 1) // 2, 6)),
            rooms=rooms,
            size_sqm=size,
        ))
units = pd.DataFrame(unit_rows)

# --------------------------------------------------------------------------
# 3. Tenancies (each unit: a sequence of tenancies with vacancy gaps)
# --------------------------------------------------------------------------
prop_lookup = properties.set_index("property_id")
ten_rows = []
tid = 1
for u in units.itertuples():
    p = prop_lookup.loc[u.property_id]
    c = CITIES[p.city]
    # Market rent per m2 adjusted by energy class (worse class = lower rent)
    ec_adj = {"A": 1.18, "B": 1.12, "C": 1.05, "D": 1.0, "E": 0.95, "F": 0.90, "G": 0.86}[p.energy_class]
    market_sqm = c["rent_sqm"] * ec_adj

    # Existing tenant at 1 Jan 2023 (sitting tenants pay below market)
    start = START - pd.Timedelta(days=int(rng.integers(60, 365 * 12)))
    rent_sqm = market_sqm * rng.uniform(0.82, 0.97)
    current = START
    # ~3% of units already vacant on 1 Jan 2023
    if rng.random() < 0.03:
        current = START + pd.Timedelta(days=int(rng.integers(10, 120)))
        start = current
        rent_sqm = market_sqm * rng.uniform(0.98, 1.06)

    while True:
        # Daily move-out hazard; older, worse-energy buildings churn a bit more
        hazard = c["moveout_p"] * (1.15 if p.energy_class in "FG" else 1.0)
        tenure_days = int(rng.exponential(365 / hazard))
        end = max(current, start) + pd.Timedelta(days=tenure_days)
        rec = dict(
            tenancy_id=f"T{tid:05d}", unit_id=u.unit_id,
            start_date=start.date(),
            end_date=end.date() if end <= END else None,
            monthly_rent_eur=round(rent_sqm * u.size_sqm, 2),
            service_charge_eur=round(u.size_sqm * rng.uniform(2.3, 3.1), 2),
        )
        ten_rows.append(rec)
        tid += 1
        if end > END:
            break
        # Vacancy gap: longer for poor energy class, high floors w/o lift, weak cities
        base = rng.gamma(2.0, 22)
        if p.energy_class in "FG": base *= 1.6
        if (not p.has_elevator) and u.floor >= 3: base *= 1.4
        if p.city in ("Gelsenkirchen", "Duisburg"): base *= 1.35
        if rng.random() < 0.08:  # renovation before re-let
            base += rng.integers(45, 120)
        gap = int(base) + 5
        start = end + pd.Timedelta(days=gap)
        current = start
        rent_sqm = market_sqm * rng.uniform(0.98, 1.08) * (1 + 0.025 * ((start.year - 2023)))
        if start > END:
            break

tenancies = pd.DataFrame(ten_rows)

# --------------------------------------------------------------------------
# 4. Rent payments (one row per tenancy per month inside the study period)
# --------------------------------------------------------------------------
months = pd.date_range(START, END, freq="MS")
unit_city = units.merge(properties[["property_id", "city"]], on="property_id").set_index("unit_id")["city"]
pay_rows = []
pid = 1
for t in tenancies.itertuples():
    s = pd.Timestamp(t.start_date)
    e = pd.Timestamp(t.end_date) if t.end_date else END
    city = unit_city[t.unit_id]
    c = CITIES[city]
    chronic = rng.random() < 0.04          # small group of chronic late payers
    for m in months:
        if m < s.replace(day=1) or m > e:
            continue
        due = round(t.monthly_rent_eur + t.service_charge_eur, 2)
        r = rng.random()
        late_p = c["late_p"] * (4 if chronic else 1)
        miss_p = c["miss_p"] * (5 if chronic else 1)
        if r < miss_p:
            paid = round(due * rng.choice([0, 0.5]), 2)
            pdate = (m + pd.Timedelta(days=int(rng.integers(20, 28)))).date() if paid else None
        elif r < miss_p + late_p:
            paid = due
            pdate = (m + pd.Timedelta(days=int(rng.integers(6, 25)))).date()
        else:
            paid = due
            pdate = (m + pd.Timedelta(days=int(rng.integers(0, 4)))).date()
        pay_rows.append(dict(payment_id=f"R{pid:06d}", tenancy_id=t.tenancy_id,
                             month=m.date(), amount_due_eur=due,
                             amount_paid_eur=paid, paid_date=pdate))
        pid += 1
payments = pd.DataFrame(pay_rows)

# --------------------------------------------------------------------------
# 5. Contractors
# --------------------------------------------------------------------------
contractors = pd.DataFrame([
    ("C01", "Contractor A", "Heating & Plumbing", 1.00),
    ("C02", "Contractor B", "Heating & Plumbing", 1.55),   # the slow one
    ("C03", "Contractor C", "Electrical",         0.95),
    ("C04", "Contractor D", "Joinery & Windows",  1.10),
    ("C05", "Contractor E", "General Repairs",    0.90),
    ("C06", "Contractor F", "General Repairs",    1.20),
    ("C07", "Contractor G", "Lift Service",       1.00),
    ("C08", "Contractor H", "Pest & Damp",        1.05),
], columns=["contractor_id", "contractor_name", "trade", "_speed"])

TRADE_FOR = {
    "Heating": "Heating & Plumbing", "Plumbing": "Heating & Plumbing",
    "Electrical": "Electrical", "Windows & Doors": "Joinery & Windows",
    "General Repair": "General Repairs", "Common Areas": "General Repairs",
    "Lift": "Lift Service", "Damp & Mould": "Pest & Damp", "Pest Control": "Pest & Damp",
}
# Category: (base yearly rate per unit, median cost EUR, cost sigma)
CATS = {
    "Heating":         (0.30, 260, 0.8),
    "Plumbing":        (0.28, 190, 0.8),
    "Electrical":      (0.14, 150, 0.7),
    "Windows & Doors": (0.12, 220, 0.7),
    "General Repair":  (0.25, 120, 0.7),
    "Common Areas":    (0.10, 140, 0.6),
    "Lift":            (0.00, 480, 0.6),   # only buildings with a lift
    "Damp & Mould":    (0.09, 520, 0.7),
    "Pest Control":    (0.04, 180, 0.5),
}
PRIORITY_SLA_H = {"Emergency": 24, "High": 72, "Normal": 240, "Low": 480}

# --------------------------------------------------------------------------
# 6. Maintenance tickets
# --------------------------------------------------------------------------
days = pd.date_range(START, END, freq="D")
month_of_day = days.month.values
tick_rows = []
k = 1
for u in units.itertuples():
    p = prop_lookup.loc[u.property_id]
    age_mult = 1.6 if p.year_built < 1970 else 1.25 if p.year_built < 1990 else 0.85 if p.year_built < 2005 else 0.6
    for cat, (rate, med_cost, sig) in CATS.items():
        r = rate
        if cat == "Lift":
            r = 0.07 if p.has_elevator else 0
        if cat == "Damp & Mould" and p.energy_class in "FG":
            r *= 2.2
        r *= age_mult if cat != "Lift" else 1
        if r == 0:
            continue
        # seasonal weights
        w = np.ones(len(days))
        if cat == "Heating":
            w = np.where(np.isin(month_of_day, [10, 11, 12, 1, 2, 3]), 3.2, 0.35)
        if cat == "Damp & Mould":
            w = np.where(np.isin(month_of_day, [11, 12, 1, 2]), 2.0, 0.8)
        n = rng.poisson(r * 3)
        if n == 0:
            continue
        chosen = rng.choice(days, n, p=w / w.sum())
        options = contractors[contractors.trade == TRADE_FOR[cat]]
        for d in chosen:
            d = pd.Timestamp(d) + pd.Timedelta(hours=int(rng.integers(7, 19)))
            if cat in ("Heating", "Lift") and d.month in (11, 12, 1, 2):
                prio = rng.choice(["Emergency", "High", "Normal"], p=[0.30, 0.45, 0.25])
            elif cat == "Damp & Mould":
                prio = rng.choice(["High", "Normal", "Low"], p=[0.2, 0.55, 0.25])
            else:
                prio = rng.choice(["Emergency", "High", "Normal", "Low"], p=[0.06, 0.24, 0.50, 0.20])
            con = options.sample(1, random_state=int(rng.integers(1e9))).iloc[0]
            sla = PRIORITY_SLA_H[prio]
            hours = rng.gamma(2.2, sla * 0.42) * con["_speed"]
            if cat == "Heating" and d.month in (12, 1):
                hours *= 1.25  # winter backlog
            closed = d + pd.Timedelta(hours=float(hours))
            status = "Closed"
            cost = round(float(rng.lognormal(np.log(med_cost), sig * 0.6)), 2)
            if closed > END + pd.Timedelta(days=1):
                closed, status, cost = None, rng.choice(["Open", "In Progress"]), None
            tick_rows.append(dict(
                ticket_id=f"M{k:06d}", unit_id=u.unit_id, property_id=u.property_id,
                created_at=d,
                category=cat, priority=prio, contractor_id=con["contractor_id"],
                status=status, closed_at=closed, repair_cost_eur=cost,
            ))
            k += 1
tickets = pd.DataFrame(tick_rows).sort_values("created_at").reset_index(drop=True)
tickets["ticket_id"] = [f"M{i:06d}" for i in range(1, len(tickets) + 1)]
contractors = contractors.drop(columns="_speed")

# --------------------------------------------------------------------------
# 7. Inject realistic data-quality problems into the RAW exports
# --------------------------------------------------------------------------
props_raw = properties.copy()
idx = rng.choice(props_raw.index, 14, replace=False)
variants = {"Essen": ["essen", "ESSEN", "Essen "], "Mülheim": ["Muelheim", "Mülheim an der Ruhr"],
            "Gelsenkirchen": ["Gelsenkirchen ", "GE"], "Dortmund": ["dortmund"],
            "Bochum": ["Bochum "], "Duisburg": ["duisburg"]}
for i in idx:
    props_raw.loc[i, "city"] = rng.choice(variants[props_raw.loc[i, "city"]])
props_raw.loc[rng.choice(props_raw.index, 3, replace=False), "energy_class"] = None

t_raw = tickets.copy()
t_raw["created_at"] = t_raw["created_at"].dt.strftime("%Y-%m-%d %H:%M")
t_raw["closed_at"] = pd.to_datetime(t_raw["closed_at"]).dt.strftime("%Y-%m-%d %H:%M")
# ~7% of dates typed in German format by one regional office
ger = rng.choice(t_raw.index, int(len(t_raw) * 0.07), replace=False)
t_raw.loc[ger, "created_at"] = pd.to_datetime(t_raw.loc[ger, "created_at"]).dt.strftime("%d.%m.%Y %H:%M")
# duplicates from a system re-export
dups = t_raw.sample(int(len(t_raw) * 0.012), random_state=SEED)
t_raw = pd.concat([t_raw, dups]).sort_index(kind="stable").reset_index(drop=True)
# closed tickets with missing cost
closed_idx = t_raw.index[t_raw.status == "Closed"]
t_raw.loc[rng.choice(closed_idx, 160, replace=False), "repair_cost_eur"] = None
# a few negative costs (credit notes keyed wrongly)
t_raw.loc[rng.choice(closed_idx, 12, replace=False), "repair_cost_eur"] *= -1
# a few closed dates before created dates (keying errors)
bad = rng.choice(closed_idx, 25, replace=False)
_c = t_raw.loc[bad, "created_at"]
_c = (pd.to_datetime(_c, format="%Y-%m-%d %H:%M", errors="coerce")
        .fillna(pd.to_datetime(_c, format="%d.%m.%Y %H:%M", errors="coerce")))
t_raw.loc[bad, "closed_at"] = (_c - pd.Timedelta(days=2)).dt.strftime("%Y-%m-%d %H:%M")
# inconsistent category labels
t_raw.loc[rng.choice(t_raw.index, 40, replace=False), "category"] = "heating"
t_raw.loc[rng.choice(t_raw.index, 25, replace=False), "category"] = "Mould/Damp"

# --------------------------------------------------------------------------
# 8. Save
# --------------------------------------------------------------------------
props_raw.to_csv(RAW / "properties.csv", index=False)
units.to_csv(RAW / "units.csv", index=False)
tenancies.to_csv(RAW / "tenancies.csv", index=False)
payments.to_csv(RAW / "rent_payments.csv", index=False)
contractors.to_csv(RAW / "contractors.csv", index=False)
t_raw.to_csv(RAW / "maintenance_tickets.csv", index=False)

for name, df in [("properties", props_raw), ("units", units), ("tenancies", tenancies),
                 ("rent_payments", payments), ("contractors", contractors),
                 ("maintenance_tickets", t_raw)]:
    print(f"{name:22s} {len(df):>7,d} rows")
