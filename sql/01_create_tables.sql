-- 01_create_tables.sql
-- Star schema for the Ruhr Wohnen property portfolio.
-- Written for SQLite; also runs on PostgreSQL / SQL Server with minor type changes
-- (TEXT -> VARCHAR, REAL -> DECIMAL).

DROP TABLE IF EXISTS fact_unit_month;
DROP TABLE IF EXISTS fact_ticket;
DROP TABLE IF EXISTS fact_rent_payment;
DROP TABLE IF EXISTS fact_tenancy;
DROP TABLE IF EXISTS dim_unit;
DROP TABLE IF EXISTS dim_property;
DROP TABLE IF EXISTS dim_contractor;
DROP TABLE IF EXISTS dim_date;

CREATE TABLE dim_property (
    property_id        TEXT PRIMARY KEY,
    city               TEXT NOT NULL,
    district           TEXT,
    address            TEXT,
    year_built         INTEGER,
    energy_class       TEXT,
    has_elevator       TEXT,
    units_count        INTEGER,
    building_age_band  TEXT
);

CREATE TABLE dim_unit (
    unit_id      TEXT PRIMARY KEY,
    property_id  TEXT NOT NULL REFERENCES dim_property(property_id),
    floor        INTEGER,
    rooms        INTEGER,
    size_sqm     REAL
);

CREATE TABLE dim_contractor (
    contractor_id    TEXT PRIMARY KEY,
    contractor_name  TEXT,
    trade            TEXT
);

CREATE TABLE dim_date (
    date               TEXT PRIMARY KEY,
    year               INTEGER,
    quarter            TEXT,
    month_num          INTEGER,
    month_name         TEXT,
    year_month         TEXT,
    is_heating_season  TEXT
);

CREATE TABLE fact_tenancy (
    tenancy_id          TEXT PRIMARY KEY,
    unit_id             TEXT NOT NULL REFERENCES dim_unit(unit_id),
    start_date          TEXT,
    end_date            TEXT,
    monthly_rent_eur    REAL,
    service_charge_eur  REAL,
    is_active_end_2025  TEXT
);

CREATE TABLE fact_rent_payment (
    payment_id       TEXT PRIMARY KEY,
    tenancy_id       TEXT NOT NULL REFERENCES fact_tenancy(tenancy_id),
    month            TEXT,
    amount_due_eur   REAL,
    amount_paid_eur  REAL,
    paid_date        TEXT,
    days_late        REAL,
    arrears_eur      REAL,
    payment_status   TEXT,
    unit_id          TEXT REFERENCES dim_unit(unit_id)
);

CREATE TABLE fact_ticket (
    ticket_id         TEXT PRIMARY KEY,
    unit_id           TEXT REFERENCES dim_unit(unit_id),
    property_id       TEXT REFERENCES dim_property(property_id),
    created_at        TEXT,
    category          TEXT,
    priority          TEXT,
    contractor_id     TEXT REFERENCES dim_contractor(contractor_id),
    status            TEXT,
    closed_at         TEXT,
    repair_cost_eur   REAL,
    dq_flag           TEXT,
    sla_hours         INTEGER,
    resolution_hours  REAL,
    sla_met           TEXT,
    created_date      TEXT,
    closed_date       TEXT
);

CREATE TABLE fact_unit_month (
    unit_id         TEXT REFERENCES dim_unit(unit_id),
    month           TEXT,
    days_in_month   INTEGER,
    occupied_days   INTEGER,
    vacant_days     INTEGER,
    lost_rent_eur   REAL,
    PRIMARY KEY (unit_id, month)
);

CREATE INDEX ix_ticket_property ON fact_ticket(property_id);
CREATE INDEX ix_payment_tenancy ON fact_rent_payment(tenancy_id);
CREATE INDEX ix_unit_month_month ON fact_unit_month(month);
