"""Read-only customer release gate. No OTP sends, payment requests or authenticated reads.

Run after a build with --export-dir out, or against production with --live.
Checks real rendered anchors rather than occurrences in serialized JavaScript.
The live route matrix separately checks www, retired access and wildcard hosts.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
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
# /auth is intentionally NOT a static-export page. Amplify rewrites it to the
# customer-commerce authorization backend, and scripts/probe_url_host_matrix.py
# owns its live contract. Requiring out/auth/index.html would make every valid
# static production build fail.
CUSTOMER_PAGES = ('/checkout/', '/orders/',
                  '/checkout/status/', '/checkout/success/')
RETIRED_HOSTS = {'bnbclub.in', 'legalchamp.in', 'nofault.in', 'ritualguru.in', 'swdhya.in'}


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
        if (parsed.hostname in (None, 'wecare.digital')
                and (parsed.path.startswith('/workspace') or parsed.path.rstrip('/') == '/access')):
            failures.append(f'{path}: public staff link {href}')
    if '/checkout/' not in page.links:
        failures.append(f'{path}: Checkout destination missing')
    # The retired /cart/ URL must not appear in customer-facing links.
    if any(urlsplit(href).path.rstrip('/') == '/cart' for href in page.links):
        failures.append(f'{path}: legacy cart destination linked')
    if any(urlsplit(href).path.rstrip('/') == '/checkout/whatsapp' for href in page.links):
        failures.append(f'{path}: removed WhatsApp checkout page linked')
    if not any(urlsplit(href).path == '/r/wa' for href in page.links):
        failures.append(f'{path}: default WhatsApp widget missing')
    return failures


def check_checkout_basket_source():
    """Canonical checkout must keep the owner-scoped one-shot basket handoff."""
    failures = []
    if (ROOT / 'src/pages/cart.tsx').exists():
        failures.append('cart: retired standalone page reappeared')
    body = (ROOT / 'src/components/cart/CartPage.tsx').read_text(encoding='utf-8')
    if ('basketTokenFromUrl()' not in body
            or 'rememberBasketToken( token );' not in body
            or 'claimBasket( session.accessToken, token )' not in body
            or "const SIGN_IN_PATH = '/auth?return=/checkout/';" not in body):
        failures.append('checkout: secure basket claim/sign-in handoff was lost')
    return failures


def check_orders_history_source():
    """Production export invariant: no customer expandable order receipts.

    This is part of the existing release checker, not a revived offline test
    runner or CI workflow. It reads source only; no customer or AWS calls.
    Staff Orders detail screens and internal invoice records are unaffected.
    """
    failures = []

    def source(relative):
        try:
            return (ROOT / relative).read_text(encoding='utf-8')
        except OSError:
            failures.append('orders: missing source ' + relative)
            return ''

    orders = source('src/components/orders/OrdersPage.tsx')
    route = source('src/pages/orders.tsx')
    page_path = source('src/lib/orderPage.ts')
    checkout_status = source('src/pages/checkout/status.tsx')
    actions = source('src/components/orders/OrderActionsMenu.tsx')
    checkout_backend = source('amplify/functions/ecommerce/checkout/handler.py')

    component_dir = ROOT / 'src/components/orders'
    if (ROOT / 'src/pages/orders').exists():
        failures.append('orders: alternate individual-order route is forbidden')
    if component_dir.exists():
        old_details = [p.name for p in component_dir.iterdir()
                       if p.name.lower().startswith(('orderdetail', 'orderreceipt'))]
        if old_details:
            failures.append('orders: deleted order-detail component returned: ' +
                            ', '.join(sorted(old_details)))

    jsx = orders.split('<style jsx>{`')[0]
    thead = re.search(r'<thead>[\s\S]*?</thead>', jsx)
    headings = re.findall(r'<th\b[^>]*>([^<]*)</th>', thead.group(0)) if thead else []
    if [x.strip() for x in headings] != ['Order #', 'Date', 'Amount', 'Status', 'Invoice']:
        failures.append('orders: history must have only five column headings')
    if not re.search(r'<tr\s+key=\{\s*rowId\s*\}\s+className="ord-tr"\s*>', jsx):
        failures.append('orders: history row must be static, never clickable or expandable')
    if not re.search(r'<span\s+className="ord-ordno"(?=\s|>)', jsx):
        failures.append('orders: static order-number label is missing')
    if '<OrderActionsMenu' not in jsx or 'MY_INVOICE_URL' not in jsx:
        failures.append('orders: invoice download and More actions must remain available')

    forbidden = (
        ('detail component or expand state',
         r'\b(?:OrderDetail|OrderReceipt|expandedOrder|setExpandedOrder|selectedOrder|setSelectedOrder|setExpanded|openOrderDetails|toggleOrderDetails)\b'),
        ('itemized/order-detail data in customer history',
         r'\b(?:lineItems|deliveryAddress|paymentReference|invoiceNumber|gstAmount)\b'),
        ('click handler on order table row or cell', r'<(?:tr|th|td)\b[^>]*\bonClick\s*='),
        ('inline expandable receipt or dialog', r'<(?:details|dialog)\b|\baria-expanded\s*='),
        ('retired order-detail checkout action', r'\baction\s*:\s*[\'"]order[\'"]'),
    )
    for label, pattern in forbidden:
        if re.search(pattern, jsx, flags=re.IGNORECASE if label == 'inline expandable receipt or dialog' else 0):
            failures.append('orders: forbidden ' + label)

    if ("params.has( 'o' )" not in jsx or
            "window.history.replaceState( window.history.state, '', '/orders/' )" not in jsx or
            "sessionStorage.removeItem( 'wecare.pendingOrderView' )" not in jsx):
        failures.append('orders: stale ?o= links and old selectors must be discarded')
    if ("import OrdersPage from '../components/orders/OrdersPage'" not in route or
            'export default OrdersPage;' not in route):
        failures.append('orders: /orders must use the single history component')

    helper = re.search(r'export function orderPagePath\s*\([^)]*\)\s*:\s*string\s*\{([^}]*)\}', page_path)
    if not helper or not re.fullmatch(r"\s*return\s+['\"]/orders/['\"];\s*", helper.group(1)):
        failures.append('orders: links must resolve only to /orders/')
    if (not re.search(r'router\.replace\(\s*orderPagePath\(', checkout_status) or
            not re.search(r'href=\{\s*orderPagePath\(', checkout_status) or
            re.search(r"sessionStorage\.setItem\(\s*['\"]wecare\.pendingOrderView", checkout_status) or
            re.search(r'[?&]o=', checkout_status)):
        failures.append('orders: checkout must return to history without selecting a receipt')
    if re.search(r'\bOrderDetail\b|/orders/\$\{|[?&]o=', actions):
        failures.append('orders: More actions must not open individual-order details')

    retired = checkout_backend.find('if action == "order":')
    refused = checkout_backend.find(
        'return _hardened(cors_response(410, {"error": "ORDER_DETAILS_RETIRED"}, origin))',
        retired)
    creates = checkout_backend.find('if action == "create":', retired)
    if (retired < 0 or refused < retired or creates <= refused or
            re.search(r'^\s*def _order_(?:detail|view|lines)\b', checkout_backend, re.MULTILINE)):
        failures.append('orders: retired backend action must return 410 before payment create')

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

    # Source-only Orders check runs for every Amplify export build, before deploy.
    # --live validates public HTML only and cannot attest an authenticated UI.
    failures = (check_orders_history_source() + check_checkout_basket_source()
                if args.export_dir else [])
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        failures.extend(failure for result in pool.map(check, paths()) for failure in result)
    print(json.dumps({'pages': len(paths()), 'failures': failures}, indent=2))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
