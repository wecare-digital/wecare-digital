"""Load canonical public brand assets for local verification and release embedding.

The release builder embeds these values so Lambda needs no filesystem or website request.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[4]
BRAND_LOGO = (ROOT / 'tools/customer-commerce/assets/logo.svg').read_text().strip()
BRAND_LOGO = BRAND_LOGO[BRAND_LOGO.index('<svg'):]
DIAL_COUNTRIES = [
    (code, country, [int(n) for n in re.findall(r'\d+', lengths)])
    for code, country, lengths in re.findall(
        r"\{ code: '([^']+)', country: '([^']+)', nationalDigits: \[([^\]]*)\] \}",
        (ROOT / 'src/lib/dialCodes.ts').read_text())
]
if not DIAL_COUNTRIES or DIAL_COUNTRIES[0][0] != '+91':
    raise ValueError('Canonical dial-code list unavailable')
