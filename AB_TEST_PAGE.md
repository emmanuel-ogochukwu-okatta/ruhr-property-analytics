# Page 5 — A/B Test: Preventive Heating Checks

Time needed: about 1–2 hours. Run `python python/06_ab_test_analysis.py` first.

The statistics (p-values, confidence intervals, CUPED) are calculated in Python. This page
shows the result to managers and lets them play with the cost of the check.

---

## Step 1 — Load the two files

**Get data → Text/CSV**, from `outputs/ab_test/`:

| File | Grain | Use |
|---|---|---|
| `ab_results_by_building.csv` | one building | all measures below |
| `ab_effect_by_segment.csv` | one segment | table with effect, 95% CI and p-value |

Check types in Power Query (same UTF-8 / English locale tip as in `BUILD_GUIDE.md`):
`post_cost_eur`, `pre_rate_per_unit`, `pre_tickets_season` and all columns in the segment file
except `segment` → Decimal number.

Optional: relate `ab_results_by_building[property_id]` → `dim_property[property_id]`
(many-to-one) so the city slicer from page 1 also filters this page.

## Step 2 — What-if parameter for the check cost

**Modeling → New parameter → Numeric range**: name `Check Cost`, min 100, max 500,
increment 25, default 250. Tick *Add slicer to this page*. This creates the measure
`Check Cost Value`.

## Step 3 — Measures (add to `_Measures`)

```DAX
AB Tickets per 100 Units =
DIVIDE (
    SUM ( ab_results_by_building[post_tickets] ),
    SUM ( ab_results_by_building[units_count] )
) * 100
```
Format: decimal, 1 place

```DAX
AB Pre Tickets per 100 Units =
DIVIDE (
    SUM ( ab_results_by_building[pre_tickets_season] ),
    SUM ( ab_results_by_building[units_count] )
) * 100
```

```DAX
AB Treatment per 100 =
CALCULATE ( [AB Tickets per 100 Units], ab_results_by_building[group] = "Treatment" )
```

```DAX
AB Control per 100 =
CALCULATE ( [AB Tickets per 100 Units], ab_results_by_building[group] = "Control" )
```

```DAX
AB Change % = DIVIDE ( [AB Treatment per 100], [AB Control per 100] ) - 1
```
Format: percentage, 0 places. This is the raw change; the CUPED-adjusted value with its
confidence interval comes from the segment table.

```DAX
AB Emergency per 100 Units =
DIVIDE (
    SUM ( ab_results_by_building[post_emergency] ),
    SUM ( ab_results_by_building[units_count] )
) * 100
```

```DAX
AB Repair Cost per Unit =
DIVIDE (
    SUM ( ab_results_by_building[post_cost_eur] ),
    SUM ( ab_results_by_building[units_count] )
)
```
Format: currency €, 2 places

```DAX
AB Saving per Building =
VAR CostControl =
    CALCULATE ( [AB Repair Cost per Unit], ab_results_by_building[group] = "Control" )
VAR CostTreatment =
    CALCULATE ( [AB Repair Cost per Unit], ab_results_by_building[group] = "Treatment" )
RETURN
    ( CostControl - CostTreatment ) * AVERAGE ( ab_results_by_building[units_count] )
```
Format: currency €, 0 places

```DAX
AB Net per Building = [AB Saving per Building] - [Check Cost Value]
```

```DAX
AB Net Colour = IF ( [AB Net per Building] >= 0, "#2a78d6", "#eb6834" )
```

## Step 4 — Build the page

| Position | Visual | Fields |
|---|---|---|
| Top row | 4 cards | `AB Control per 100`, `AB Treatment per 100`, `AB Change %`, `AB Net per Building` (conditional font colour: field value → `AB Net Colour`) |
| Left | Clustered column chart | X-axis: `group` · Y-axis: `AB Pre Tickets per 100 Units` and `AB Tickets per 100 Units` (rename to "Before" and "Pilot 2025/26") |
| Right | Table | `ab_effect_by_segment`: segment, buildings, effect, ci_low, ci_high, p_value, net_per_building |
| Top right | Slicers | `segment` (from `ab_results_by_building`) and the `Check Cost` parameter |
| Bottom | Text box | The decision from `outputs/ab_test/readout.md`, in one or two sentences |

Format `effect`, `ci_low` and `ci_high` as percentages. In the table, add conditional
formatting to `p_value` (background blue if < 0.05).

## Step 5 — Try it before an interview

- Set the segment slicer to *Built before 1970*: the net saving stays positive even at a check
  cost of €500.
- Set it to *Built 1970 or later*: the saving is only about €105 per building, so the net is
  negative at any realistic price. That's why the recommendation is to keep testing those
  buildings instead of rolling out.

### Questions you should be ready for

- *Why randomise buildings, not flats?* Flats share one boiler; their tickets are not independent.
- *Why stratify by building age?* So old and new buildings are balanced in both groups by design.
- *What is CUPED?* It uses each building's ticket history to remove known noise, giving a
  narrower confidence interval with the same data.
- *The overall p-value is 0.051. Is that a failure?* No. It's borderline, and the test was only
  powered for effects of about 20%. The pre-registered older-building segment is clear, and
  that's where the money is.
- *What would you do next?* Roll out to pre-1970 buildings, keep a 10% control group, and keep
  testing newer buildings for another season.
