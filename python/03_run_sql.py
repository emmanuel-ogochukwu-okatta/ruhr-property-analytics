"""
03_run_sql.py
-------------
Loads the clean CSVs into a local SQLite database (no server needed),
then runs every query in sql/02_analysis_queries.sql and saves each result
as a CSV in outputs/sql_results/.

Run:  python python/03_run_sql.py
"""
from pathlib import Path
import re
import sqlite3
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean"
OUT = ROOT / "outputs" / "sql_results"
OUT.mkdir(parents=True, exist_ok=True)
DB = ROOT / "data" / "property_portfolio.db"

con = sqlite3.connect(DB)
con.executescript((ROOT / "sql" / "01_create_tables.sql").read_text(encoding="utf-8"))

for csv in sorted(CLEAN.glob("*.csv")):
    df = pd.read_csv(csv)
    df.to_sql(csv.stem, con, if_exists="append", index=False)
    print(f"loaded {csv.stem:20s} {len(df):>7,d} rows")

sql = (ROOT / "sql" / "02_analysis_queries.sql").read_text(encoding="utf-8")
blocks = re.split(r"^-- (Q\d+): (.*)$", sql, flags=re.M)
# blocks = [preamble, 'Q1', title, body, 'Q2', title, body, ...]
for i in range(1, len(blocks), 3):
    qid, title, body = blocks[i], blocks[i + 1].strip(), blocks[i + 2].strip()
    res = pd.read_sql_query(body, con)
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:50]
    res.to_csv(OUT / f"{qid.lower()}_{slug}.csv", index=False)
    print(f"\n=== {qid}: {title} ({len(res)} rows)")
    print(res.head(12).to_string(index=False))
con.close()
