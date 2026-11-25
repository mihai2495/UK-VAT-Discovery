# VAT Identifier Discovery

Can a UK company VAT dataset be built from the open web? This repo is my attempt, tested on a sample. Only numbers that I checked on HMRC's checker count as found; everything else is a candidate.

## Summary

- Companies House (5,711,779 rows, downloaded 13 November 2026) has company numbers and addresses, but no websites and no VAT numbers.
- I could not get production access to HMRC's API (it needs an organisation identifier I don't have as a student), so I verify candidates by hand on HMRC's free GOV.UK checker.
- Searching company by company failed, so I scan Common Crawl pages for a company number and a VAT number written close together.
- I scanned 243 WET files (5,226,081 pages) and found **382 candidates** for 371 companies. Only **5 of 100,000** companies in my random sample had a valid candidate (0.005%).
- I have verified 5 candidates by hand: 4 matched HMRC's record and 1 was a different company. Only these count as found.
- This route is cheap but reaches few companies, so on its own it cannot solve the problem. With company infrastructure it could be one stage of a larger pipeline.

| Discovery (243 WET files) | |
|---|---|
| Pages scanned | 5,226,081 |
| Pages with both a company number and a VAT number | 5,947 |
| Candidates (company exists in Companies House, VAT number nearby) | 382 |
| Passing the checksum | 379 |
| Single nearby company/VAT pair / marked ambiguous | 368 / 14 |
| Distinct companies with a checksum-valid candidate | 371 |
| Pages whose text was cut at the size limit | 153 |
| Speed | 4,294 pages per second |
| Coverage of my sample (`sample_main`, 100,000 companies) | 5 of 100,000 = 0.0050% |

## Files and how to run

| File | Purpose |
|---|---|
| `load.py` | Loads the Companies House CSV into PostgreSQL |
| `make_sample.py` | Builds `companies_all` and a repeatable random `sample_main` |
| `setup_db.py` | Creates `cc_candidates`, `vat_checks`, `scan_runs` |
| `vat_checksum.py` | Checks the format and checksum of a UK VAT number (no HMRC call) |
| `cc_scan.py` | Scans Common Crawl WET files for company number + VAT number pairs (extractor `cc_scan_v2`) |
| `inspect_both.py` | Prints pages with both numbers, to check the patterns by eye |
| `report.py` | Prints all numbers used below |
| `hmrc_verify.py` | HMRC sandbox client (works with test data only) |

Requirements: Python 3 (developed on 3.14) and a PostgreSQL database. The data files (Companies House CSV, Common Crawl files) are not in this repo; steps 2 and 3 say where to download them.

1. `pip install -r requirements.txt`, copy `.env.example` to `.env`, fill in the database login.
2. Download the Companies House snapshot, then run `python load.py`, `python make_sample.py`, `python setup_db.py`.
3. Download `https://data.commoncrawl.org/crawl-data/CC-MAIN-2026-43/wet.paths.gz`.
4. Scan: `python cc_scan.py --list "path\to\wet.paths.gz" --n 20` (files are streamed, not saved). Use `--skip 20` for the next 20.
5. List the candidates from the sample with the query in Part 2, check each one by hand on the GOV.UK checker, and save the result in `vat_checks` with the `INSERT` statements in [Recording my checks](#recording-my-checks).
6. `python report.py` prints the numbers.
7. Optional: `python test_cc_scan.py` runs the tests for the extractor.

---

# Part 1: Research

## HMRC verifier

HMRC only works backwards: it confirms a number I give it, and never gives a number for a company.

- 13 November 2026: I created a sandbox application and subscribed to "Check a UK VAT number 2.0". The token request returned **200**.
- A badly formatted number returned **400** ("9 or 12 digits"), so I added `normalize_vrn()`. A made-up number returned **404** ("does not match a registered company"). The chain works.
- **200** = registered, still to compare with Companies House. **404** = not registered, candidate rejected.

**Dead end: production access.** The sandbox only knows its own test numbers, so it cannot check real companies. I expected a short form for an API key. The form asks for an organisation identifier (UTR, VAT number, PAYE reference or Companies House number), a privacy policy URL, terms and conditions, and a breach process. I am an individual student and have none of these.

**Decision:** I check candidates by hand on the GOV.UK page, only those that pass the checksum, and I don't automate that page (it is made for people; bulk checks are what the API is for). I keep `hmrc_verify.py` and cover the API in Part 3.

## Dead end: company by company

I planned to take each sample company, find its website and look for a VAT number. This fails because Companies House has no websites, and finding the right site for each company is the hardest step and doesn't scale.

## Common Crawl

Common Crawl is a free public copy of a large part of the web. For each page, `cc_scan.py` looks for a company number and a VAT number, keeps company numbers that exist in my database (that number is the link, I never need the website), runs the checksum, and saves the URL and the text around the numbers as evidence.

**First scan (16 November 2026)**, file `CC-MAIN-20261005105623-20261005135623-00000.warc.wet.gz`, crawl `CC-MAIN-2026-43`, looking for my 40 pilot companies (`sample_b`):

| Measure | Result |
|---|---|
| Pages scanned | 21,463 |
| With a company number / a VAT number | 97 / 46 |
| With both | 28 (0.13%) |
| Company number found in my database | 0 |
| Time | 3 seconds (local file) |

My first run failed with `ArchiveLoadFailed` because I passed `wet.paths.gz`, which is only the list of files. The 0 hits are a coverage result: 40 companies out of 5.7 million are very unlikely to appear in one file.

**What I changed after that:**

- I match pages against all companies (`companies_all`) and mark which ones are in the random sample (`sample_main`), and the scan handles many files in one run.
- **Extractor `cc_scan_v2`:** a company number and a VAT number only form a pair if they are in the same paragraph and within 500 characters of each other. If several company numbers or several VAT numbers are close together, the pair is marked **ambiguous** instead of guessed (14 of 382). Pages are read up to 2 MB, and longer ones are cut and flagged (153 pages). Downloads retry when they fail. Each VAT number is stored once, with the first company it was found with, so a VAT number shown for two different companies (for example a group) is recorded only for the first one.

The results of the 243-file scan are in the table in the summary and in Part 3.

---

# Part 2: Proof of concept

## Samples

I removed dormant companies and companies with no postcode, so every company can be compared with HMRC's address.

- **`sample_a`:** a sample that represents all UK companies. It does not fit this problem, whose customer is a manufacturer with suppliers.
- **`sample_b`:** my 40-company pilot sample, with filters meant to make it closer to a manufacturer's suppliers.
- **`sample_main`:** a random sample of 100,000 active companies, ordered by a hash of the company number plus a fixed seed, so it can be reproduced. It is the sample used for coverage.

I did not pick companies that I knew publish a VAT number.

## Verification

I check candidates by hand on the GOV.UK "Check a UK VAT number" page and record `match` (HMRC's name and address are the company's), `mismatch` (a different company), `not_registered` or `unsure` in `vat_checks`. A number counts as correct only if HMRC's name and address match the Companies House record of that company number.

**Sample companies.** I verified every candidate that belongs to a company in `sample_main`, found with this query:

```sql
SELECT c.company_number, n.company_name, c.vat_candidate,
       BOOL_OR(c.checksum_ok) AS checksum_ok,
       COUNT(*) AS pages, MIN(c.page_url) AS example_page
FROM cc_candidates c
JOIN sample_main s ON s.company_number = c.company_number
LEFT JOIN companies_all n ON n.company_number = c.company_number
GROUP BY c.company_number, n.company_name, c.vat_candidate
ORDER BY c.company_number, c.vat_candidate;
```

### Recording my checks

The candidates are saved in `cc_candidates` by `cc_scan.py`. My GOV.UK check of each one is saved by hand in `vat_checks`, with one of four results: `match`, `mismatch`, `not_registered` or `unsure`. `hmrc_name` is the name HMRC showed. The company number and VAT number are copied from `cc_candidates`, so they cannot be mistyped, and `cc_candidate_id` links the check to its candidate (`report.py` needs it to count how many checked companies are in the sample).

```sql
INSERT INTO vat_checks (cc_candidate_id, company_number, vat_candidate, result, hmrc_name)
SELECT c.id, c.company_number, c.vat_candidate, v.result, v.hmrc_name
FROM (VALUES
    ('123456789', 'match',          'EXAMPLE LTD'),
    ('987654321', 'mismatch',       'OTHER COMPANY LIMITED'),
    ('111222333', 'not_registered', NULL)
) AS v(vat, result, hmrc_name)
JOIN cc_candidates c ON c.vat_candidate = v.vat;
```

The three rows are examples; replace them with the VAT numbers I checked. Two things to know:

- Use the VAT number in the same format as in `cc_candidates` (check with `SELECT vat_candidate FROM cc_candidates LIMIT 5;`). If the format differs, the statement inserts nothing and gives no error.
- `vat_checks` has no unique constraint, so running a statement twice saves the check twice. Remove a wrong row with `DELETE FROM vat_checks WHERE id = <id>;`.

To see the totals: `SELECT result, COUNT(*) FROM vat_checks GROUP BY result;`

## Results

```text
=== DISCOVERY (WET files) ===
WET files scanned: 243
Pages scanned: 5226081
Pages with both numbers: 5947
Candidates found (company is in Companies House): 382
  passing the checksum: 379
  single nearby company/VAT pair: 368
  marked ambiguous: 14
  distinct companies with a checksum-valid candidate: 371
Pages whose text was truncated: 153
Speed: 4294 pages/second, 21507 pages per file

=== COVERAGE OF MY SAMPLE ===
Sample: sample_main (100000 companies, drawn at random from the active companies)
Sample companies with a checksum-valid candidate: 5 of 100000 = 0.0050%
Coverage is measured on the files scanned so far only, not on the whole web.

=== MANUAL VERIFICATION ===
Verified: 5
  match: 4
  mismatch: 1
  not_registered: 0
  unsure: 0
```

Of the 5 candidates from my random sample, 4 matched HMRC and 1 was a different company (20%). Five checks are too few for a reliable rate, so I treat this as an indication only, not a measurement.

## What my numbers don't capture

- **Coverage is for 243 files only,** the first ones on the list, not a random draw of the crawl.
- **"Not found" means two things:** the company is not VAT registered, or my method missed it. I can't tell them apart from the scan.
- **The false-positive rate comes from a small number of checks.**
- **The verified candidates are companies that publish both numbers on a web page,** so the rate may not hold for other companies.
- **Unreachable:** companies with no website, sites missing from the crawl, and VAT numbers only in PDFs, invoices or behind a login.
- **My own filters:** each VAT number is stored once, and pairs further apart than 500 characters are not found.

---

# Part 3: With real resources

## What my run measured

I scanned 243 WET files with one process on my laptop.

| Measure | Result |
|---|---|
| Pages scanned | 5,226,081 (about 21,500 per file) |
| Speed | 4,294 pages per second (includes streaming the download) |
| Pages with both a company number and a VAT number | 5,947 (0.11% of pages) |
| Candidates (company exists in Companies House, VAT within 500 characters) | 382 distinct VAT numbers |
| Passing the checksum | 379 of 382 (99.2%) |
| Marked ambiguous | 14 (3.7%) |
| Distinct companies with a valid candidate | 371 (about 71 per million pages) |
| Coverage of my random sample | 5 of 100,000 = 0.005% (95% interval about 0.002% to 0.012%) |

Two things I learned from these numbers:

- **Most pages with both patterns give no candidate.** At most 6.4% of the 5,947 pages produced a pair. The others have a company number that is not in my data, or the two numbers are not in the same paragraph within 500 characters. I did not investigate which of the two is the main reason.
- **The checksum rejects almost nothing** (3 of 382). It is a sanity check, not a filter. The real risk is a well-formed number that belongs to the wrong company, and only HMRC's name and address match catches that.

## Cost of scanning a full crawl

Common Crawl's August 2026 announcement lists 100,000 WET files, 2.14 billion pages and 5.84 TiB of compressed WET text per crawl. I assume the crawl I used (`CC-MAIN-2026-43`) is similar. 100,000 files at my 21,500 pages per file gives 2.15 billion pages, which matches.

- **One process, my speed:** 139 hours (5.8 days).
- **A 32-core machine in parallel:** about 4.3 hours.
- **Download:** 5.84 TiB takes about 14 hours at 1 Gbit/s and about 6 days at 100 Mbit/s. On a laptop the network is the limit, in the cloud it is not.
- **Cost (my assumption: about $1.50 per hour for a 32-core machine, and no fee for reading the data inside the same cloud region):** roughly $10 to a few tens of dollars per crawl, well under one cent per candidate. Scanning is not the expensive part.

## Coverage

- **Extrapolation:** 371 companies in 243 files gives about 150,000 candidate companies in one full crawl. That is about 2.7% of the 5.7 million companies in my data, or about 7% of the roughly 2.18 million VAT registrations. It is an upper bound, because the same company appears in many files, some candidates are wrong, and my 243 files are not a random draw. These are candidates, not verified numbers, so the real figure is lower.
- **For the customer:** 40,000 suppliers with about 26,700 missing a VAT number. At 2.7%, a crawl reaches about 700 of them. A crawl alone cannot deliver two thirds.
- **What this route cannot reach:** companies with no website, sites missing from the crawl (small businesses are probably underrepresented, which I did not test), and VAT numbers that only appear in PDFs, invoices or behind a login.

## How I would raise coverage

1. **Crawl targeted pages instead of random ones.** Veridion already has company websites. Join them to Companies House and fetch only the legal pages (terms, privacy, contact, about, footer) of those sites. This removes the problem that stopped my company-by-company attempt (no website for each company). It needs a polite crawler and proxies to avoid blocks, and I have not tested it.
2. **Scan more crawls** (there are about 12 a year), with diminishing returns because the same sites repeat.
3. **Other sources I did not test:** public procurement notices, marketplace seller profiles (check their terms first), and commercial data.

## The HMRC API

The API would automate the verification step, which I did by hand. It needs production access, which requires an organisation with a registration identifier, a privacy policy, terms and conditions, and a breach process. I could not meet that as an individual, and a company can. I do not know the rate limit, so the time to verify is the number of candidates divided by the allowed requests per second (to be checked in the documentation). Without the API, at an assumed one minute per check, 150,000 candidates would take about 2,500 hours.

## Rough cost per company

These are assumptions. Only the speed and the yield are measured.

- **Scanning:** well under one cent per candidate (above).
- **Verification through the API:** I assumed there is no per-call fee but did not confirm it. Engineering and compliance work are the real cost.
- **Human review of ambiguous or mismatching candidates:** at one minute and £15 per hour (assumed), about £0.25 per review. With 3.7% of candidates ambiguous, that is about £0.01 per company.
- **Targeted crawling with proxies:** not estimated. I expect it to be the largest cost.

## What breaks first

1. **Pairing the right VAT number with the right company.** 14 of 382 candidates were ambiguous, and group companies and directory pages share numbers. Storing each VAT number only once also hides cases where one number is shown for several companies.
2. **Candidates are mostly lost before they are found:** most pages with both patterns give no pair (above), so the patterns and the 500-character window decide what is reachable at all.
3. **Bias in the crawl,** which favours large and old sites.
4. **HMRC rate limits and terms of use.**
5. **Stale data,** because companies register and deregister all the time.

## What I would monitor in production

- The false-positive rate each month, on a random sample verified through the API, with an alarm threshold.
- The share of ambiguous and mismatching candidates.
- Candidates per million pages. A sudden drop means the extractor or the crawl broke.
- The share of candidates failing the checksum (0.8% now). A rise means the pattern is catching other numbers.
- The deregistration rate, by re-verifying numbers regularly.
- Coverage and accuracy on the customer's known third (suppliers whose VAT number is already known). It is a partial reference set, though biased toward the easier suppliers.
- Cost per verified company and pages per second.

Source: [Common Crawl, August 2026 crawl archive](https://commoncrawl.org/blog/august-2026-crawl-archive-now-available)

---

# Debate topics

A few thoughts each, in my own words.

1. **Is this the most efficient method?** No. It is not the most efficient way to get VAT numbers, but it was the best option I found with a student's resources, and with more resources (more compute, targeted crawling of company websites) it could return a good number of VAT numbers.
2. **How to keep the data up to date:** run the scripts on each new Common Crawl crawl as it is released, and re-verify existing numbers regularly, because companies register and deregister all the time.
3. **Sources I would not use in a real product:**
   - Scripting HMRC's web checker, because it is made for people.
   - Marketplaces or directories whose terms forbid automated access or reuse.
   - Third-party company directories of unknown origin, because they copy each other's errors and I could not explain where a number came from.
   - Anything behind a login, and any leaked or purchased data without a clear legal basis.
   - Scraped details of sole traders without a lawful basis under UK GDPR.