"""Contract tests for the Gastronomy batch gate: v2 editorial rules plus the native blog contract."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'gastronomy_batch.py'


def load_module():
    spec = importlib.util.spec_from_file_location('gastronomy_batch', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_post(n: int, title=None):
    slug = f'post-{n:03d}'
    return {
        'id': f'GAST-{n:03d}',
        'title': title or f'Post {n:03d}',
        'slug': slug,
        'author': 'Anew by WECARE.DIGITAL',
        'category': 'Gastronomy',
        'tags': ['Breakfast'],
        'seo_title': f'{title or f"Post {n:03d}"} | WECARE.DIGITAL',
        'meta_description': f'Meta description for post {n:03d}.',
        'canonical': f'https://wecare.digital/post/{slug}/',
        'source_ref': f'private source p.{n}',
        'image_status': 'none',
        'article_type': 'RECIPE',
        'body_markdown': (
            'This recipe has a clear culinary identity and enough context to explain what to look for before cooking.\n\n'
            '## Ingredients\n\n- 1 cup ingredient\n- 1 tsp spice\n\n'
            '## Method\n\nCook carefully, watching texture and heat rather than relying only on the clock. '
            'Let it rest off the heat before serving, so the texture settles rather than tightening.'
        ),
    }


def make_doc(start=455, size=25):
    return {
        'quality_version': 2,
        'batch_start': start,
        'batch_end': start + size - 1,
        'source_profile': {
            'label': 'Example source',
            'blocked_public_terms': ['Example Publisher', 'Example Author', 'Example Institute'],
            'required_public_attribution_terms': [],
        },
        'posts': [make_post(i) for i in range(start, start + size)],
    }


def test_v2_manifest_accepts_150_posts():
    m = load_module()
    doc = make_doc(size=150)
    assert m.validate_batch_document(doc, require_v2=True) == []


def test_manifest_over_150_is_rejected():
    m = load_module()
    doc = make_doc(size=151)
    errors = m.validate_batch_document(doc, require_v2=True)
    assert any('1-150' in e for e in errors)


def test_there_is_no_publish_mode():
    """Publication belongs to Blog Studio; this gate validates and audits only."""
    m = load_module()
    assert m.MAX_MANIFEST_POSTS == 150
    assert not hasattr(m, 'publish_document')
    with pytest.raises(SystemExit) as refused:
        m.main(['publish', '--manifest', 'unused.json'])
    assert refused.value.code == 2
    source = SCRIPT.read_text(encoding='utf-8')
    for forbidden in ('put_item', 'put_object', 'create_blog_post(', '/blog-publish',
                      'get_secret_value', 'Authorization'):
        assert forbidden not in source, forbidden


def test_source_terms_are_dynamic_not_isha_specific():
    m = load_module()
    doc = make_doc(size=1)
    doc['posts'][0]['body_markdown'] += '\n\nExample Publisher prepared the original material.'
    errors = m.validate_batch_document(doc, require_v2=True)
    assert any('Example Publisher' in e for e in errors)
    assert not any('Isha' in e for e in errors)


def test_required_attribution_can_be_explicitly_allowed():
    m = load_module()
    doc = make_doc(size=1)
    doc['source_profile']['blocked_public_terms'] = ['Named Theory']
    doc['source_profile']['required_public_attribution_terms'] = ['Named Theory']
    doc['posts'][0]['body_markdown'] += '\n\nNamed Theory is discussed here because attribution is required.'
    errors = m.validate_batch_document(doc, require_v2=True)
    assert not any('Named Theory' in e for e in errors)


def test_generic_source_scaffolding_is_rejected():
    m = load_module()
    doc = make_doc(size=1)
    doc['posts'][0]['body_markdown'] += '\n\nThe cookbook says to toast the spice first.'
    errors = m.validate_batch_document(doc, require_v2=True)
    assert any('cookbook-facing language' in e for e in errors)


def test_personal_possessive_title_requires_justification():
    m = load_module()
    doc = make_doc(size=1)
    p = doc['posts'][0]
    p['title'] = "Caroline's Carob Almond Cookies"
    p['seo_title'] = "Caroline's Carob Almond Cookies | WECARE.DIGITAL"
    errors = m.validate_batch_document(doc, require_v2=True)
    assert any('personal/kinship name' in e for e in errors)


def test_personal_title_can_be_justified_when_identity_is_essential():
    m = load_module()
    doc = make_doc(size=1)
    p = doc['posts'][0]
    p['title'] = "Caroline's Carob Almond Cookies"
    p['seo_title'] = "Caroline's Carob Almond Cookies | WECARE.DIGITAL"
    p['public_name_justification'] = 'Established dish identity with required attribution.'
    errors = m.validate_batch_document(doc, require_v2=True)
    assert not any('personal/kinship name' in e for e in errors)


def test_health_claim_title_requires_review():
    m = load_module()
    doc = make_doc(size=1)
    p = doc['posts'][0]
    p['title'] = 'Cold Cure Soup'
    p['seo_title'] = 'Cold Cure Soup | WECARE.DIGITAL'
    errors = m.validate_batch_document(doc, require_v2=True)
    assert any('health-claim term' in e for e in errors)


def test_non_recipe_article_does_not_require_ingredients_method():
    m = load_module()
    doc = make_doc(size=1)
    p = doc['posts'][0]
    p['article_type'] = 'CULINARY_ARTICLE'
    p['body_markdown'] = (
        'A first substantial paragraph explains the culinary distinction clearly enough to orient the reader without source-facing framing.\n\n'
        'A second substantial paragraph develops the technique, ingredient logic, or cultural context while remaining independently written.'
    )
    errors = m.validate_batch_document(doc, require_v2=True)
    assert not any('Ingredients heading' in e for e in errors)
    assert not any('Method heading' in e for e in errors)


def test_legacy_manifest_can_still_validate_but_cannot_be_audited():
    m = load_module()
    legacy = {
        'batch_start': 41,
        'batch_end': 41,
        'posts': [make_post(41)],
    }
    assert not any('quality_version' in e for e in m.validate_batch_document(legacy, require_v2=False))
    assert any('quality_version' in e for e in m.validate_batch_document(legacy, require_v2=True))


def test_unreconciled_live_baseline_is_valid_but_cannot_advance():
    m = load_module()
    progress = {
        'completed_through': 340,
        'next_id': None,
        'max_manifest_posts': 150,
        'live_verified_posts': 454,
        'sequence_reconciled': False,
    }
    assert m.validate_progress(progress) == []
    try:
        m.advance_progress(progress, 341, 454)
    except ValueError as exc:
        assert 'reconciliation' in str(exc)
    else:
        raise AssertionError('expected unreconciled progress to block sequence advance')


def test_progress_is_variable_size_up_to_150_after_reconciliation():
    m = load_module()
    progress = {
        'completed_through': 454,
        'next_id': 455,
        'max_manifest_posts': 150,
        'live_verified_posts': 454,
        'sequence_reconciled': True,
    }
    assert m.validate_progress(progress) == []
    advanced = m.advance_progress(progress, 455, 604)
    assert advanced['completed_through'] == 604
    assert advanced['next_id'] == 605
    assert advanced['last_manifest'] == 'GAST-455-GAST-604'


def test_progress_rejects_skip_and_over_150():
    m = load_module()
    progress = {
        'completed_through': 454,
        'next_id': 455,
        'max_manifest_posts': 150,
        'live_verified_posts': 454,
        'sequence_reconciled': True,
    }
    try:
        m.advance_progress(progress, 456, 500)
    except ValueError as exc:
        assert 'next_id' in str(exc)
    else:
        raise AssertionError('expected skipped start to fail')

    try:
        m.advance_progress(progress, 455, 605)
    except ValueError as exc:
        assert '1-150' in str(exc)
    else:
        raise AssertionError('expected oversized manifest to fail')


def test_normal_cooking_language_is_not_globally_blocked():
    m = load_module()
    doc = make_doc(size=1)
    doc['posts'][0]['body_markdown'] += (
        '\n\nThe vegetables are cooked with ginger and herbs, and the technique can be learned from repeated practice.'
    )
    errors = m.validate_batch_document(doc, require_v2=True)
    assert not any('personal provenance' in e for e in errors)
    assert not any('source-institution provenance' in e for e in errors)


def test_pdf_profile_blocks_publisher_author_title_and_private_place():
    m = load_module()
    doc = make_doc(size=1)
    doc['source_profile'] = {
        'label': 'PDF source',
        'source_type': 'PDF',
        'source_ref': 'private://example.pdf',
        'publisher_names': ['Example Publisher'],
        'author_names': ['Example Author'],
        'publication_titles': ['Example Cookbook'],
        'institution_names': ['Example Institute'],
        'private_person_names': ['Private Person'],
        'private_place_names': ['Private Kitchen'],
        'provenance_phrases': ['family kitchen in Example Town'],
        'allowed_public_terms': [],
        'required_public_attribution_terms': [],
    }
    doc['posts'][0]['body_markdown'] += '\n\nExample Cookbook was prepared by Example Author for Example Publisher.'
    errors = m.validate_batch_document(doc, require_v2=True)
    joined = '\n'.join(errors)
    assert 'Example Cookbook' in joined
    assert 'Example Author' in joined
    assert 'Example Publisher' in joined


def test_allowed_public_term_overrides_source_profile_block():
    m = load_module()
    doc = make_doc(size=1)
    doc['source_profile']['blocked_public_terms'] = ['Persian']
    doc['source_profile']['allowed_public_terms'] = ['Persian']
    doc['posts'][0]['body_markdown'] += '\n\nPersian culinary identity is central to this dish.'
    errors = m.validate_batch_document(doc, require_v2=True)
    assert not any('Persian' in e for e in errors)


def test_v2_source_profile_requires_label():
    m = load_module()
    doc = make_doc(size=1)
    doc['source_profile']['label'] = ''
    errors = m.validate_batch_document(doc, require_v2=True)
    assert any('source_profile requires label' in e for e in errors)


# ── the native blog contract ────────────────────────────────────────────────────

def test_recipe_structure_is_read_the_way_the_native_page_renders_it():
    """A heading deeper than ### is not a heading on the native page, so Method goes missing."""
    m = load_module()
    doc = make_doc(size=1)
    post = doc['posts'][0]
    post['body_markdown'] = post['body_markdown'].replace('## Method', '#### Method')
    errors = m.validate_batch_document(doc, require_v2=True)
    assert any('heading deeper than ###' in e for e in errors)
    assert any('missing Method heading' in e for e in errors)


def test_a_slug_the_native_store_would_rewrite_is_rejected():
    m = load_module()
    doc = make_doc(size=1)
    post = doc['posts'][0]
    post['slug'] = 'Post 455'
    post['canonical'] = 'https://wecare.digital/post/Post 455/'
    errors = m.validate_batch_document(doc, require_v2=True)
    assert any('slug must be lowercase words joined by single hyphens' in e for e in errors)


def test_body_markup_the_native_page_shows_literally_is_rejected():
    m = load_module()
    doc = make_doc(size=1)
    doc['posts'][0]['body_markdown'] += '\n\n> A quoted tip about resting the dough.'
    errors = m.validate_batch_document(doc, require_v2=True)
    assert any("blockquote marker shows as a literal '>'" in e for e in errors)


def test_validate_needs_no_aws_sdk(monkeypatch):
    m = load_module()
    monkeypatch.setitem(__import__('sys').modules, 'boto3', None)
    assert m.validate_batch_document(make_doc(size=3), require_v2=True) == []


def native_post(post, **overrides):
    """A live post as the native `/seo-tools/blog-public/<slug>` view returns it."""
    live = {
        'id': f"BLOG#{post['slug']}",
        'slug': post['slug'],
        'title': post['title'],
        'url': f"https://wecare.digital/post/{post['slug']}/",
        'authorName': post['author'],
        'category': post['category'],
        'tags': list(post['tags']),
        'seoTitle': post['seo_title'],
        'metaDescription': post['meta_description'],
        'coverImage': '',
        'content': post['body_markdown'],
        'contentText': post['body_markdown'],
        'publishedDate': '2026-10-01T00:00:00Z',
    }
    live.update(overrides)
    return live


def test_a_native_post_with_its_recipe_structure_audits_clean():
    m = load_module()
    doc = make_doc(size=1)
    post = doc['posts'][0]
    assert m.audit_public_post(native_post(post), post, m._source_profile(doc), 2) == []


def test_audit_reads_recipe_structure_from_the_native_markdown_body():
    m = load_module()
    doc = make_doc(size=1)
    post = doc['posts'][0]
    body = post['body_markdown'].replace('## Method', 'Method').replace('- ', '')
    errors = m.audit_public_post(native_post(post, content=body, contentText=body), post)
    assert any('missing Method heading' in e for e in errors)
    assert any('missing ingredient list' in e for e in errors)


def test_audit_catches_native_formatting_and_metadata_defects():
    m = load_module()
    doc = make_doc(size=1)
    post = doc['posts'][0]
    body = post['body_markdown'] + '\n\n#### Serving\nnull'
    live = native_post(post, content=body, contentText=body, coverImage='x.jpg',
                       authorName='Someone')
    joined = '\n'.join(m.audit_public_post(live, post))
    assert 'published body: heading deeper than ###' in joined
    assert 'editor placeholder token' in joined
    assert 'cover image must be empty' in joined
    assert 'author mismatch' in joined


def test_audit_checks_source_privacy_on_the_rendered_body():
    """Emphasis markers split a blocked name in the Markdown; the reader still sees it whole."""
    m = load_module()
    doc = make_doc(size=1)
    post = doc['posts'][0]
    body = post['body_markdown'] + '\n\nExample **Publisher** prepared the original material.'
    errors = m.audit_public_post(native_post(post, content=body, contentText=body),
                                 post, m._source_profile(doc), 2)
    assert any('"Example Publisher"' in e for e in errors)


def test_audit_reports_a_post_that_is_not_live_and_keeps_going(monkeypatch):
    m = load_module()
    doc = make_doc(size=2)
    first, second = doc['posts']
    live = {first['slug']: native_post(first)}

    def fetch(slug):
        if slug not in live:
            raise RuntimeError(f'public-blog HTTP 404 for /seo-tools/blog-public/{slug}')
        return live[slug]

    monkeypatch.setattr(m, 'fetch_public_post', fetch)
    assert m.audit_document(doc) == [
        f"{second['slug']}: read-back failed "
        f"(public-blog HTTP 404 for /seo-tools/blog-public/{second['slug']})"
    ]
