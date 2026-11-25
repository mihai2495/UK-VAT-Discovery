"""Builds two clean tables from the raw Companies House table made by load.py:

  companies_all : every company, with a normalised 8-character company number
  sample_main   : a random sample of ACTIVE companies (repeatable: same seed = same sample)

Usage:  python make_sample.py            (sample size from config.py, default 100000)
        python make_sample.py 50000      (your own sample size)
"""
import sys
from config import connect, RAW_TABLE, ALL_TABLE, SAMPLE_TABLE, SAMPLE_SIZE, SAMPLE_SEED

size = int(sys.argv[1]) if len(sys.argv) > 1 else SAMPLE_SIZE

conn = connect()
cur = conn.cursor()

# 1. Check that the raw table has the columns we expect
cur.execute(
    "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (RAW_TABLE,)
)
cols = {r[0] for r in cur.fetchall()}
if not cols:
    sys.exit(f"Table {RAW_TABLE} does not exist. Run load.py first.")
needed = {"companynumber", "companyname", "companystatus"}
if not needed <= cols:
    print("Missing columns:", sorted(needed - cols))
    print("Columns that exist:", sorted(cols))
    sys.exit("Edit the column names inside make_sample.py to match the list above.")
has_category = "companycategory" in cols

# 2. All companies, with the number in one clean format (same rule as norm_company in cc_scan.py)
cur.execute(f"DROP TABLE IF EXISTS {ALL_TABLE} CASCADE")
cur.execute(f"""
    CREATE TABLE {ALL_TABLE} AS
    SELECT CASE WHEN TRIM(companynumber) ~ '^[0-9]+$'
                THEN LPAD(TRIM(companynumber), 8, '0')
                ELSE UPPER(REPLACE(TRIM(companynumber), ' ', '')) END AS company_number,
           companyname AS company_name,
           companystatus AS company_status
           {', companycategory AS company_category' if has_category else ''}
    FROM {RAW_TABLE}
    WHERE companynumber IS NOT NULL AND TRIM(companynumber) <> ''
""")
cur.execute(f"CREATE INDEX ON {ALL_TABLE} (company_number)")
cur.execute(f"SELECT COUNT(*) FROM {ALL_TABLE}")
total = cur.fetchone()[0]
print(f"{ALL_TABLE}: {total} companies")

# 3. Random sample of active companies.
#    Sorting by md5(number + seed) gives a random-looking order that is exactly repeatable.
cur.execute(f"DROP TABLE IF EXISTS {SAMPLE_TABLE}")
cur.execute(f"""
    CREATE TABLE {SAMPLE_TABLE} AS
    SELECT * FROM {ALL_TABLE}
    WHERE company_status ILIKE 'active%%'
    ORDER BY md5(company_number || %s)
    LIMIT %s
""", (SAMPLE_SEED, size))
cur.execute(f"CREATE INDEX ON {SAMPLE_TABLE} (company_number)")
cur.execute(f"SELECT COUNT(*) FROM {SAMPLE_TABLE}")
n = cur.fetchone()[0]
cur.execute(f"SELECT COUNT(*) FROM {ALL_TABLE} WHERE company_status ILIKE 'active%'")
active = cur.fetchone()[0]
print(f"{SAMPLE_TABLE}: {n} companies = {n / active:.2%} of the {active} active companies (seed '{SAMPLE_SEED}')")

# 4. Evidence that the sample is representative: compare company types, sample vs all active
if has_category:
    print("\nCompany type: share in the sample vs share among all active companies")
    cur.execute(f"""
        SELECT a.company_category,
               COUNT(*)::float / %s AS share_all,
               COALESCE(s.c, 0)::float / %s AS share_sample
        FROM {ALL_TABLE} a
        LEFT JOIN (SELECT company_category, COUNT(*) c FROM {SAMPLE_TABLE} GROUP BY 1) s
               ON s.company_category = a.company_category
        WHERE a.company_status ILIKE 'active%%'
        GROUP BY a.company_category, s.c
        ORDER BY 2 DESC LIMIT 6
    """, (active, n))
    for cat, share_all, share_sample in cur.fetchall():
        print(f"  {str(cat)[:45]:45s} all: {share_all:6.1%}   sample: {share_sample:6.1%}")

conn.commit()
