import os
import re
import time
import requests
from dotenv import load_dotenv

load_dotenv()

BASE = "https://test-api.service.hmrc.gov.uk"  # sandbox; for production: https://api.service.hmrc.gov.uk

_token = None
_token_expires_at = 0


def get_token():
    """Return a valid access token; reuse it until it expires."""
    global _token, _token_expires_at
    if _token and time.time() < _token_expires_at - 60:
        return _token

    print("Requesting a new access token from HMRC...")
    r = requests.post(
        f"{BASE}/oauth/token",
        data={
            "client_id": os.environ["HMRC_CLIENT_ID"],
            "client_secret": os.environ["HMRC_CLIENT_SECRET"],
            "grant_type": "client_credentials",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    _token = data["access_token"]
    _token_expires_at = time.time() + data.get("expires_in", 3600)
    print(f"Token obtained (expires in {data.get('expires_in', 3600)} seconds).")
    return _token


def normalize_vrn(raw):
    """Keep digits only (strips GB, spaces, dashes). Accepts 9 or 12 digits."""
    digits = re.sub(r"\D", "", str(raw))
    return digits if len(digits) in (9, 12) else None


def lookup(raw_vrn):
    """Return (status_code, json). Returns (None, {...}) if the format is invalid."""
    vrn = normalize_vrn(raw_vrn)
    if vrn is None:
        return None, {"error": f"Invalid format, HMRC was not called: {raw_vrn!r}"}

    print(f"Looking up VAT number {vrn}...")
    r = requests.get(
        f"{BASE}/organisations/vat/check-vat-number/lookup/{vrn}",
        headers={
            "Accept": "application/vnd.hmrc.2.0+json",
            "Authorization": f"Bearer {get_token()}",
        },
        timeout=30,
    )
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text}
    return r.status_code, body


def describe(status, body):
    """Print a human-readable summary of a lookup result."""
    if status is None:
        print("Result: skipped (invalid format).")
    elif status == 200:
        print("Result: VAT number is registered.")
    elif status == 404:
        print("Result: VAT number does not match a registered company.")
    elif status == 400:
        print("Result: HMRC rejected the request (bad format).")
    else:
        print(f"Result: unexpected status {status}.")


if __name__ == "__main__":
    # Replace with a test VRN from the sandbox documentation
    # ("Check a UK VAT number 2.0" -> Testing / Sandbox data section).
    TEST_VRN = "123456789"

    status, body = lookup(TEST_VRN)
    print("Status:", status)
    print("Response:", body)
    describe(status, body)