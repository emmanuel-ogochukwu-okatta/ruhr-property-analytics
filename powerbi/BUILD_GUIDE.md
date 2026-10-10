# Power BI Build Guide — step by step

Time needed: about 6–10 hours spread over a few evenings. Build it yourself, click by click — in an interview you will be asked *how* you built it, and you need to be able to answer from experience.

**You need:** Power BI Desktop (free, Windows — Microsoft Store), the CSV files in `data/clean/`, `DAX_measures.md` and `ruhr_theme.json` from this folder.

---

## Step 1 — Load the data

1. Open Power BI Desktop → **Get data → Text/CSV**.
2. Load all 8 files from `data/clean/` one by one: `dim_property`, `dim_unit`, `dim_contractor`, `dim_date`, `fact_tenancy`, `fact_rent_payment`, `fact_ticket`, `fact_unit_month`.
3. In each preview window click **Transform Data** (not Load) the first time, so you can check types in Power Query.

## Step 2 — Check data types in Power Query

German Windows settings can misread decimals. For every CSV: **Home → (gear icon on the Source step) → File origin: 65001 Unicode (UTF-8)**, and set types with **Using Locale → English (United States)** if numbers look wrong (e.g. 7.4 shown as 74).

| Table | Column | Type |
|---|---|---|
| dim_date | date | Date |
| fact_ticket | created_at, closed_at | Date/Time |
| fact_ticket | created_date, closed_date | Date |
| fact_ticket | repair_cost_eur, resolution_hours | Decimal number |
| fact_rent_payment | month, paid_date | Date |
| fact_unit_month | month | Date |
| fact_tenancy | start_date, end_date | Date |
| fact_tenancy | is_active_end_2025 | True/False |
| all money columns (`*_eur`) | | Decimal number |

Then **Close & Apply**.

> Screenshot tip: take a screenshot of the Applied Steps pane — it shows you know Power Query.

## Step 3 — Build the data model (Model view)

Delete any relationships Power BI guessed automatically, then create these (drag column onto column). All are **one-to-many, single direction**:

| From (one side) | To (many side) |
|---|---|
| dim_property[property_id] | dim_unit[property_id] |
| dim_unit[unit_id] | fact_unit_month[unit_id] |
| dim_unit[unit_id] | fact_rent_payment[unit_id] |
| dim_unit[unit_id] | fact_tenancy[unit_id] |
| dim_unit[unit_id] | fact_ticket[unit_id] |
| dim_contractor[contractor_id] | fact_ticket[contractor_id] |
| dim_date[date] | fact_ticket[created_date] |
| dim_date[date] | fact_rent_payment[month] |
| dim_date[date] | fact_unit_month[month] |

Do **not** relate `fact_ticket[property_id]` to `dim_property` — the path already runs through `dim_unit`, and a second path makes the model ambiguous.

Then:
- Select `dim_date` → **Table tools → Mark as date table** → column `date`.
- Hide all ID columns in the fact tables (right-click → Hide in report view). It keeps the field list clean.
- Sort `dim_date[month_name]` by `month_num` (**Column tools → Sort by column**).

> Screenshot tip: arrange the model as a neat star/snowflake and screenshot it for the README.

## Step 4 — Add the measures

Create a `_Measures` table and add every measure from `DAX_measures.md`. Then put four cards on a test page and compare with the **Check your numbers** table at the end of that file. Fix any difference before designing pages.

## Step 5 — Apply the theme

**View → Themes → Browse for themes →** `ruhr_theme.json`. Canvas size: **16:9 (1280 × 720)**.

## Step 6 — Build the four report pages

Layout for every page: a title bar across the top, slicers in one row under it (City, Year, Energy class), KPI cards, then charts. Keep the same positions on every page.

### Page 1 — Portfolio Overview
| Visual | Fields |
|---|---|
| 5 KPI cards | Units · Occupancy % · Avg Rent per m² (current) · Collection Rate % · Open Tickets |
| Line chart | X: dim_date[date] (month level) · Y: Occupancy % |
| Clustered bar | Y: dim_property[city] · X: Units |
| Matrix | Rows: city → district · Values: Units, Occupancy %, Collection Rate %, Repair Cost per Unit € |
| Slicers | dim_property[city], dim_date[year] |

### Page 2 — Maintenance & Contractors
| Visual | Fields |
|---|---|
| KPI cards | Tickets · SLA Met % · Avg Resolution Hours · Repair Cost € |
| Column chart | X: dim_date[month_name] · Y: Tickets · Legend: none · Filter: category = Heating (title it "Heating tickets by month") |
| Bar chart | Y: dim_property[building_age_band] · X: Tickets per 100 Units / Year |
| Bar chart | Y: dim_contractor[contractor_name] · X: SLA Met % (sorted ascending) |
| Table | Top 10 properties: property_id, city, year_built, energy_class, Repair Cost per Unit € — use **Filters → Top N = 10 by Repair Cost per Unit €** |
| Slicer | fact_ticket[category], fact_ticket[priority] |

Add **conditional formatting** to the contractor bars: Format → Bars → Colors → fx → rules: SLA Met % < 0.5 → orange `#EB6834`, otherwise blue.

### Page 3 — Vacancy & Energy
| Visual | Fields |
|---|---|
| KPI cards | Vacancy % · Lost Rent € · Vacant Days |
| Column chart | X: dim_property[energy_class] · Y: Lost Rent per Unit € |
| Scatter chart | Details: dim_property[property_id] · X: dim_property[year_built] · Y: Repair Cost per Unit € · Size: Units |
| Line chart | X: dim_date[date] · Y: Vacancy % · Small multiples: dim_property[city] |

### Page 4 — Rent Collection
| Visual | Fields |
|---|---|
| KPI cards | Rent Due € · Collection Rate % · Arrears € · Problem Tenancies |
| Bar chart | Y: city · X: Late or Missed % (sorted descending) |
| Line chart | X: dim_date[date] · Y: Collection Rate % |
| Table | tenancy_id, city, Arrears €, filter: Problem Tenancies ≥ 1, sorted by Arrears € |

## Step 7 — Interactivity (this is what impresses)

1. **Sync slicers** across pages: View → Sync slicers → tick all pages for City and Year.
2. **Navigation buttons**: Insert → Buttons → Navigator → Page navigator. Place on every page.
3. **Tooltip page**: new page → Format → Page information → Allow use as tooltip; size Tooltip. Add a card for Units, Occupancy %, Repair Cost per Unit €. On the city bar chart: Format → Tooltips → Type: Report page → select it.
4. **Drill-through**: on a new "Property Detail" page, drag dim_property[property_id] into **Drill through**. Add the property's tickets table and rent collection line. Now users can right-click any property → Drill through.
5. **Bookmark** a "Reset filters" state and attach it to a button.

## Step 8 — Write the insights on the dashboard

Add one text box per page with 1–2 sentences: what the chart shows and what the business should do. Use `outputs/insights.md` as your starting point but write it in your own words. Employers hire analysts for the *so what*, not the chart.

## Step 9 — Export and publish

1. Save as `powerbi/Ruhr_Property_Dashboard.pbix`.
2. Take a clean screenshot of each page (Windows: Win + Shift + S) and save as `docs/page1_overview.png` … `docs/page4_rent.png`.
3. **File → Export → Export to PDF** → `docs/Ruhr_Property_Dashboard.pdf` (recruiters on phones can open it).
4. Optional: record a 60–90 second walkthrough video (Windows: Win + G or Clipchamp) and link it in the README and on LinkedIn.

*Note:* "Publish to web" needs a work or school account; with a private email address, screenshots + PDF + the .pbix in GitHub is the standard approach.

## Step 10 — Update the README

Replace the screenshot placeholders in `README.md` with your images, push to GitHub, and pin the repository on your GitHub profile.

---

### Interview questions you should be ready for
- Why a star schema? Why single-direction relationships?
- Why did you leave missing repair costs blank instead of filling them with the average?
- How is "Tickets per 100 Units / Year" calculated, and why normalise?
- What would you recommend to management first, and why?
- What would you do with real data that you could not do with this dataset?
