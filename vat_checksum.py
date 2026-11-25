import re
from stdnum.gb import vat


def normalize(raw):
    """Keep only the digits. Accept 9 digits (or 12 with a branch suffix)."""
    digits = re.sub(r"\D", "", str(raw))
    return digits if len(digits) in (9, 12) else None


def is_valid_checksum(raw):
    """True if the number passes the UK VAT checksum. It says nothing about whether the number is registered."""
    digits = normalize(raw)
    return digits is not None and vat.is_valid(digits)