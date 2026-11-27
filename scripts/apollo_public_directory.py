#!/usr/bin/env python3
"""Operator-only, provider-approved public directory link discovery.

This is NOT the IC service login, slot inventory, patient lookup, or booking API.
Apollo's public-site disclaimer restricts commercial reuse and retention.
Run only with explicit Apollo authorization for this scope. No crawl by default;
no cookies, credentials, forms, retries, pagination, profile downloads or writes.
"""
from __future__ import annotations

import argparse
import datetime as dt
from html.parser import HTMLParser
import json
import re
import sys
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import URLError
from urllib.robotparser import RobotFileParser

ORIGIN = 'https://www.apollohospitals.com'
SOURCES = {'hospitals': ORIGIN + '/facilities/hospitals', 'doctors': ORIGIN + '/doctors'}
AGENT = 'WECARE-Arogya-Directory/1.0'
MAX_BYTES = 4 * 1024 * 1024
MAX_LINKS = 200
ROUTES = {
    'hospitals': re.compile(r'/hospitals/[a-z0-9-]+/?\Z'),
    'doctors': re.compile(r'/doctors/([a-z0-9-]+)/([a-z0-9-]+)/(dr-[a-z0-9-]+)/?\Z'),
}


class DirectoryUnavailable(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DirectoryUnavailable('Directory redirect refused')


def fetch(url, *, max_bytes, media):
    if url not in (*SOURCES.values(), ORIGIN + '/robots.txt'):
        raise DirectoryUnavailable('Directory source refused')
    req = Request(url, headers={'User-Agent': AGENT, 'Accept': media}, method='GET')
    with build_opener(NoRedirect()).open(req, timeout=10) as response:
        if response.status != 200 or response.headers.get_content_type() != media:
            raise DirectoryUnavailable('Unexpected directory response')
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise DirectoryUnavailable('Directory response exceeded size limit')
        return raw.decode(response.headers.get_content_charset() or 'utf-8', errors='strict')


class DirectoryLinks(HTMLParser):
    def __init__(self, kind):
        super().__init__(convert_charrefs=True)
        self.kind = kind
        self.href = None
        self.text = []
        self.links = {}
        self.truncated = False
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'template'):
            self.ignored += 1
        if self.ignored:
            return
        if tag == 'a':
            self.href = dict(attrs).get('href')
            self.text = []

    def handle_data(self, data):
        if self.href is not None and not self.ignored:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'template'):
            self.ignored = max(0, self.ignored - 1)
        if self.ignored or tag != 'a' or self.href is None:
            return
        href, label = self.href, ' '.join(' '.join(self.text).split())
        self.href, self.text = None, []
        # No arbitrary input URLs, credentials, query strings, fragments, non-
        # canonical paths, embedded userinfo, or off-origin link destinations.
        try:
            url = urlsplit(urljoin(SOURCES[self.kind], href))
        except ValueError:
            return
        if url.scheme != 'https' or url.netloc != 'www.apollohospitals.com' or url.query or url.fragment:
            return
        match = ROUTES[self.kind].fullmatch(url.path)
        if not match or not 3 <= len(label) <= 160 or any(ord(c) < 32 or ord(c) == 127 for c in label):
            return
        if self.kind == 'doctors' and not re.match(r'^Dr\.?\s', label, re.I):
            return
        if self.kind == 'hospitals' and not re.match(r'^(Apollo|Indraprastha Apollo|Nirali)\b', label, re.I):
            return
        canonical = ORIGIN + url.path.rstrip('/')
        if canonical in self.links:
            return
        if len(self.links) >= MAX_LINKS:
            self.truncated = True
            return
        item = {'label': label, 'url': canonical}
        if self.kind == 'doctors':
            item.update({'specialitySlug': match.group(1), 'citySlug': match.group(2)})
        self.links[canonical] = item


def parse_directory(kind, html):
    if kind not in SOURCES or not isinstance(html, str):
        raise DirectoryUnavailable('Directory input refused')
    parser = DirectoryLinks(kind)
    parser.feed(html)
    parser.close()
    if not parser.links:
        raise DirectoryUnavailable('Directory layout unrecognized or empty')
    return list(parser.links.values()), parser.truncated


def discover(kind, *, approved=False, get=fetch):
    if approved is not True or kind not in SOURCES:
        raise DirectoryUnavailable('Apollo-approved directory access required')
    robots = get(ORIGIN + '/robots.txt', max_bytes=256 * 1024, media='text/plain')
    policy = RobotFileParser()
    policy.parse(robots.splitlines())
    if not robots.strip() or not re.search(r'(?im)^\s*user-agent\s*:', robots):
        raise DirectoryUnavailable('Directory crawl policy unavailable')
    # Honor the declared user agent and robots.txt. A provider's affirmative
    # permission is separate from a robots allowance.
    if not policy.can_fetch(AGENT, SOURCES[kind]):
        raise DirectoryUnavailable('Directory crawl disallowed by robots.txt')
    html = get(SOURCES[kind], max_bytes=MAX_BYTES, media='text/html')
    items, truncated = parse_directory(kind, html)
    return {'source': SOURCES[kind], 'observedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
            'kind': kind, 'directoryOnly': True, 'coverage': 'first-page-only',
            'truncated': truncated, 'items': items}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kind', required=True, choices=list(SOURCES))
    p.add_argument('--approved-by-provider', action='store_true',
                   help='Confirm written Apollo authorization for this directory use and retention')
    args = p.parse_args()
    try:
        print(json.dumps(discover(args.kind, approved=args.approved_by_provider), ensure_ascii=True))
    except (DirectoryUnavailable, URLError, TimeoutError, UnicodeError, ValueError):
        print('Directory discovery unavailable or not authorized. Open the official public directory instead.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
