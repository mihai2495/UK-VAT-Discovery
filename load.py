import csv, os, re, psycopg
from dotenv import load_dotenv

load_dotenv()

path = "BasicCompanyDataAsOneFile-2026-11-01.csv"   # your exact filename
BATCH = 200_000

with open(path, newline="", encoding="utf-8-sig") as f:
    header = next(csv.reader(f))
cols = [re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_") for h in header]

conn = psycopg.connect(                              # login comes from .env, never written in the code
    host=os.environ["PG_HOST"], port=os.environ.get("PG_PORT", "5432"),
    dbname=os.environ["PG_DB"], user=os.environ["PG_USER"], password=os.environ["PG_PASSWORD"],
    autocommit=True,                                 # every command is saved at once
)
conn.execute("DROP TABLE IF EXISTS uk_companies_raw")
conn.execute("CREATE TABLE uk_companies_raw (" + ", ".join(f"{c} text" for c in cols) + ")")
print("table created")

loaded = bad = 0
with open(path, newline="", encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    next(reader)                                     # skip header
    batch = []
    for row in reader:
        if len(row) != len(cols):
            bad += 1
            continue
        batch.append(row)
        if len(batch) >= BATCH:
            with conn.cursor() as cur, cur.copy("COPY uk_companies_raw FROM STDIN") as cp:
                for r in batch:
                    cp.write_row(r)
            loaded += len(batch)
            batch = []
            print(loaded, "rows loaded so far")
    if batch:
        with conn.cursor() as cur, cur.copy("COPY uk_companies_raw FROM STDIN") as cp:
            for r in batch:
                cp.write_row(r)
        loaded += len(batch)

print("DONE:", loaded, "rows loaded;", bad, "bad rows skipped")
conn.close()