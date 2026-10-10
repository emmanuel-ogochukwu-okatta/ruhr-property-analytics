# DAX Measures

Create a blank table called **_Measures** (Home → Enter data → name it `_Measures` → Load), then add each measure below with **Modeling → New measure**. Keeping all measures in one table makes the model tidy — reviewers notice this.

Set the format shown after each measure in **Measure tools → Format**.

---

## Portfolio

```DAX
Units = COUNTROWS ( dim_unit )
```
Format: whole number

```DAX
Properties = COUNTROWS ( dim_property )
```

```DAX
Total m² = SUM ( dim_unit[size_sqm] )
```
Format: whole number, thousands separator

```DAX
Avg Rent per m² (current) =
VAR ActiveRent =
    CALCULATE ( SUM ( fact_tenancy[monthly_rent_eur] ), fact_tenancy[is_active_end_2025] = TRUE () )
VAR ActiveSqm =
    CALCULATE (
        SUMX ( fact_tenancy, RELATED ( dim_unit[size_sqm] ) ),
        fact_tenancy[is_active_end_2025] = TRUE ()
    )
RETURN
    DIVIDE ( ActiveRent, ActiveSqm )
```
Format: currency €, 2 decimals

## Occupancy & vacancy

```DAX
Occupancy % =
DIVIDE ( SUM ( fact_unit_month[occupied_days] ), SUM ( fact_unit_month[days_in_month] ) )
```
Format: percentage, 1 decimal

```DAX
Vacancy % = 1 - [Occupancy %]
```

```DAX
Vacant Days = SUM ( fact_unit_month[vacant_days] )
```

```DAX
Lost Rent € = SUM ( fact_unit_month[lost_rent_eur] )
```
Format: currency €, 0 decimals

```DAX
Lost Rent per Unit € = DIVIDE ( [Lost Rent €], [Units] )
```

## Rent collection

```DAX
Rent Due € = SUM ( fact_rent_payment[amount_due_eur] )
```

```DAX
Rent Collected € = SUM ( fact_rent_payment[amount_paid_eur] )
```

```DAX
Collection Rate % = DIVIDE ( [Rent Collected €], [Rent Due €] )
```
Format: percentage, 2 decimals

```DAX
Arrears € = SUM ( fact_rent_payment[arrears_eur] )
```

```DAX
Late or Missed % =
DIVIDE (
    CALCULATE ( COUNTROWS ( fact_rent_payment ), fact_rent_payment[payment_status] <> "On time" ),
    COUNTROWS ( fact_rent_payment )
)
```
Format: percentage, 1 decimal

```DAX
Problem Tenancies =
COUNTROWS (
    FILTER (
        VALUES ( fact_rent_payment[tenancy_id] ),
        CALCULATE ( COUNTROWS ( fact_rent_payment ), fact_rent_payment[payment_status] <> "On time" ) >= 4
    )
)
```
Tenancies with 4 or more late, partial or missed months — matches SQL query Q9.

## Maintenance

```DAX
Tickets = COUNTROWS ( fact_ticket )
```

```DAX
Open Tickets =
CALCULATE ( [Tickets], fact_ticket[status] IN { "Open", "In Progress" } )
```

```DAX
Repair Cost € = SUM ( fact_ticket[repair_cost_eur] )
```

```DAX
Repair Cost per Unit € = DIVIDE ( [Repair Cost €], [Units] )
```

```DAX
Months in Selection = DISTINCTCOUNT ( fact_unit_month[month] )
```

```DAX
Tickets per 100 Units / Year =
DIVIDE ( [Tickets], [Units] ) * 100 / DIVIDE ( [Months in Selection], 12 )
```
Format: decimal, 0 decimals. Normalises for building size and the period selected, so small and large buildings can be compared fairly.

```DAX
Avg Resolution Hours = AVERAGE ( fact_ticket[resolution_hours] )
```
Blank resolution hours (open tickets and data-quality exclusions) are ignored automatically.

```DAX
SLA Met % =
DIVIDE (
    CALCULATE ( [Tickets], fact_ticket[sla_met] = "Yes" ),
    CALCULATE ( [Tickets], NOT ISBLANK ( fact_ticket[resolution_hours] ) )
)
```
Format: percentage, 1 decimal

## Time intelligence (needs dim_date marked as date table)

```DAX
Tickets LY = CALCULATE ( [Tickets], SAMEPERIODLASTYEAR ( dim_date[date] ) )
```

```DAX
Tickets YoY % = DIVIDE ( [Tickets] - [Tickets LY], [Tickets LY] )
```

```DAX
Collection Rate LY % =
CALCULATE ( [Collection Rate %], SAMEPERIODLASTYEAR ( dim_date[date] ) )
```

## Dynamic titles (small touch, big impression)

```DAX
Title Maintenance =
"Repair tickets — " &
IF ( ISFILTERED ( dim_property[city] ), SELECTEDVALUE ( dim_property[city], "selected cities" ), "all cities" )
```
Use in a visual's title: **Format → General → Title → fx → Field value → Title Maintenance**.

---

## Check your numbers

With no filters applied, your cards should match `outputs/insights.md`:

| Measure | Expected |
|---|---:|
| Units | 1,308 |
| Occupancy % | 98.1% |
| Collection Rate % | 97.80% |
| Tickets | 7,048 |
| SLA Met % | 57.5% |

If a number is different, check the relationships and data types first (see BUILD_GUIDE.md, steps 3–4).
