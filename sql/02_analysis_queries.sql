-- 02_analysis_queries.sql
-- Business questions a housing company's management would actually ask.
-- Each query starts with a "-- Q<n>:" header; python/03_run_sql.py runs them
-- and saves every result to outputs/sql_results/.

-- Q1: Portfolio overview by city
SELECT  p.city,
        COUNT(DISTINCT p.property_id)          AS properties,
        COUNT(u.unit_id)                       AS units,
        ROUND(SUM(u.size_sqm), 0)              AS total_sqm,
        ROUND(AVG(u.size_sqm), 1)              AS avg_unit_sqm
FROM dim_property p
JOIN dim_unit u ON u.property_id = p.property_id
GROUP BY p.city
ORDER BY units DESC;

-- Q2: Occupancy rate by city and year (share of unit-days let)
SELECT  p.city,
        SUBSTR(m.month, 1, 4)                                        AS year,
        ROUND(100.0 * SUM(m.occupied_days) / SUM(m.days_in_month), 1) AS occupancy_pct
FROM fact_unit_month m
JOIN dim_unit u     ON u.unit_id = m.unit_id
JOIN dim_property p ON p.property_id = u.property_id
GROUP BY p.city, year
ORDER BY p.city, year;

-- Q3: Rent lost to vacancy by energy class (2023-2025)
SELECT  p.energy_class,
        COUNT(DISTINCT u.unit_id)                                     AS units,
        ROUND(SUM(m.lost_rent_eur), 0)                                AS lost_rent_eur,
        ROUND(SUM(m.lost_rent_eur) / COUNT(DISTINCT u.unit_id), 0)    AS lost_rent_per_unit_eur,
        ROUND(100.0 * SUM(m.vacant_days) / SUM(m.days_in_month), 1)   AS vacancy_pct
FROM fact_unit_month m
JOIN dim_unit u     ON u.unit_id = m.unit_id
JOIN dim_property p ON p.property_id = u.property_id
GROUP BY p.energy_class
ORDER BY p.energy_class;

-- Q4: Rent collection rate and arrears by city
SELECT  p.city,
        ROUND(SUM(r.amount_due_eur), 0)                                   AS rent_due_eur,
        ROUND(SUM(r.arrears_eur), 0)                                      AS arrears_eur,
        ROUND(100.0 * SUM(r.amount_paid_eur) / SUM(r.amount_due_eur), 2) AS collection_rate_pct,
        ROUND(100.0 * SUM(CASE WHEN r.payment_status <> 'On time' THEN 1 ELSE 0 END)
              / COUNT(*), 1)                                              AS late_or_missed_pct
FROM fact_rent_payment r
JOIN dim_unit u     ON u.unit_id = r.unit_id
JOIN dim_property p ON p.property_id = u.property_id
GROUP BY p.city
ORDER BY collection_rate_pct;

-- Q5: Repair tickets per 100 units per year by building age
WITH units_by_band AS (
    SELECT p.building_age_band, COUNT(*) AS units
    FROM dim_unit u JOIN dim_property p ON p.property_id = u.property_id
    GROUP BY p.building_age_band
)
SELECT  b.building_age_band,
        b.units,
        COUNT(t.ticket_id)                                         AS tickets,
        ROUND(100.0 * COUNT(t.ticket_id) / b.units / 3, 1)         AS tickets_per_100_units_per_year,
        ROUND(SUM(t.repair_cost_eur) / b.units / 3, 0)             AS repair_cost_per_unit_per_year_eur
FROM units_by_band b
JOIN dim_property p ON p.building_age_band = b.building_age_band
JOIN fact_ticket t  ON t.property_id = p.property_id
GROUP BY b.building_age_band, b.units
ORDER BY b.building_age_band;

-- Q6: Contractor performance (closed tickets with valid dates only)
SELECT  c.contractor_name,
        c.trade,
        COUNT(*)                                                         AS closed_tickets,
        ROUND(AVG(t.resolution_hours), 0)                                AS avg_resolution_hours,
        ROUND(100.0 * SUM(CASE WHEN t.sla_met = 'Yes' THEN 1 ELSE 0 END) / COUNT(*), 1) AS sla_met_pct,
        ROUND(AVG(t.repair_cost_eur), 0)                                 AS avg_cost_eur
FROM fact_ticket t
JOIN dim_contractor c ON c.contractor_id = t.contractor_id
WHERE t.resolution_hours IS NOT NULL
GROUP BY c.contractor_name, c.trade
ORDER BY c.trade, sla_met_pct;

-- Q7: Heating tickets by calendar month (seasonality)
SELECT  CAST(SUBSTR(created_date, 6, 2) AS INTEGER)  AS month_num,
        COUNT(*)                                      AS heating_tickets,
        ROUND(COUNT(*) / 3.0, 0)                      AS avg_per_year
FROM fact_ticket
WHERE category = 'Heating'
GROUP BY month_num
ORDER BY month_num;

-- Q8: Top 10 properties by repair cost per unit (window function)
WITH cost AS (
    SELECT  p.property_id, p.city, p.year_built, p.energy_class, p.units_count,
            SUM(t.repair_cost_eur)                    AS repair_cost_eur,
            SUM(t.repair_cost_eur) / p.units_count    AS cost_per_unit_eur
    FROM dim_property p
    JOIN fact_ticket t ON t.property_id = p.property_id
    GROUP BY p.property_id, p.city, p.year_built, p.energy_class, p.units_count
)
SELECT *
FROM (
    SELECT  property_id, city, year_built, energy_class, units_count,
            ROUND(repair_cost_eur, 0)    AS repair_cost_eur,
            ROUND(cost_per_unit_eur, 0)  AS cost_per_unit_eur,
            RANK() OVER (ORDER BY cost_per_unit_eur DESC) AS cost_rank
    FROM cost
)
WHERE cost_rank <= 10
ORDER BY cost_rank;

-- Q9: Tenancies with repeated payment problems (4+ late/partial/missed months)
SELECT  r.tenancy_id,
        p.city,
        COUNT(*)                                                             AS months_billed,
        SUM(CASE WHEN r.payment_status <> 'On time' THEN 1 ELSE 0 END)       AS problem_months,
        ROUND(SUM(r.arrears_eur), 2)                                         AS open_arrears_eur
FROM fact_rent_payment r
JOIN dim_unit u     ON u.unit_id = r.unit_id
JOIN dim_property p ON p.property_id = u.property_id
GROUP BY r.tenancy_id, p.city
HAVING SUM(CASE WHEN r.payment_status <> 'On time' THEN 1 ELSE 0 END) >= 4
ORDER BY problem_months DESC, open_arrears_eur DESC;

-- Q10: Units with repeat repairs (3+ tickets of the same category)
SELECT  t.unit_id,
        p.city,
        p.year_built,
        t.category,
        COUNT(*)                         AS tickets,
        ROUND(SUM(t.repair_cost_eur), 0) AS cost_eur
FROM fact_ticket t
JOIN dim_property p ON p.property_id = t.property_id
GROUP BY t.unit_id, p.city, p.year_built, t.category
HAVING COUNT(*) >= 3
ORDER BY tickets DESC, cost_eur DESC;
