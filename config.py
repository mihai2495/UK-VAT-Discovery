import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# ---------- SETTINGS (defaults work as they are; override in .env if needed) ----------
SAMPLE_TABLE = os.environ.get("SAMPLE_TABLE", "sample_main")   # the random sample (made by make_sample.py)
ALL_TABLE = os.environ.get("ALL_TABLE", "companies_all")       # all Companies House companies (made by make_sample.py)
NUMBER_COLUMN = os.environ.get("NUMBER_COLUMN", "company_number")
NAME_COLUMN = os.environ.get("NAME_COLUMN", "company_name")
RAW_TABLE = os.environ.get("RAW_TABLE", "uk_companies_raw")    # the table created by load.py
SAMPLE_SIZE = int(os.environ.get("SAMPLE_SIZE", "100000"))     # how many companies in the sample
SAMPLE_SEED = os.environ.get("SAMPLE_SEED", "veridion-2026-11")  # same seed = same sample
WET_BASE_URL = os.environ.get("WET_BASE_URL", "https://data.commoncrawl.org/")
VERIFY_COUNT = int(os.environ.get("VERIFY_COUNT", "100"))      # decide before looking at results
# --------------------------------------------------------------------------------------


def connect():
    return psycopg2.connect(
        host=os.environ["PG_HOST"],
        port=os.environ.get("PG_PORT", "5432"),
        dbname=os.environ["PG_DB"],
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASSWORD"],
    )
