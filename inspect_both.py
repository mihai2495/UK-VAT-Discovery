import sys
from warcio.archiveiterator import ArchiveIterator
from cc_scan import COMPANY_RE, VAT_RE, norm_company
from vat_checksum import is_valid_checksum

path = sys.argv[1]
with open(path, "rb") as f:
    for rec in ArchiveIterator(f):
        if rec.rec_type != "conversion":
            continue
        text = rec.content_stream().read().decode("utf-8", errors="ignore")
        c, v = COMPANY_RE.search(text), VAT_RE.search(text)
        if c and v:
            vat = v.group(1).replace(" ", "")
            print(rec.rec_headers.get_header("WARC-Target-URI"))
            print("  company:", norm_company(c.group(1)), "| VAT:", vat, "| checksum ok:", is_valid_checksum(vat))