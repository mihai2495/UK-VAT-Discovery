import sys
from config import connect

conn = connect()
cur = conn.cursor()

# Only on purpose: "python setup_db.py reset" deletes the 3 tables and their data
if len(sys.argv) > 1 and sys.argv[1] == "reset":
    cur.execute("DROP TABLE IF EXISTS cc_candidates, vat_checks, scan_runs")
    print("Old tables deleted.")

cur.execute("""
CREATE TABLE IF NOT EXISTS cc_candidates (
    id              SERIAL PRIMARY KEY,
    company_number  TEXT NOT NULL,
    vat_candidate   TEXT NOT NULL,
    checksum_ok     BOOLEAN,
    in_sample       BOOLEAN,
    company_matches INTEGER,
    page_url        TEXT,
    wet_file        TEXT,
    snippet         TEXT,
    match_status    TEXT NOT NULL DEFAULT 'legacy',
    match_distance  INTEGER,
    page_truncated  BOOLEAN,
    found_at        TIMESTAMP DEFAULT now(),
    UNIQUE (company_number, vat_candidate, page_url)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS vat_checks (
    id               SERIAL PRIMARY KEY,
    cc_candidate_id  INTEGER REFERENCES cc_candidates(id),
    company_number   TEXT NOT NULL,
    vat_candidate    TEXT NOT NULL,
    result           TEXT NOT NULL,   -- match / mismatch / not_registered / unsure
    hmrc_name        TEXT,
    checked_at       TIMESTAMP DEFAULT now()
)
""")

# Keep one candidate row per normalized VAT number. PostgreSQL requires this
# unique index for ON CONFLICT (vat_candidate) in cc_scan.py.
cur.execute("""
WITH ranked AS (
    SELECT id,
           MIN(id) OVER (PARTITION BY vat_candidate) AS keep_id
    FROM cc_candidates
),
duplicates AS (
    SELECT id, keep_id
    FROM ranked
    WHERE id <> keep_id
)
UPDATE vat_checks v
SET cc_candidate_id = d.keep_id
FROM duplicates d
WHERE v.cc_candidate_id = d.id
""")
cur.execute("""
DELETE FROM cc_candidates c
WHERE EXISTS (
    SELECT 1
    FROM cc_candidates retained
    WHERE retained.vat_candidate = c.vat_candidate
      AND retained.id < c.id
)
""")
cur.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS uq_cc_candidates_vat_candidate
ON cc_candidates (vat_candidate)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS scan_runs (
    id                  SERIAL PRIMARY KEY,
    wet_file            TEXT,
    pages               INTEGER,
    pages_with_company  INTEGER,
    pages_with_vat      INTEGER,
    pages_with_both     INTEGER,
    hits_in_ch          INTEGER,
    hits_ambiguous      INTEGER,
    hits_checksum_ok    INTEGER,
    hits_in_sample      INTEGER,
    pages_truncated     INTEGER,
    seconds             INTEGER,
    run_at              TIMESTAMP DEFAULT now()
)
""")

# Columns added later to retain scan inputs and extraction metadata for reproducibility.
for col, typ in [("sample_table", "TEXT"), ("sample_size", "INTEGER"),
                 ("known_table", "TEXT"), ("known_size", "INTEGER"),
                 ("sample_fingerprint", "TEXT"), ("known_fingerprint", "TEXT"),
                 ("extractor_version", "TEXT"), ("pages_truncated", "INTEGER"),
                 ("hits_ambiguous", "INTEGER")]:
    cur.execute(f"ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS {col} {typ}")

for col, typ in [("match_status", "TEXT NOT NULL DEFAULT 'legacy'"),
                 ("match_distance", "INTEGER"), ("page_truncated", "BOOLEAN")]:
    cur.execute(f"ALTER TABLE cc_candidates ADD COLUMN IF NOT EXISTS {col} {typ}")

conn.commit()
print("Tables ready: cc_candidates, vat_checks, scan_runs")