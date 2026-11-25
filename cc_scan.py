"""Scans Common Crawl WET files for company/VAT number candidates.

Run setup_db.py before the first scan to create or migrate the database schema.

Examples:
  python cc_scan.py "C:\\path\\file.warc.wet.gz"
  python cc_scan.py file1.warc.wet.gz file2.warc.wet.gz
  python cc_scan.py --list "C:\\path\\wet.paths.gz" --n 20
  python cc_scan.py --list "C:\\path\\wet.paths.gz" --n 20 --skip 20

Each company/VAT pair is scoped to a text paragraph and nearby mentions.
Ambiguous pairs are saved as such for review rather than silently guessed.
"""
import argparse
import gzip
import hashlib
import itertools
import re
import time
from contextlib import contextmanager
from urllib.parse import urljoin

import requests
from psycopg2 import sql
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from warcio.archiveiterator import ArchiveIterator

from config import connect, SAMPLE_TABLE, ALL_TABLE, NUMBER_COLUMN, WET_BASE_URL
from vat_checksum import is_valid_checksum, normalize as normalize_vat

PAIR_WINDOW_CHARS = 500
DEFAULT_MAX_PAGE_BYTES = 2 * 1024 * 1024
EXTRACTOR_VERSION = "cc_scan_v2"
READ_CHUNK_BYTES = 64 * 1024

COMPANY_RE = re.compile(
    r"(?:company|registered)\s*(?:registration\s*)?(?:number|no\.?|#)\s*[:\-]?\s*((?:[A-Z]{2})?\d{6,8})\b",
    re.I,
)
VAT_RE = re.compile(
    r"\bVAT\s*(?:(?:registration|reg\.?)\s*)?(?:number|no\.?|#)?\s*[:\-]?\s*"
    r"(?:GB\s*)?(?P<vat>\d(?:[\s.-]?\d){8}(?:[\s.-]?\d{3})?)\b",
    re.I,
)

_retry = Retry(
    total=3,
    connect=3,
    read=2,
    status=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    respect_retry_after_header=True,
)
_http = requests.Session()
_http.mount("https://", HTTPAdapter(max_retries=_retry))
_http.mount("http://", HTTPAdapter(max_retries=_retry))


def norm_company(raw):
    """Return company numbers in the same format as the Companies House table."""
    raw = re.sub(r"\s+", "", str(raw).strip().upper())
    return raw.zfill(8) if raw.isdigit() else raw


def load_numbers(conn, table):
    """Load normalized company numbers and fingerprint the values used."""
    numbers = set()
    fingerprint = hashlib.sha256()
    query = sql.SQL("SELECT {number} FROM {table} ORDER BY {number}").format(
        number=sql.Identifier(NUMBER_COLUMN),
        table=sql.Identifier(table),
    )
    with conn.cursor(name="load_numbers") as cur:
        cur.itersize = 200_000
        cur.execute(query)
        for (value,) in cur:
            if value:
                number = norm_company(value)
                numbers.add(number)
                fingerprint.update(number.encode("utf-8"))
                fingerprint.update(b"\n")
    conn.commit()
    return numbers, fingerprint.hexdigest()


@contextmanager
def open_wet(src):
    """Open a local WET file or stream a remote one with bounded request retries."""
    if re.match(r"^https?://", src, re.I):
        with _http.get(src, stream=True, timeout=(30, 120)) as response:
            response.raise_for_status()
            yield response.raw
    else:
        with open(src, "rb") as stream:
            yield stream


def read_page(record, max_bytes):
    """Read at most max_bytes into memory, draining any remainder for archive iteration."""
    content = record.content_stream()
    data = bytearray()
    remaining = max_bytes
    while remaining:
        chunk = content.read(min(READ_CHUNK_BYTES, remaining))
        if not chunk:
            break
        data.extend(chunk)
        remaining -= len(chunk)

    truncated = bool(content.read(1))
    if truncated:
        while content.read(READ_CHUNK_BYTES):
            pass

    return data.decode("utf-8", errors="ignore"), truncated


def paragraph_ranges(text):
    """Yield text ranges separated by blank lines."""
    start = 0
    for separator in re.finditer(r"\n\s*\n", text):
        yield start, separator.start()
        start = separator.end()
    yield start, len(text)


def extract_pairs(text, known):
    """Return nearby company/VAT pairs and the number of distinct page mentions."""
    pairs = {}
    company_numbers = set()
    vat_count = 0
    for paragraph_start, paragraph_end in paragraph_ranges(text):
        all_companies = [
            (norm_company(match.group(1)), match.start(1), match.end(1))
            for match in COMPANY_RE.finditer(text, paragraph_start, paragraph_end)
        ]
        company_numbers.update(item[0] for item in all_companies)
        companies = [item for item in all_companies if item[0] in known]
        vats = []
        for match in VAT_RE.finditer(text, paragraph_start, paragraph_end):
            vat = normalize_vat(match.group("vat"))
            if vat:
                vats.append((vat, match.start("vat"), match.end("vat")))
        vat_count += len(vats)

        for vat, vat_start, vat_end in vats:
            vat_center = (vat_start + vat_end) // 2
            nearby_companies = [
                company for company in companies
                if abs((company[1] + company[2]) // 2 - vat_center) <= PAIR_WINDOW_CHARS
            ]
            nearby_company_numbers = {item[0] for item in nearby_companies}
            for company, company_start, company_end in nearby_companies:
                if company == vat:
                    continue
                company_center = (company_start + company_end) // 2
                nearby_vats = {
                    other_vat
                    for other_vat, other_start, other_end in vats
                    if abs((other_start + other_end) // 2 - company_center) <= PAIR_WINDOW_CHARS
                }
                status = (
                    "ambiguous"
                    if len(nearby_company_numbers) > 1 or len(nearby_vats) > 1
                    else "single_nearby_pair"
                )
                distance = abs(company_center - vat_center)
                snippet_start = max(
                    paragraph_start, min(company_start, vat_start) - 100
                )
                snippet_end = min(
                    paragraph_end, max(company_end, vat_end) + 100
                )
                key = (company, vat)
                candidate = {
                    "company": company,
                    "vat": vat,
                    "status": status,
                    "distance": distance,
                    "snippet": text[snippet_start:snippet_end],
                }
                previous = pairs.get(key)
                if previous is None:
                    pairs[key] = candidate
                else:
                    if status == "ambiguous":
                        previous["status"] = "ambiguous"
                    if distance < previous["distance"]:
                        previous["distance"] = distance
                        previous["snippet"] = candidate["snippet"]

    return pairs.values(), len(company_numbers), vat_count


def scan_file(cur, src, known, sample, max_page_bytes):
    stats = dict(
        pages=0,
        with_company=0,
        with_vat=0,
        with_both=0,
        pages_truncated=0,
        in_ch=0,
        ambiguous=0,
        checksum_ok=0,
        in_sample=0,
    )
    with open_wet(src) as stream:
        for record in ArchiveIterator(stream):
            if record.rec_type != "conversion":
                continue
            stats["pages"] += 1

            text, truncated = read_page(record, max_page_bytes)
            stats["pages_truncated"] += truncated
            pairs, company_count, vat_count = extract_pairs(text, known)
            stats["with_company"] += company_count > 0
            stats["with_vat"] += vat_count > 0
            stats["with_both"] += company_count > 0 and vat_count > 0

            url = record.rec_headers.get_header("WARC-Target-URI")
            for pair in pairs:
                company = pair["company"]
                vat = pair["vat"]
                checksum_ok = is_valid_checksum(vat)
                in_sample = company in sample
                stats["in_ch"] += 1
                stats["ambiguous"] += pair["status"] == "ambiguous"
                stats["checksum_ok"] += checksum_ok
                stats["in_sample"] += in_sample
                cur.execute(
                    """INSERT INTO cc_candidates
                       (company_number, vat_candidate, checksum_ok, in_sample,
                        company_matches, page_url, wet_file, snippet, match_status,
                        match_distance, page_truncated)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (vat_candidate) DO NOTHING""",
                    (
                        company, vat, checksum_ok, in_sample, company_count,
                        url, src, pair["snippet"], pair["status"],
                        pair["distance"], truncated,
                    ),
                )
    return stats


def files_to_scan(args):
    if args.list:
        start = args.skip
        stop = args.skip + args.n
        with gzip.open(args.list, "rt", encoding="utf-8") as paths_file:
            paths = (
                line.strip() for line in paths_file
                if line.strip()
            )
            selected = itertools.islice(paths, start, stop)
            base_url = WET_BASE_URL.rstrip("/") + "/"
            return [urljoin(base_url, path.lstrip("/")) for path in selected]
    return args.files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", help="WET file paths or URLs")
    parser.add_argument("--list", help="path to wet.paths.gz from one crawl")
    parser.add_argument("--n", type=int, default=10, help="how many files to take from --list")
    parser.add_argument("--skip", type=int, default=0, help="how many paths to skip first")
    parser.add_argument(
        "--max-page-bytes",
        type=int,
        default=DEFAULT_MAX_PAGE_BYTES,
        help=f"maximum page text retained in memory (default: {DEFAULT_MAX_PAGE_BYTES})",
    )
    args = parser.parse_args()

    if args.n < 1:
        parser.error("--n must be greater than zero")
    if args.skip < 0:
        parser.error("--skip cannot be negative")
    if args.max_page_bytes < 1:
        parser.error("--max-page-bytes must be greater than zero")

    files = files_to_scan(args)
    if not files:
        parser.error("Give at least one WET file, or use --list")

    conn = connect()
    cur = conn.cursor()

    sample, sample_fingerprint = load_numbers(conn, SAMPLE_TABLE)
    if ALL_TABLE:
        known, known_fingerprint = load_numbers(conn, ALL_TABLE)
    else:
        known, known_fingerprint = sample, sample_fingerprint

    extractor_version = (
        f"{EXTRACTOR_VERSION};pair_window={PAIR_WINDOW_CHARS};"
        f"max_page_bytes={args.max_page_bytes}"
    )
    print(f"Sample companies: {len(sample)} | Companies we look for: {len(known)}")
    print(f"Files to scan: {len(files)}\n")

    total = dict(
        pages=0,
        with_company=0,
        with_vat=0,
        with_both=0,
        pages_truncated=0,
        in_ch=0,
        ambiguous=0,
        checksum_ok=0,
        in_sample=0,
    )
    done = 0
    for index, src in enumerate(files, 1):
        cur.execute(
            """SELECT sample_fingerprint, known_fingerprint, extractor_version
               FROM scan_runs WHERE wet_file = %s""",
            (src,),
        )
        previous_runs = cur.fetchall()
        if previous_runs:
            signature = (sample_fingerprint, known_fingerprint, extractor_version)
            if signature in previous_runs:
                print(f"[{index}/{len(files)}] already scanned, skipping: {src[-60:]}")
                continue
            raise SystemExit(
                f"{src} was previously scanned with different or legacy inputs. "
                "For a clean rescan, run 'python setup_db.py reset' first; this "
                "also deletes saved candidates and manual VAT checks."
            )

        start = time.time()
        try:
            stats = scan_file(cur, src, known, sample, args.max_page_bytes)
        except Exception as error:
            conn.rollback()
            print(
                f"[{index}/{len(files)}] FAILED "
                f"({type(error).__name__}: {error}): {src[-60:]}"
            )
            continue

        seconds = int(time.time() - start)
        cur.execute(
            """INSERT INTO scan_runs
               (wet_file, pages, pages_with_company, pages_with_vat, pages_with_both,
               pages_truncated, hits_in_ch, hits_ambiguous, hits_checksum_ok,
               hits_in_sample, seconds,
                sample_table, sample_size, known_table, known_size,
                sample_fingerprint, known_fingerprint, extractor_version)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                src, stats["pages"], stats["with_company"], stats["with_vat"],
               stats["with_both"], stats["pages_truncated"], stats["in_ch"],
               stats["ambiguous"], stats["checksum_ok"], stats["in_sample"], seconds,
                SAMPLE_TABLE, len(sample), ALL_TABLE or SAMPLE_TABLE, len(known),
                sample_fingerprint, known_fingerprint, extractor_version,
            ),
        )
        conn.commit()
        done += 1
        for key in total:
            total[key] += stats[key]
        print(
            f"[{index}/{len(files)}] {stats['pages']} pages, "
            f"{stats['with_both']} with both numbers, "
            f"{stats['in_ch']} nearby pairs "
            f"({stats['ambiguous']} ambiguous, {stats['checksum_ok']} checksum ok, "
            f"{stats['in_sample']} in sample, "
            f"{stats['pages_truncated']} truncated), {seconds}s"
        )

    print(f"\nDONE: {done} files scanned this run")
    print(f"Pages scanned:                         {total['pages']}")
    print(f"Pages with a company number:           {total['with_company']}")
    print(f"Pages with a VAT number:               {total['with_vat']}")
    print(f"Pages with both:                       {total['with_both']}")
    print(f"Pages whose text was truncated:        {total['pages_truncated']}")
    print(f"Nearby company/VAT pairs:              {total['in_ch']}")
    print(f"  marked ambiguous:                    {total['ambiguous']}")
    print(f"  of which VAT passes the checksum:    {total['checksum_ok']}")
    print(f"  of which company is in my sample:    {total['in_sample']}")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
