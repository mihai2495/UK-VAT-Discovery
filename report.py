from config import connect

conn = connect()
cur = conn.cursor()


def one(sql):
    cur.execute(sql)
    return cur.fetchone()[0]


files = one("SELECT COUNT(*) FROM scan_runs")
pages = one("SELECT COALESCE(SUM(pages),0) FROM scan_runs")
secs = one("SELECT COALESCE(SUM(seconds),0) FROM scan_runs")

print("=== DISCOVERY (WET files) ===")
print("WET files scanned:", files)
print("Pages scanned:", pages)
print("Pages with both numbers:", one("SELECT COALESCE(SUM(pages_with_both),0) FROM scan_runs"))
print("Candidates found (company is in Companies House):", one("SELECT COUNT(*) FROM cc_candidates"))
print("  passing the checksum:", one("SELECT COUNT(*) FROM cc_candidates WHERE checksum_ok"))
print("  single nearby company/VAT pair:",
      one("SELECT COUNT(*) FROM cc_candidates WHERE match_status = 'single_nearby_pair'"))
print("  marked ambiguous:",
      one("SELECT COUNT(*) FROM cc_candidates WHERE match_status = 'ambiguous'"))
print("  distinct companies with a checksum-valid candidate:",
      one("SELECT COUNT(DISTINCT company_number) FROM cc_candidates WHERE checksum_ok"))
print("Pages whose text was truncated:",
      one("SELECT COALESCE(SUM(pages_truncated),0) FROM scan_runs"))
if files:
    print(f"Speed: {pages / max(secs, 1):.0f} pages/second, {pages / files:.0f} pages per file")

# The sample size comes from the scans themselves, so it stays correct even if you change the sample later
cur.execute("SELECT DISTINCT sample_table, sample_size, known_size FROM scan_runs WHERE sample_table IS NOT NULL")
runs = cur.fetchall()
print("\n=== COVERAGE OF MY SAMPLE ===")
if len(runs) != 1:
    print("The scans used different samples:", runs)
    print("Run 'python setup_db.py reset' and scan again with one sample, otherwise coverage is not meaningful.")
else:
    sample_table, sample_size, known_size = runs[0]
    covered = one("SELECT COUNT(DISTINCT company_number) FROM cc_candidates WHERE in_sample AND checksum_ok")
    print(f"Sample: {sample_table} ({sample_size} companies, drawn at random from the active companies)")
    print(f"Sample companies with a checksum-valid candidate: {covered} of {sample_size} = {covered / sample_size:.4%}")
    print("Coverage is measured on the files scanned so far only, not on the whole web.")

print("\n=== MANUAL VERIFICATION ===")
total = one("SELECT COUNT(*) FROM vat_checks")
print("Verified:", total)
for res in ("match", "mismatch", "not_registered", "unsure"):
    print(f"  {res}:", one(f"SELECT COUNT(*) FROM vat_checks WHERE result = '{res}'"))

decided = total - one("SELECT COUNT(*) FROM vat_checks WHERE result = 'unsure'")
wrong = one("SELECT COUNT(*) FROM vat_checks WHERE result IN ('mismatch','not_registered')")
if decided:
    print(f"\nFalse-positive rate: {wrong}/{decided} = {wrong / decided:.1%}")
    print("(wrong = different company or not registered; 'unsure' excluded)")
    in_s = one("SELECT COUNT(*) FROM vat_checks v JOIN cc_candidates c ON c.id = v.cc_candidate_id WHERE c.in_sample")
    print(f"Of the verified candidates, {in_s} are companies from the random sample; "
          f"the rest are other companies found on the same pages.")
