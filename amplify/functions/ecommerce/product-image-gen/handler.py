"""
Product Image Generator — WECARE.DIGITAL

Auto-generates branded 3000x3000 PNG product card images for the AWS-native catalog.
Uses Pillow (PIL) for high-quality raster image generation.

Product image specs:
  - 1:1 square ratio, 3000x3000px for zoom quality
  - PNG format
  - Max 8MB

Design:
  - Dark gradient background (brand navy)
  - Country flag from flagcdn.com (free CDN)
  - Visa type badge with accent color
  - Country name, tagline, price
  - WECARE.DIGITAL branding + BNB CLUB ribbon

Routes:
  POST /generate-product-image   — Generate PNG, upload to S3, optionally attach to native product
  GET  /preview-product-image    — Return SVG preview (lightweight browser preview)

Lambda Layer: Klayers-p312-Pillow:10 (Pillow 12.1.1)
"""

import os
import json
import logging
import uuid
import urllib.request
import urllib.error
import io
import base64
from datetime import datetime, timezone
from typing import Dict, Any, Tuple

import boto3
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.middleware import require_auth

from lambda_utils.logging import get_logger
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated

logger = get_logger(__name__)

# Read from the environment, and default to the bucket that actually exists.
#
# This was the literal 'app.wecare.digital' until 2026-09-28. That bucket has been
# deleted, so both put_object calls below would raise NoSuchBucket and the
# publicUrl built from it would 404. Written as an env lookup rather than a new
# literal so the next bucket move is a configuration change, not a code deploy.
S3_BUCKET = os.environ.get('S3_BUCKET', media_paths.BUCKET)
# The PUBLIC host, deliberately separate from the bucket name. Both publicUrl sites
# below built the URL from S3_BUCKET, which was only ever valid because the old
# bucket was named app.wecare.digital and so doubled as a hostname.
CDN_DOMAIN = os.environ.get('CDN_DOMAIN', media_paths.CDN_DOMAIN)

PRODUCTS_TABLE = os.environ.get('PRODUCTS_TABLE', 'stack-wecare-digital-ProductsTable')
S3_PREFIX = media_paths.public('stack/store/products')

# Image dimensions (3000x3000, large enough for storefront zoom)
IMG_SIZE = 3000

# Country code → name mapping (ISO 3166-1 alpha-2)
COUNTRIES = {
    'fr': 'France', 'de': 'Germany', 'it': 'Italy', 'es': 'Spain',
    'gb': 'United Kingdom', 'us': 'United States', 'ca': 'Canada',
    'au': 'Australia', 'jp': 'Japan', 'sg': 'Singapore', 'ae': 'UAE',
    'th': 'Thailand', 'my': 'Malaysia', 'tr': 'Turkey', 'gr': 'Greece',
    'pt': 'Portugal', 'nl': 'Netherlands', 'be': 'Belgium', 'at': 'Austria',
    'ch': 'Switzerland', 'se': 'Sweden', 'no': 'Norway', 'dk': 'Denmark',
    'fi': 'Finland', 'ie': 'Ireland', 'nz': 'New Zealand', 'za': 'South Africa',
    'kr': 'South Korea', 'cn': 'China', 'vn': 'Vietnam', 'id': 'Indonesia',
    'ph': 'Philippines', 'lk': 'Sri Lanka', 'np': 'Nepal', 'mm': 'Myanmar',
    'kh': 'Cambodia', 'cz': 'Czech Republic', 'pl': 'Poland', 'hu': 'Hungary',
    'hr': 'Croatia', 'bg': 'Bulgaria', 'ro': 'Romania', 'ee': 'Estonia',
    'lv': 'Latvia', 'lt': 'Lithuania', 'si': 'Slovenia', 'sk': 'Slovakia',
    'mt': 'Malta', 'cy': 'Cyprus', 'is': 'Iceland', 'lu': 'Luxembourg',
    'schengen': 'Schengen Zone',
}

VISA_TYPES = {
    'tourist':    {'label': 'TOURIST VISA',    'color': (0, 201, 167)},    # teal
    'schengen':   {'label': 'SCHENGEN VISA',   'color': (74, 144, 217)},   # blue
    'business':   {'label': 'BUSINESS VISA',   'color': (245, 166, 35)},   # gold
    'conference': {'label': 'CONFERENCE VISA', 'color': (245, 166, 35)},   # gold
    'transit':    {'label': 'TRANSIT VISA',    'color': (155, 89, 182)},    # purple
    'student':    {'label': 'STUDENT VISA',    'color': (231, 76, 60)},     # red
    'work':       {'label': 'WORK VISA',       'color': (230, 126, 34)},    # orange
    'medical':    {'label': 'MEDICAL VISA',    'color': (26, 188, 156)},    # green
}

# Brand colors
BG_TOP = (10, 22, 40)       # #0A1628
BG_BOTTOM = (26, 39, 68)    # #1A2744
WHITE = (255, 255, 255)
WHITE_DIM = (255, 255, 255, 150)
WHITE_FAINT = (255, 255, 255, 60)

# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler."""
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)
    try:
        http_method = event.get('httpMethod', event.get('requestContext', {}).get('http', {}).get('method', 'GET'))
        path = event.get('path', event.get('rawPath', '/'))
        params = event.get('queryStringParameters', {}) or {}

        if http_method == 'OPTIONS':
            return _resp(200, {'ok': True})

        # ── Authenticate API Gateway callers ──
        # All three routes were public with no handler check, and image generation
        # costs money per call, so an anonymous caller could run up spend. Note the
        # Retired provider credentials are not route credentials. This native endpoint
        # authenticates the caller directly before any image-generation work.
        auth_failure = require_auth(event)
        if auth_failure is not None:
            return auth_failure

        if http_method == 'POST' and '/generate-product-image' in path:
            body = json.loads(event.get('body', '{}') or '{}')
            return _generate_and_upload(body, request_id)

        if http_method == 'POST' and '/convert-flag' in path:
            body = json.loads(event.get('body', '{}') or '{}')
            return _convert_flag_to_png(body, request_id)

        if '/preview-product-image' in path:
            return _preview_svg(params, request_id)

        return _resp(404, {'error': 'Not found', 'path': path})
    except (json.JSONDecodeError, TypeError, ValueError):
        return _resp(400, {'error': 'Invalid JSON in request body'})
    except Exception as e:
        logger.error(json.dumps({'action': 'image_gen_error', 'error': str(e), 'requestId': request_id}))
        return _resp(500, {'error': str(e), 'requestId': request_id})


# ===================================================================
# PNG IMAGE GENERATION (Pillow)
# ===================================================================

def _draw_gradient(img: Image.Image, top: Tuple, bottom: Tuple):
    """Draw a vertical gradient on the image."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for y in range(h):
        ratio = y / h
        r = int(top[0] + (bottom[0] - top[0]) * ratio)
        g = int(top[1] + (bottom[1] - top[1]) * ratio)
        b = int(top[2] + (bottom[2] - top[2]) * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


def _draw_rounded_rect(draw: ImageDraw.Draw, xy, radius, fill=None, outline=None, width=1):
    """Draw a rounded rectangle."""
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _fetch_flag(country_code: str, size: int = 640) -> Image.Image:
    """Download country flag from flagcdn.com and return as PIL Image."""
    cc = country_code.lower()
    if cc == 'schengen':
        cc = 'eu'
    url = f'https://flagcdn.com/w{size}/{cc}.png'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'WECARE-ImageGen/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return Image.open(io.BytesIO(resp.read())).convert('RGBA')
    except Exception as e:
        logger.warning(f'Flag fetch failed for {cc}: {e}')
        # Return a placeholder gray circle
        placeholder = Image.new('RGBA', (size, int(size * 0.66)), (100, 100, 100, 200))
        return placeholder


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Get a font. Lambda has DejaVu Sans available."""
    font_paths = [
        '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    for fp in font_paths:
        try:
            return ImageFont.truetype(fp, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _generate_png(country_code: str, visa_type: str, price: str = '',
                  custom_tagline: str = '', country_name: str = '') -> bytes:
    """
    Generate a 3000x3000 PNG product card image.
    Returns PNG bytes.
    """
    S = IMG_SIZE  # 3000
    cc = country_code.lower()
    vt = visa_type.lower()

    c_name = country_name or COUNTRIES.get(cc, cc.upper())
    v_info = VISA_TYPES.get(vt, {'label': f'{vt.upper()} VISA', 'color': (0, 201, 167)})
    v_label = v_info['label']
    v_color = v_info['color']
    v_color_alpha = v_color + (255,)
    tagline = custom_tagline or 'We optimize for approval, not just submission'

    # Create base image with gradient
    img = Image.new('RGB', (S, S))
    _draw_gradient(img, BG_TOP, BG_BOTTOM)

    # Convert to RGBA for compositing
    img = img.convert('RGBA')
    overlay = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # ---- Accent glow (radial, centered at flag area) ----
    glow = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    cx, cy = S // 2, int(S * 0.38)
    for r in range(800, 0, -2):
        alpha = int(25 * (1 - r / 800))
        glow_draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                          fill=v_color + (alpha,))
    img = Image.alpha_composite(img, glow)

    draw = ImageDraw.Draw(img)

    # ---- Top accent line ----
    draw.rectangle([0, 0, S, 12], fill=v_color_alpha)

    # ---- WECARE.DIGITAL logo (top-left) ----
    font_logo = _get_font(60, bold=True)
    draw.text((150, 150), 'WECARE.DIGITAL', fill=WHITE, font=font_logo)

    # ---- BNB CLUB ribbon (top-right) ----
    ribbon_w, ribbon_h = 660, 132
    ribbon_x = S - ribbon_w - 120
    ribbon_y = 120
    _draw_rounded_rect(draw, [ribbon_x, ribbon_y, ribbon_x + ribbon_w, ribbon_y + ribbon_h],
                       radius=66, fill=v_color_alpha)
    font_ribbon = _get_font(54, bold=True)
    bbox = draw.textbbox((0, 0), 'BNB CLUB', font=font_ribbon)
    tw = bbox[2] - bbox[0]
    draw.text((ribbon_x + (ribbon_w - tw) // 2, ribbon_y + 30), 'BNB CLUB',
              fill=WHITE, font=font_ribbon)

    # ---- Divider line ----
    draw.line([(150, 310), (S - 150, 310)], fill=(255, 255, 255, 20), width=3)

    # ---- Country flag (circular, centered) ----
    flag_img = _fetch_flag(cc, 640)
    flag_size = 720  # diameter of circular flag
    flag_center_y = int(S * 0.38)

    # Create circular mask
    mask = Image.new('L', (flag_size, flag_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse([0, 0, flag_size, flag_size], fill=255)

    # Resize flag to fill circle
    flag_resized = flag_img.resize((flag_size, flag_size), Image.LANCZOS)

    # Draw circle background (subtle glow ring)
    ring_size = flag_size + 30
    ring_x = (S - ring_size) // 2
    ring_y = flag_center_y - ring_size // 2
    draw.ellipse([ring_x, ring_y, ring_x + ring_size, ring_y + ring_size],
                 fill=(255, 255, 255, 15), outline=v_color + (100,), width=6)

    # Paste flag with circular mask
    flag_x = (S - flag_size) // 2
    flag_y = flag_center_y - flag_size // 2
    img.paste(flag_resized, (flag_x, flag_y), mask)

    # Redraw on composited image
    draw = ImageDraw.Draw(img)

    # ---- Visa type badge ----
    badge_w, badge_h = 900, 138
    badge_x = (S - badge_w) // 2
    badge_y = flag_center_y + flag_size // 2 + 100
    _draw_rounded_rect(draw, [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
                       radius=69, fill=v_color + (40,), outline=v_color + (120,), width=5)
    font_badge = _get_font(60, bold=True)
    bbox = draw.textbbox((0, 0), v_label, font=font_badge)
    tw = bbox[2] - bbox[0]
    draw.text(((S - tw) // 2, badge_y + 30), v_label, fill=v_color_alpha, font=font_badge)

    # ---- Country name ----
    font_country = _get_font(156, bold=True)
    country_upper = c_name.upper()
    bbox = draw.textbbox((0, 0), country_upper, font=font_country)
    tw = bbox[2] - bbox[0]
    country_y = badge_y + badge_h + 80
    draw.text(((S - tw) // 2, country_y), country_upper, fill=WHITE, font=font_country)

    # ---- Tagline ----
    font_tagline = _get_font(48)
    tagline_text = f'"{tagline}"'
    bbox = draw.textbbox((0, 0), tagline_text, font=font_tagline)
    tw = bbox[2] - bbox[0]
    tagline_y = country_y + 200
    draw.text(((S - tw) // 2, tagline_y), tagline_text, fill=(255, 255, 255, 130), font=font_tagline)

    # ---- Price ----
    if price:
        font_price = _get_font(84, bold=True)
        price_text = f'From {price}'
        bbox = draw.textbbox((0, 0), price_text, font=font_price)
        tw = bbox[2] - bbox[0]
        price_y = tagline_y + 120
        draw.text(((S - tw) // 2, price_y), price_text, fill=v_color_alpha, font=font_price)

    # ---- Bottom bar ----
    draw.rectangle([0, S - 240, S, S], fill=(255, 255, 255, 8))
    draw.line([(0, S - 240), (S, S - 240)], fill=(255, 255, 255, 20), width=3)

    # ---- Bottom contact ----
    font_contact = _get_font(42)
    contact = 'WhatsApp: +91 93309 94400  |  visa@wecare.digital'
    bbox = draw.textbbox((0, 0), contact, font=font_contact)
    tw = bbox[2] - bbox[0]
    draw.text(((S - tw) // 2, S - 160), contact, fill=(255, 255, 255, 80), font=font_contact)

    # ---- Bottom accent line ----
    draw.rectangle([0, S - 12, S, S], fill=v_color_alpha)

    # Convert to RGB for PNG (no alpha needed in final)
    final = img.convert('RGB')

    # Save to bytes
    buf = io.BytesIO()
    final.save(buf, format='PNG', optimize=True)
    buf.seek(0)
    return buf.getvalue()


# ===================================================================
# ROUTES
# ===================================================================

def _generate_and_upload(body: dict, request_id: str) -> Dict[str, Any]:
    """
    Generate 3000x3000 PNG product image and upload to S3.

    Body:
      country: 'fr' (ISO code, required)
      visaType: 'tourist' (required)
      price: '₹2,999' (optional)
      tagline: custom tagline (optional)
      countryName: override country name (optional)
      category: S3 subfolder (default: 'bnb-club')
      productId: optional native ProductsTable id to attach image
      expectedUpdatedAt: required with productId for optimistic concurrency
    """
    country = body.get('country', '')
    visa_type = body.get('visaType', '')
    if not country or not visa_type:
        return _resp(400, {'error': 'Missing country or visaType', 'requestId': request_id})

    price = body.get('price', '')
    tagline = body.get('tagline', '')
    country_name = body.get('countryName', '')
    category = body.get('category', 'bnb-club').strip('/')

    # Generate PNG
    png_bytes = _generate_png(country, visa_type, price, tagline, country_name)
    short_id = uuid.uuid4().hex[:8]
    file_name = f'wecare-digital-{short_id}-{country}-{visa_type}.png'
    s3_key = f'{S3_PREFIX}/{file_name}'

    try:
        s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=png_bytes,
            ContentType='image/png',
            CacheControl='public, max-age=31536000',
        )

        public_url = f'https://{CDN_DOMAIN}/{s3_key}'
        size_kb = len(png_bytes) / 1024

        result = {
            's3Key': s3_key,
            'publicUrl': public_url,
            'fileName': file_name,
            'country': country,
            'visaType': visa_type,
            'sizeKB': round(size_kb, 1),
            'dimensions': f'{IMG_SIZE}x{IMG_SIZE}',
            'format': 'PNG',
            'uploaded': True,
            'requestId': request_id,
        }

        # Optionally attach to the AWS-native product row. This is guarded by
        # expectedUpdatedAt so image generation can never overwrite a concurrent
        # staff catalog edit. The S3 object remains valid even if the attach loses
        # the optimistic-lock race.
        pid = str(body.get('productId') or '').strip()
        if pid:
            expected = str(body.get('expectedUpdatedAt') or '').strip()
            if not expected:
                result['productAttached'] = False
                result['productAttachError'] = 'EXPECTED_UPDATED_AT_REQUIRED'
            else:
                try:
                    table = boto3.resource(
                        'dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1')
                    ).Table(PRODUCTS_TABLE)
                    current = table.get_item(
                        Key={'id': pid}, ConsistentRead=True
                    ).get('Item')
                    if not current:
                        result['productAttached'] = False
                        result['productAttachError'] = 'PRODUCT_NOT_FOUND'
                    elif str(current.get('updatedAt') or '') != expected:
                        result['productAttached'] = False
                        result['productAttachError'] = 'PRODUCT_VERSION_CONFLICT'
                    else:
                        refs = [str(x) for x in (current.get('imageRefs') or [])
                                if isinstance(x, str) and x]
                        if public_url not in refs:
                            refs.append(public_url)
                        now = datetime.now(timezone.utc).isoformat(
                            timespec='milliseconds').replace('+00:00', 'Z')
                        table.update_item(
                            Key={'id': pid},
                            UpdateExpression='SET #images = :images, #updated = :now',
                            ConditionExpression='#updated = :expected',
                            ExpressionAttributeNames={
                                '#images': 'imageRefs', '#updated': 'updatedAt',
                            },
                            ExpressionAttributeValues={
                                ':images': refs, ':now': now, ':expected': expected,
                            },
                        )
                        result['productAttached'] = True
                        result['productId'] = pid
                        result['updatedAt'] = now
                except Exception as e:
                    code = getattr(e, 'response', {}).get('Error', {}).get('Code')
                    result['productAttached'] = False
                    result['productAttachError'] = (
                        'PRODUCT_VERSION_CONFLICT'
                        if code == 'ConditionalCheckFailedException'
                        else 'NATIVE_PRODUCT_ATTACH_FAILED'
                    )

        return _resp(200, result)
    except Exception as e:
        return _resp(500, {'error': str(e), 'requestId': request_id})


def _preview_svg(params: dict, request_id: str) -> Dict[str, Any]:
    """Return lightweight SVG preview for browser (no S3 upload)."""
    country = params.get('country', 'fr')
    visa_type = params.get('visaType', 'tourist')
    price = params.get('price', '')
    tagline = params.get('tagline', '')
    country_name = params.get('countryName', '')

    cc = country.lower()
    vt = visa_type.lower()
    c_name = country_name or COUNTRIES.get(cc, cc.upper())
    v_info = VISA_TYPES.get(vt, {'label': f'{vt.upper()} VISA', 'color': (0, 201, 167)})
    v_label = v_info['label']
    vc = v_info['color']
    v_hex = f'#{vc[0]:02x}{vc[1]:02x}{vc[2]:02x}'
    flag_cc = 'eu' if cc == 'schengen' else cc
    flag_url = f'https://flagcdn.com/w320/{flag_cc}.png'
    price_text = f'From {price}' if price else ''
    tl = tagline or 'We optimize for approval, not just submission'

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="1000" viewBox="0 0 1000 1000">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#0A1628"/><stop offset="100%" style="stop-color:#1A2744"/>
    </linearGradient>
    <radialGradient id="glow" cx="50%" cy="38%" r="35%">
      <stop offset="0%" style="stop-color:{v_hex};stop-opacity:0.15"/>
      <stop offset="100%" style="stop-color:{v_hex};stop-opacity:0"/>
    </radialGradient>
    <clipPath id="fc"><circle cx="500" cy="380" r="120"/></clipPath>
  </defs>
  <rect width="1000" height="1000" fill="url(#bg)"/>
  <rect width="1000" height="1000" fill="url(#glow)"/>
  <rect x="0" y="0" width="1000" height="4" fill="{v_hex}" opacity="0.8"/>
  <text x="50" y="70" font-family="Arial,sans-serif" font-size="20" font-weight="700" fill="white" opacity="0.9">WECARE.DIGITAL</text>
  <rect x="740" y="40" width="220" height="44" rx="22" fill="{v_hex}" opacity="0.9"/>
  <text x="850" y="68" font-family="Arial,sans-serif" font-size="18" font-weight="700" fill="white" text-anchor="middle">BNB CLUB</text>
  <circle cx="500" cy="380" r="125" fill="white" opacity="0.06"/>
  <circle cx="500" cy="380" r="122" fill="none" stroke="{v_hex}" stroke-width="2" opacity="0.4"/>
  <image href="{flag_url}" x="380" y="310" width="240" height="140" clip-path="url(#fc)" preserveAspectRatio="xMidYMid slice"/>
  <rect x="350" y="530" width="300" height="46" rx="23" fill="{v_hex}" opacity="0.15"/>
  <rect x="350" y="530" width="300" height="46" rx="23" fill="none" stroke="{v_hex}" stroke-width="1.5" opacity="0.5"/>
  <text x="500" y="560" font-family="Arial,sans-serif" font-size="20" font-weight="700" fill="{v_hex}" text-anchor="middle" letter-spacing="3">{v_label}</text>
  <text x="500" y="640" font-family="Arial,sans-serif" font-size="52" font-weight="800" fill="white" text-anchor="middle">{c_name.upper()}</text>
  <text x="500" y="710" font-family="Arial,sans-serif" font-size="16" fill="white" opacity="0.5" text-anchor="middle" font-style="italic">"{tl}"</text>
  <text x="500" y="780" font-family="Arial,sans-serif" font-size="28" font-weight="700" fill="{v_hex}" text-anchor="middle">{price_text}</text>
  <rect x="0" y="920" width="1000" height="80" fill="white" opacity="0.03"/>
  <text x="500" y="958" font-family="Arial,sans-serif" font-size="14" fill="white" opacity="0.35" text-anchor="middle">WhatsApp: +91 93309 94400  |  visa@wecare.digital</text>
  <rect x="0" y="996" width="1000" height="4" fill="{v_hex}" opacity="0.8"/>
</svg>'''

    svg_headers = cors_headers(origin)
    svg_headers['Content-Type'] = 'image/svg+xml'
    return {
        'statusCode': 200,
        'headers': svg_headers,
        'body': svg,
    }


def _convert_flag_to_png(body: dict, request_id: str) -> Dict[str, Any]:
    """
    Fetch flag PNG from flagcdn.com, render onto 3000x3000 white canvas, upload to S3.

    Body:
      country: 'in' (ISO code, required)
      size: 3000 (optional, default 3000)
      background: 'white' or 'transparent' (optional, default 'white')
    """
    cc = body.get('country', '').lower()
    if not cc:
        return _resp(400, {'error': 'Missing country code', 'requestId': request_id})

    size = int(body.get('size', 3000))
    bg = body.get('background', 'white')

    try:
        # Fetch highest res flag from flagcdn (640px wide)
        flag_img = _fetch_flag(cc, 640)

        # Create square canvas
        if bg == 'transparent':
            canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        else:
            canvas = Image.new('RGBA', (size, size), (255, 255, 255, 255))

        # Scale flag to fit canvas with padding (80% of canvas)
        flag_w, flag_h = flag_img.size
        aspect = flag_w / flag_h
        target_w = int(size * 0.85)
        target_h = int(target_w / aspect)
        if target_h > int(size * 0.85):
            target_h = int(size * 0.85)
            target_w = int(target_h * aspect)

        flag_resized = flag_img.resize((target_w, target_h), Image.LANCZOS)

        # Center on canvas
        x = (size - target_w) // 2
        y = (size - target_h) // 2
        canvas.paste(flag_resized, (x, y), flag_resized if flag_resized.mode == 'RGBA' else None)

        # Save as PNG
        buf = io.BytesIO()
        if bg == 'transparent':
            canvas.save(buf, format='PNG', optimize=True)
        else:
            canvas.convert('RGB').save(buf, format='PNG', optimize=True)
        buf.seek(0)
        png_bytes = buf.getvalue()

        # Upload to S3
        s3_key = media_paths.public(f'stream/media/flags/wecare-digital-{cc}.png')
        s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=png_bytes,
            ContentType='image/png',
            CacheControl='public, max-age=31536000',
        )

        return _resp(200, {
            's3Key': s3_key,
            'publicUrl': f'https://{CDN_DOMAIN}/{s3_key}',
            'country': cc,
            'dimensions': f'{size}x{size}',
            'sizeKB': round(len(png_bytes) / 1024, 1),
            'uploaded': True,
            'requestId': request_id,
        })
    except Exception as e:
        return _resp(500, {'error': str(e), 'requestId': request_id})


def _resp(status_code: int, body: dict) -> Dict[str, Any]:
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps(body, default=str),
    }
