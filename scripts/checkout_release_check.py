"""Read-only customer release gate. No OTP sends, payment requests or authenticated reads.

Run after a build with --export-dir out, or against production with --live.
Checks real rendered anchors rather than occurrences in serialized JavaScript.
The live route matrix separately checks www, retired access and wildcard hosts.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
# '/shop/' was removed on 2026-10-04: the owner withdrew the catalogue index, so there is no
# out/shop/index.html to read and a probe for one raises, which `main()` turns into a failure row
# and exits 1 - AFTER `next build` has already succeeded, failing the Amplify build for a page that
# was deliberately deleted. NOTE `paths()` BELOW UNIONS TWO SOURCES: this tuple and
# config/public-pages.json, whose own '/shop' entry is turned straight back into '/shop/' by the
# rstrip-then-append. Cleaning only one of the two leaves the page in the probe set, so both were
# cleaned together.
CUSTOMER_PAGES = ('/cart/', '/account/sign-in/', '/orders/',
                  '/checkout/status/', '/checkout/success/')
RETIRED_HOSTS = {'store.wecare.digital', 'shop.wecare.digital', 'xout.wecare.digital',
                 'bnbclub.in', 'legalchamp.in', 'nofault.in', 'ritualguru.in', 'swdhya.in'}


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        if tag == 'a':
            self.links.append(dict(attrs).get('href', ''))


def check_html(path, html):
    page = Page()
    page.feed(html)
    failures = [f'{path}: missing {tag}' for tag in ('header', 'footer', 'h1', 'main')
                if tag not in page.tags]
    for href in page.links:
        parsed = urlsplit(href)
        if parsed.hostname in RETIRED_HOSTS:
            failures.append(f'{path}: stale destination {href}')
        if (parsed.hostname in (None, 'wecare.digital', 'www.wecare.digital')
                and (parsed.path.startswith('/workspace') or parsed.path.rstrip('/') == '/access')):
            failures.append(f'{path}: public staff link {href}')
    if '/cart/' not in page.links:
        failures.append(f'{path}: Shopping Bag destination missing')
    if not any(urlsplit(href).path == '/r/wa' for href in page.links):
        failures.append(f'{path}: default WhatsApp widget missing')
    return failures


def paths():
    catalogue = json.loads((ROOT / 'config/public-pages.json').read_text())
    public = [entry['path'].rstrip('/') + '/' for entry in catalogue['pages']
              if not entry['path'].startswith('/blog/')]
    return sorted(set(public + list(CUSTOMER_PAGES)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--live', action='store_true')
    group.add_argument('--export-dir', type=Path)
    args = parser.parse_args()

    def check(path):
        try:
            if args.live:
                request = Request('https://wecare.digital' + path,
                                  headers={'User-Agent': 'WECARE-customer-release-check/1'})
                with urlopen(request, timeout=30) as response:
                    if response.status != 200:
                        return [f'{path}: HTTP {response.status}']
                    html = response.read().decode('utf-8')
            else:
                html = (args.export_dir / path.lstrip('/') / 'index.html').read_text()
            return check_html(path, html)
        except Exception as error:
            return [f'{path}: {type(error).__name__}']

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        failures = [failure for result in pool.map(check, paths()) for failure in result]
    print(json.dumps({'pages': len(paths()), 'failures': failures}, indent=2))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
