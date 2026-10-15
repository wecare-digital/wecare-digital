#!/usr/bin/env python3
"""Gastronomy batch gate: validate a manifest, audit what went live.

Both modes check against the AWS-native blog through `blog_native_contract`: the slug the
store keeps, the Markdown the post page renders, and the public read route of
`wecare-seo-tools`. Recipe structure is read the way that renderer reads it, one line at a
time.

There is no publish mode. Publication belongs to Blog Studio, where `wecare-seo-tools`
performs the native write behind its own sign-off and release gates; a writer here would be a
second route to the same store that skips them.
"""
import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import blog_native_contract as native  # noqa: E402

AUTHOR = 'Anew by WECARE.DIGITAL'
CATEGORY = 'Gastronomy'
QUALITY_VERSION = 2
MAX_MANIFEST_POSTS = 150

RECIPE_TYPES = {'RECIPE'}
SOURCE_PROFILE_TERM_FIELDS = (
    'blocked_public_terms',
    'publisher_names',
    'author_names',
    'publication_titles',
    'institution_names',
    'private_person_names',
    'private_place_names',
    'provenance_phrases',
)
GENERIC_SOURCE_PATTERNS = [
    (re.compile(r'\bsource note\b', re.I), 'source note'),
    (re.compile(r'\badapted from\b', re.I), 'adapted from'),
    (re.compile(r'\bindependently written from\b', re.I), 'independently written from'),
    (
        re.compile(
            r'\b(?:the|this) source(?:[’\']s)?\b|'
            r'\bsource recipe\b|'
            r'\baccording to the source\b|'
            r'\bin the source\b',
            re.I,
        ),
        'source-facing language',
    ),
    (
        re.compile(
            r'\b(?:the|this) cookbook(?:[’\']s)?\b|'
            r'\baccording to the cookbook\b|'
            r'\bin the cookbook\b',
            re.I,
        ),
        'cookbook-facing language',
    ),
    (
        re.compile(
            r'\bthe book (?:says|describes|presents|notes|uses|recommends|explains)\b|'
            r'\bin (?:the|this) book\b',
            re.I,
        ),
        'book-facing language',
    ),
    (
        re.compile(
            r'\bthe author (?:says|describes|notes|explains|learned|grew up|recalls)\b|'
            r'\bthe author[’\']s (?:family|friend|teacher|mentor|background|childhood|home|story|experience)\b',
            re.I,
        ),
        'source-author biography',
    ),
]
PERSONAL_TITLE_PATTERN = re.compile(
    r'^(?:Grandma|Granny|Mama|Papa|Aunty|Aunt|Uncle|Mom|Mother|Father|Dad)[’\']s\b|^[A-Z][A-Za-z.-]{2,}[’\']s\b'
)
HEALTH_TITLE_PATTERN = re.compile(r'\b(?:cure|detox|cleanse|heal|treat|prevent|medicinal)\b', re.I)


def body_structure(markdown: str):
    """Headings, list presence and substantive prose, as the native post page renders them.

    Each non-blank line is one block (`blog_native_contract.parse_blocks`). A `- ` line is a
    list item, and a prose paragraph counts as substantive at 60 visible characters.
    """
    blocks = native.parse_blocks(markdown)
    return {
        'headings': [block.text for block in blocks if block.kind == 'heading'],
        'has_list': any(block.kind == 'item' for block in blocks),
        'paragraphs': [
            block.text for block in blocks
            if block.kind == 'paragraph' and len(block.text.strip()) >= 60
        ],
    }


def _quality_version(document):
    try:
        return int(document.get('quality_version') or 1)
    except (TypeError, ValueError):
        return 1


def _clean_term_list(value):
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()]


def _source_profile(document):
    profile = document.get('source_profile') or {}
    blocked = []
    for field in SOURCE_PROFILE_TERM_FIELDS:
        blocked.extend(_clean_term_list(profile.get(field)))
    blocked = list(dict.fromkeys(blocked))
    return {
        'label': str(profile.get('label') or '').strip(),
        'source_type': str(profile.get('source_type') or '').strip(),
        'source_ref': str(profile.get('source_ref') or '').strip(),
        'blocked_public_terms': blocked,
        'allowed_public_terms': _clean_term_list(profile.get('allowed_public_terms')),
        'required_public_attribution_terms': _clean_term_list(profile.get('required_public_attribution_terms')),
    }


def _public_text(post):
    return '\n'.join([
        str(post.get('title') or ''),
        str(post.get('slug') or ''),
        str(post.get('seo_title') or ''),
        str(post.get('meta_description') or ''),
        str(post.get('body_markdown') or ''),
    ])


def _source_privacy_errors(post, source_profile, prefix):
    errors = []
    public = _public_text(post)
    allowed = {
        x.casefold()
        for x in (
            source_profile.get('allowed_public_terms', [])
            + source_profile.get('required_public_attribution_terms', [])
        )
    }
    for regex, label in GENERIC_SOURCE_PATTERNS:
        if regex.search(public):
            errors.append(f'{prefix}: public copy contains {label}')
    for term in source_profile.get('blocked_public_terms', []):
        if term.casefold() in allowed:
            continue
        if term.casefold() in public.casefold():
            errors.append(f'{prefix}: public copy leaks blocked source/private term "{term}"')
    title = str(post.get('title') or '')
    if PERSONAL_TITLE_PATTERN.search(title) and not post.get('public_name_justification'):
        errors.append(f'{prefix}: title exposes a personal/kinship name without justification')
    title_and_seo = f"{title}\n{post.get('seo_title') or ''}"
    if HEALTH_TITLE_PATTERN.search(title_and_seo) and not post.get('health_claim_reviewed'):
        errors.append(f'{prefix}: title/SEO contains a health-claim term without review')
    return errors


def validate_batch_document(document: dict, require_v2=False):
    errors = []
    posts = document.get('posts')
    if not isinstance(posts, list):
        return ['posts must be a list']
    if not 1 <= len(posts) <= MAX_MANIFEST_POSTS:
        errors.append(f'manifest must contain 1-{MAX_MANIFEST_POSTS} posts')

    quality_version = _quality_version(document)
    if require_v2 and quality_version < QUALITY_VERSION:
        errors.append(f'quality_version must be {QUALITY_VERSION} or higher for audit')

    start = document.get('batch_start')
    end = document.get('batch_end')
    if start is not None or end is not None:
        if not isinstance(start, int) or not isinstance(end, int) or end != start + len(posts) - 1:
            errors.append('batch_start/batch_end must match the actual contiguous manifest size')

    profile = _source_profile(document)
    if quality_version >= QUALITY_VERSION:
        if not isinstance(document.get('source_profile'), dict):
            errors.append('quality v2 manifest requires source_profile object')
        elif not profile.get('label'):
            errors.append('quality v2 source_profile requires label')

    ids, slugs, titles = [], [], []
    for idx, post in enumerate(posts):
        prefix = post.get('id') or f'index {idx}'
        ids.append(post.get('id'))
        slugs.append(post.get('slug'))
        titles.append(post.get('title'))
        required = [
            'id', 'title', 'slug', 'author', 'category', 'tags', 'seo_title',
            'meta_description', 'canonical', 'source_ref', 'body_markdown', 'image_status',
        ]
        for key in required:
            if not post.get(key):
                errors.append(f'{prefix}: missing {key}')
        if post.get('author') != AUTHOR:
            errors.append(f'{prefix}: author must be {AUTHOR}')
        if post.get('category') != CATEGORY:
            errors.append(f'{prefix}: category must be {CATEGORY}')
        tags = post.get('tags') or []
        if not isinstance(tags, list) or not 1 <= len(tags) <= 3:
            errors.append(f'{prefix}: must have 1-3 tags')
        slug = str(post.get('slug') or '')
        if slug:
            errors.extend(f'{prefix}: {problem}' for problem in native.slug_errors(slug))
        if post.get('canonical') != native.canonical_url(slug):
            errors.append(f'{prefix}: canonical must match slug')

        body = str(post.get('body_markdown') or '')
        if body.strip():
            errors.extend(f'{prefix}: {problem}' for problem in native.body_errors(body))
        structure = body_structure(body)
        article_type = str(post.get('article_type') or 'RECIPE').upper()

        if len(body.strip()) < 250:
            errors.append(f'{prefix}: body too thin for editorial publication')
        min_paragraphs = 1 if article_type in RECIPE_TYPES else 2
        if len(structure['paragraphs']) < min_paragraphs:
            errors.append(f'{prefix}: needs {min_paragraphs} substantive prose paragraph(s) with real spacing')
        if article_type in RECIPE_TYPES:
            if 'Ingredients' not in structure['headings']:
                errors.append(f'{prefix}: missing Ingredients heading')
            if 'Method' not in structure['headings']:
                errors.append(f'{prefix}: missing Method heading')
            if not structure['has_list']:
                errors.append(f'{prefix}: missing ingredient list')
        if post.get('image_status') != 'none':
            errors.append(f'{prefix}: image_status must be none')

        if quality_version >= QUALITY_VERSION:
            errors.extend(_source_privacy_errors(post, profile, prefix))

    if len([x for x in slugs if x]) != len(set(x for x in slugs if x)):
        errors.append('duplicate slug inside manifest')
    if len([x for x in titles if x]) != len(set(x for x in titles if x)):
        errors.append('duplicate title inside manifest')
    if len([x for x in ids if x]) != len(set(x for x in ids if x)):
        errors.append('duplicate id inside manifest')

    if isinstance(start, int) and len(posts):
        expected = [f'GAST-{n:03d}' for n in range(start, start + len(posts))]
        if ids != expected:
            errors.append('post ids must be contiguous and match batch_start through batch_end')
    return errors


def _live_public_text(post):
    """Everything a reader or crawler sees: title, slug, SEO fields and the rendered body.

    The native view serves the stored Markdown as `content`; the body is taken as the post
    page renders it, with heading and emphasis markers resolved.
    """
    content = str(post.get('content') or post.get('contentText') or '')
    return '\n'.join([
        str(post.get('title') or ''),
        str(post.get('slug') or ''),
        str(post.get('seoTitle') or ''),
        str(post.get('metaDescription') or ''),
        native.rendered_text(content),
    ]), content


def audit_public_post(post: dict, expected: dict, source_profile=None, quality_version=1):
    errors = []
    source_profile = source_profile or {
        'blocked_public_terms': [],
        'allowed_public_terms': [],
        'required_public_attribution_terms': [],
    }
    slug = str(expected.get('slug') or '')
    if post.get('slug') != slug:
        errors.append(f'{slug}: slug mismatch')
    if post.get('title') and post.get('title') != expected.get('title'):
        errors.append(f'{slug}: title mismatch')
    if post.get('authorName') != AUTHOR:
        errors.append(f'{slug}: author mismatch')
    if post.get('category') != CATEGORY:
        errors.append(f'{slug}: category mismatch')
    if post.get('coverImage'):
        errors.append(f'{slug}: cover image must be empty')
    if post.get('seoTitle') is not None and post.get('seoTitle') != expected.get('seo_title'):
        errors.append(f'{slug}: SEO title mismatch')
    if post.get('metaDescription') is not None and post.get('metaDescription') != expected.get('meta_description'):
        errors.append(f'{slug}: meta description mismatch')

    public, content = _live_public_text(post)
    structure = body_structure(content)

    if not content.strip():
        errors.append(f'{slug}: published body is blank')
    else:
        #: Markdown the post page cannot render - a heading deeper than ###, a heading marker
        #: inside a line, raw HTML - reaches the reader as literal characters.
        errors.extend(f'{slug}: published body: {problem}'
                      for problem in native.format_errors(content))
    if re.search(r'\b(?:undefined|null|nan)\b', public, re.IGNORECASE):
        errors.append(f'{slug}: editor placeholder token in published body')
    if re.search(r'\{\s*["\']?(?:type|nodes|richContent|textData)["\']?\s*:', public):
        errors.append(f'{slug}: raw editor JSON in published body')
    if '\\n' in public:
        errors.append(f'{slug}: literal escaped newline in published body')

    article_type = str(expected.get('article_type') or 'RECIPE').upper()
    min_paragraphs = 1 if article_type in RECIPE_TYPES else 2
    if len(structure['paragraphs']) < min_paragraphs:
        errors.append(f'{slug}: insufficient substantive prose paragraphs')
    if article_type in RECIPE_TYPES:
        if 'Ingredients' not in structure['headings']:
            errors.append(f'{slug}: missing Ingredients heading')
        if 'Method' not in structure['headings']:
            errors.append(f'{slug}: missing Method heading')
        if not structure['has_list']:
            errors.append(f'{slug}: missing ingredient list')

    if quality_version >= QUALITY_VERSION:
        live_expected = dict(expected)
        live_expected['title'] = post.get('title') or expected.get('title')
        live_expected['slug'] = post.get('slug') or expected.get('slug')
        live_expected['seo_title'] = post.get('seoTitle') or expected.get('seo_title')
        live_expected['meta_description'] = post.get('metaDescription') or expected.get('meta_description')
        live_expected['body_markdown'] = public
        errors.extend(_source_privacy_errors(live_expected, source_profile, slug))
    return errors


def fetch_public_post(slug: str):
    """One published post through the public read route of `wecare-seo-tools`."""
    return native.fetch_public_post(slug)


def audit_document(document: dict):
    errors = validate_batch_document(document, require_v2=True)
    if errors:
        return errors
    profile = _source_profile(document)
    quality_version = _quality_version(document)
    audit_errors = []
    for expected in document.get('posts', []):
        try:
            live = fetch_public_post(expected['slug'])
        except RuntimeError as exc:
            #: A slug that is not live answers 404 on the public route; report it per post
            #: rather than letting one missing post end the audit of the rest.
            audit_errors.append(f"{expected['slug']}: read-back failed ({exc})")
            continue
        audit_errors.extend(audit_public_post(live, expected, profile, quality_version))
    return audit_errors


def validate_progress(progress: dict):
    errors = []
    max_posts = progress.get('max_manifest_posts')
    if max_posts != MAX_MANIFEST_POSTS:
        errors.append(f'max_manifest_posts must be {MAX_MANIFEST_POSTS}')
    live_verified = progress.get('live_verified_posts')
    if not isinstance(live_verified, int) or live_verified < 0:
        errors.append('live_verified_posts must be a non-negative integer')
    reconciled = progress.get('sequence_reconciled') is True
    next_id = progress.get('next_id')
    completed = progress.get('completed_through')
    if reconciled:
        if not isinstance(completed, int) or completed < 0:
            errors.append('completed_through must be a non-negative integer after sequence reconciliation')
        if not isinstance(next_id, int) or not isinstance(completed, int) or next_id != completed + 1:
            errors.append('next_id must equal completed_through + 1 after sequence reconciliation')
    elif next_id is not None:
        errors.append('next_id must be null until sequence reconciliation is complete')
    return errors


def advance_progress(progress: dict, batch_start: int, batch_end: int):
    errors = validate_progress(progress)
    if errors:
        raise ValueError('invalid progress: ' + '; '.join(errors))
    if progress.get('sequence_reconciled') is not True:
        raise ValueError('cannot advance sequence until live/source reconciliation is complete')
    count = batch_end - batch_start + 1
    if not 1 <= count <= MAX_MANIFEST_POSTS:
        raise ValueError(f'progress update must cover 1-{MAX_MANIFEST_POSTS} posts')
    if batch_start != progress['next_id']:
        raise ValueError(f'batch_start {batch_start} does not match next_id {progress["next_id"]}')
    updated = dict(progress)
    updated['completed_through'] = batch_end
    updated['next_id'] = batch_end + 1
    updated['last_manifest'] = f'GAST-{batch_start:03d}-GAST-{batch_end:03d}'
    return updated


def load_document(path: Path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('manifest must be a JSON object')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Gastronomy batch gate: validate and audit (publication happens in Blog Studio)')
    sub = parser.add_subparsers(dest='command', required=True)
    validate = sub.add_parser('validate')
    validate.add_argument('--manifest', required=True, type=Path)
    audit = sub.add_parser('audit')
    audit.add_argument('--manifest', required=True, type=Path)
    args = parser.parse_args(argv)
    doc = load_document(args.manifest)
    if args.command == 'validate':
        errors = validate_batch_document(doc, require_v2=False)
        if errors:
            for error in errors:
                print(error)
            raise SystemExit(1)
        print(f"Validated {len(doc['posts'])} Gastronomy posts")
    elif args.command == 'audit':
        errors = audit_document(doc)
        if errors:
            for error in errors:
                print(error)
            raise SystemExit(1)
        print(f"Audited {len(doc['posts'])} published Gastronomy posts successfully")


if __name__ == '__main__':
    main()
