import gzip
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cc_scan import extract_pairs, files_to_scan, read_page


class FakeRecord:
    def __init__(self, content):
        self.content = io.BytesIO(content)

    def content_stream(self):
        return self.content


class CcScanTests(unittest.TestCase):
    def setUp(self):
        self.known = {"00000001", "00000002"}

    def test_extracts_nine_digit_vat(self):
        pairs, _, _ = extract_pairs(
            "Company registration number 00000001 VAT number GB 123 4567 89",
            self.known,
        )
        pair, = pairs
        self.assertEqual((pair["company"], pair["vat"]), ("00000001", "123456789"))
        self.assertEqual(pair["status"], "single_nearby_pair")

    def test_extracts_twelve_digit_branch_vat(self):
        pairs, _, _ = extract_pairs(
            "Company number 00000001 VAT registration number: 123456789 001",
            self.known,
        )
        pair, = pairs
        self.assertEqual(pair["vat"], "123456789001")

    def test_marks_multiple_nearby_companies_ambiguous(self):
        pairs, _, _ = extract_pairs(
            "Company number 00000001 VAT number 123456789 "
            "and company number 00000002",
            self.known,
        )
        self.assertEqual({pair["status"] for pair in pairs}, {"ambiguous"})
        self.assertEqual({pair["company"] for pair in pairs}, self.known)

    def test_does_not_pair_mentions_in_separate_paragraphs(self):
        pairs, _, _ = extract_pairs(
            "Company number 00000001\n\nVAT number 123456789",
            self.known,
        )
        self.assertEqual(list(pairs), [])

    def test_read_page_caps_memory_and_drains_record(self):
        record = FakeRecord(b"0123456789")
        text, truncated = read_page(record, 5)
        self.assertEqual(text, "01234")
        self.assertTrue(truncated)
        self.assertEqual(record.content.read(), b"")

    def test_list_mode_reads_only_requested_range(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wet.paths.gz"
            with gzip.open(path, "wt", encoding="utf-8") as paths_file:
                paths_file.writelines(f"crawl-data/file-{index}.warc.wet.gz\n" for index in range(5))

            paths = files_to_scan(
                SimpleNamespace(list=str(path), skip=2, n=2, files=[])
            )

        self.assertEqual(
            paths,
            [
                "https://data.commoncrawl.org/crawl-data/file-2.warc.wet.gz",
                "https://data.commoncrawl.org/crawl-data/file-3.warc.wet.gz",
            ],
        )


if __name__ == "__main__":
    unittest.main()
