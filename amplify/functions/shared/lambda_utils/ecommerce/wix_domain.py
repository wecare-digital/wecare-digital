"""Pure Wix catalog/order transforms. No I/O, no credentials, no AWS.

Phase 7.2's domain layer, lifted out of `wix-store/handler.py` verbatim.

WHY THIS IS A SEPARATE MODULE
-----------------------------
These 13 functions are the whole reason the handler was hard to reason about: ~270 lines
of pure shape-mapping between Wix's v3 payloads and ours, welded to a 1,700-line file that
needs a credential and three DynamoDB tables before it can be imported at all. Testing
`_money_amount` meant standing up the Wix integration.

The set was chosen by measurement, not by eye. A call-graph pass showed it is **closed** —
nothing here calls anything outside it — and that it needs exactly one module constant,
`SKU_PREFIX`. That is what made the move a single behaviour-preserving step rather than an
open-ended refactor.

Worth recording because it nearly went wrong: the first purity check used substring
matching on the AST dump and flagged `_normalize_v3_product`, `_simple_product_to_v3`,
`_extract_id` and `_s3_public_url` as impure, because their bodies contain the letters
`table`, `s3` and `resource` inside unrelated identifiers. A proper call-graph pass showed
they make no I/O call at all. Acting on the substring result would have left the two
biggest transforms — 112 and 55 lines — behind for no reason.

WHAT DELIBERATELY STAYED IN THE HANDLER
--------------------------------------
* `_wix_request`, `_load_wix_api_key`, `_credentials_disabled` — the adapter. Transport and
  credentials, which is exactly what a domain layer must not know about.
* `_hydrate_product_variants` — looks pure, calls `_wix_request`. Measured, not assumed.
* `_response` — reads a module-level `origin` global. Moving it would have carried that
  global into a shared module, which is the opposite of the point. The global's
  cross-request leak is fixed separately; threading `origin` through its 22 callers is the
  recorded remainder of 7.2.
* `_sync_products`, `_sync_orders`, `_backfill_order_ids` — the job layer.

EQUIVALENCE
-----------
Proven rather than asserted. `tests/test_wix_domain.py` replays 64 recorded input/output
cases captured from the pre-lift handler, including the awkward ones: empty dicts, `None`,
zero, a price as a string, unicode, and a 120-character name. A verbatim move that changes
behaviour is still a bug, and reading the diff cannot rule that out.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

# The only module constant the extracted set needs.
SKU_PREFIX = 'WD'


def _fields_suffix(fields: list) -> str:
    return '?' + '&'.join(f'fields={field}' for field in fields) if fields else ''
def _first_variant(product: dict) -> dict:
    return ((product.get('variantsInfo') or {}).get('variants') or [{}])[0] or {}
def _money_amount(value: Any) -> str:
    """Extract a money amount as a string, or '' when there isn't one.

    Returns '' rather than passing a non-numeric value through. It used to end in
    a bare `str(value)`, so `_money_amount('abc')` returned `'abc'` and that went
    into the `price` field the admin UI renders - a price reading "abc".

    '' is the right rejection value rather than a raise, because every caller
    already treats it as "no amount here, try the next source":

        amount = _money_amount(variant actualPrice)
        if not amount:
            amount = _money_amount(product actualPriceRange minValue)

    So validating actually repairs that fallback chain. Previously a junk value was
    truthy, which stopped the chain on the junk and never consulted the price
    range that may well have had a real number in it.
    """
    if isinstance(value, dict):
        value = value.get('amount', '')
    if value is None:
        return ''
    text = str(value).strip()
    if not text:
        return ''
    # Wix sends amounts as decimal strings ("1499", "1499.00"). Anything that is
    # not one is not an amount, whatever it is.
    try:
        Decimal(text)
    except (InvalidOperation, ValueError, ArithmeticError):
        return ''
    return text
def _read_only_variant_to_product_variant(variant: dict) -> dict:
    """Map Read-Only Variants V3 rows to the nested Products V3 variant shape."""
    row = dict(variant or {})
    return {
        'id': row.get('variantId') or row.get('id', ''),
        'visible': row.get('visible', True),
        'sku': row.get('sku', ''),
        'barcode': row.get('barcode', ''),
        'choices': row.get('optionChoices') or [],
        'price': row.get('price') or {},
        'inventoryStatus': row.get('inventoryStatus') or {},
    }
def _normalize_v3_product(product: dict) -> dict:
    """Expose a stable compatibility shape to the existing Amplify admin UI."""
    normalized = dict(product or {})
    variant_rows = (product.get('variantsInfo') or {}).get('variants') or []
    first = variant_rows[0] if variant_rows else {}
    amount = _money_amount(((first.get('price') or {}).get('actualPrice') or {}))
    if not amount:
        amount = _money_amount(((product.get('actualPriceRange') or {}).get('minValue') or {}))
    currency = product.get('currency') or 'INR'
    try:
        numeric_price = float(amount) if amount else 0.0
    except (TypeError, ValueError):
        numeric_price = 0.0

    media = product.get('media') or {}
    main_media = media.get('main') or {}
    media_items = ((media.get('itemsInfo') or {}).get('items') or [])
    inventory = product.get('inventory') or {}
    availability = str(inventory.get('availabilityStatus') or '').upper()
    variant_in_stock = any(
        (variant.get('inventoryStatus') or {}).get('inStock') is True
        for variant in variant_rows
    )
    in_stock = bool(inventory.get('inStock')) or availability in {
        'IN_STOCK', 'PARTIALLY_OUT_OF_STOCK'
    } or variant_in_stock

    categories = []
    for category in ((product.get('directCategoriesInfo') or {}).get('categories') or []):
        if isinstance(category, dict):
            categories.append({
                **category,
                '_id': category.get('id', ''),
                'name': category.get('name', ''),
            })

    compatible_options = []
    for option in product.get('options') or []:
        choices = []
        for choice in ((option.get('choicesSettings') or {}).get('choices') or []):
            choices.append({
                **choice,
                'description': choice.get('name', ''),
                'value': choice.get('name', ''),
            })
        compatible_options.append({
            **option,
            'choices': choices,
        })

    compatible_variants = []
    for variant in variant_rows:
        choices = {}
        for choice in variant.get('choices') or []:
            names = choice.get('optionChoiceNames') or {}
            option_name = names.get('optionName') or ''
            choice_name = names.get('choiceName') or ''
            if option_name:
                choices[option_name] = choice_name
        variant_amount = _money_amount(((variant.get('price') or {}).get('actualPrice') or {}))
        compatible_variants.append({
            **variant,
            'choices': choices,
            'variant': {
                **variant,
                'sku': variant.get('sku', ''),
                'priceData': {
                    'formatted': {
                        'price': f'{currency} {variant_amount}'.strip()
                    }
                },
            },
        })

    brand = product.get('brand') or {}
    ribbon = product.get('ribbon') or {}
    normalized.update({
        '_id': product.get('id', ''),
        'description': product.get('plainDescription') or product.get('description') or '',
        'price': numeric_price,
        'formattedPrice': f'{currency} {amount}'.strip() if amount else '',
        'currency': currency,
        'sku': first.get('sku', ''),
        'ribbon': ribbon.get('name', '') if isinstance(ribbon, dict) else ribbon,
        'brand': brand.get('name', '') if isinstance(brand, dict) else brand,
        'inStock': in_stock,
        'quantityInStock': inventory.get('quantity'),
        'productType': str(product.get('productType') or '').lower(),
        'mainMedia': main_media,
        'mediaItems': media_items,
        'collections': categories,
        'customTextFields': product.get('modifiers') or [],
        'productOptions': compatible_options,
        'variants': compatible_variants,
        'lastUpdated': product.get('updatedDate', ''),
        '_siteUrl': "https://wecare.digital/shop/"
                    if product.get('slug') else '',
        '_mainImage': main_media.get('url', '') if isinstance(main_media, dict) else '',
        '_mediaCount': len(media_items),
        '_priceSummary': {
            'amount': numeric_price,
            'currency': currency,
            'formatted': f'{currency} {amount}'.strip() if amount else '',
        },
        '_stockSummary': {
            'inStock': in_stock,
            'trackInventory': inventory.get('trackQuantity', False),
            'inventoryStatus': availability or 'UNKNOWN',
            'quantity': inventory.get('quantity'),
        },
    })
    return normalized
def _normalize_category(category: dict) -> dict:
    return {
        **(category or {}),
        '_id': (category or {}).get('id', ''),
        'mainMedia': (category or {}).get('image') or {},
    }
def _simple_product_to_v3(source: dict) -> dict:
    """Translate the legacy admin form payload into a Catalog V3 product."""
    src = dict(source or {})
    if src.get('variantsInfo'):
        product = {k: v for k, v in src.items()
                   if k not in {'imageUrls', 's3Keys', 'folder', 'priceData', 'stock', 'sku'}}
        product['productType'] = str(product.get('productType') or 'PHYSICAL').upper()
        return product

    product_type = str(src.get('productType') or 'PHYSICAL').upper()
    price_data = src.get('priceData') or {}
    price = price_data.get('price', src.get('price', 0))
    sku = str(src.get('sku') or '').strip()
    if not sku or not sku.startswith(SKU_PREFIX + '-'):
        sku = _generate_sku(src.get('name', ''))

    variant = {
        'visible': True,
        'sku': sku,
        'price': {'actualPrice': {'amount': str(price or 0)}},
    }
    if src.get('weight') not in (None, ''):
        try:
            variant['physicalProperties'] = {'weight': float(src.get('weight') or 0)}
        except (TypeError, ValueError):
            variant['physicalProperties'] = {}
    product = {
        'name': src.get('name', ''),
        'productType': product_type,
        'variantsInfo': {'variants': [variant]},
    }
    if product_type == 'PHYSICAL':
        product['physicalProperties'] = src.get('physicalProperties') or {}
        variant.setdefault('physicalProperties', {})

    if 'visible' in src:
        product['visible'] = bool(src.get('visible'))
    description = src.get('plainDescription', src.get('description'))
    if isinstance(description, str) and description:
        product['plainDescription'] = description
    if isinstance(src.get('brand'), dict):
        product['brand'] = src['brand']
    elif src.get('brand'):
        product['brand'] = {'name': str(src['brand'])}
    if isinstance(src.get('ribbon'), dict):
        product['ribbon'] = src['ribbon']
    elif src.get('ribbon'):
        product['ribbon'] = {'name': str(src['ribbon'])}
    if src.get('media'):
        product['media'] = src['media']
    if src.get('options'):
        product['options'] = src['options']
    if src.get('modifiers'):
        product['modifiers'] = src['modifiers']
    return product
def _generate_wd_order_number(order_date: str) -> str:
    """
    Generate a WD-ORD order number in the CURRENT public format.
    Format: WD-ORD-{8 symbols of order_keys.PUBLIC_ORDER_NUMBER_ALPHABET}
    Example: WD-ORD-K4M7PQR9

    THE OLD SHAPE IS NO LONGER MINTED. This used to emit
    `WD-ORD - {UUID8} - {DD-MM-YYYY} - {HH:MM:SS} - IST`, so the Wix sync/backfill was the
    last producer of the legacy form while our own checkout had already moved to
    `order_keys.reserve_public_order_number`. One system, one number shape.

    It is still RECOGNISED everywhere, and that is not optional: numbers already issued in
    the old shape are printed on receipts, sitting in customers' WhatsApp history and quoted
    to support. `order_keys.is_wd_order_number` accepts both legacy spellings and
    `order_keys.is_public_order_number` accepts the bare 12-character one, unchanged.

    `order_date` is kept in the signature because `order_keys.reserve_order_number` calls
    every generator with it and `wix-store` passes the Wix order's creation date - but the
    number no longer encodes a timestamp. Deliberately: a public number carrying the order's
    date leaks order volume to anyone holding two of them, which is the reasoning recorded on
    `order_keys.mint_public_order_number`. The date was never the uniqueness mechanism either;
    the conditional write under `ORDERNO#` is, and it is unchanged.

    Minted via `mint_public_order_number` rather than reimplemented, so the alphabet, the
    length and the CSPRNG source have exactly one definition.
    """
    from lambda_utils.ecommerce import order_keys
    return order_keys.mint_public_order_number()
def _generate_sku(product_name: str) -> str:
    """
    Auto-generate SKU in format WD-XX-XXXX.
    XX = first letter of first two words (split on spaces, dashes, em-dashes).
    XXXX = last 4 chars of base36 timestamp for uniqueness.
    """
    import re
    import time
    words = [w for w in re.split(r'[\s\-—–]+', product_name or '') if len(w) > 1]
    if len(words) >= 2:
        code = (words[0][0] + words[1][0]).upper()
    else:
        code = (product_name or 'XX')[:2].upper().ljust(2, 'X')
    suffix = _base36(int(time.time() * 1000))[-4:].upper()
    return f'{SKU_PREFIX}-{code}-{suffix}'
def _base36(num: int) -> str:
    """Convert integer to base36 string."""
    chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    if num == 0:
        return '0'
    result = ''
    while num:
        result = chars[num % 36] + result
        num //= 36
    return result
def _extract_id(path: str, resource: str) -> Optional[str]:
    """Extract resource ID from path like /orders/abc123 or /orders/abc123/fulfillments."""
    parts = path.rstrip('/').split('/')
    try:
        idx = parts.index(resource)
        if idx + 1 < len(parts) and parts[idx + 1]:
            return parts[idx + 1]
    except ValueError:
        pass
    return None
def _get_main_media(product: dict) -> str:
    media = product.get('media') or {}
    v3_main = media.get('main') or {}
    if isinstance(v3_main, dict) and v3_main.get('url'):
        return v3_main['url']
    return media.get('mainMedia', {}).get('image', {}).get('url', '')
def _parse_body(event: dict) -> dict:
    """Parse request body from event."""
    body = event.get('body', '')
    if not body:
        return {}
    if isinstance(body, str):
        try:
            return json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return {}
    return body
