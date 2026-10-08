#!/usr/bin/env python3
"""THE control-skin census. One scanner, three authoring mechanisms, two match modes.

Mechanisms scanned:
  A  global stylesheets      src/styles/*.css  and  *.module.css
  B  styled-jsx              <style jsx>{` ... `}</style> in src/**/*.tsx
  C  runtime-injected CSS    module-scope template literal appended to
                             document.head via createElement('style')

Match modes:
  1  the selector contains the element as a whole token
  2  the selector names a class that is a className literal on that element

Parsing notes (these matter and the previous census got them wrong):
  - `${ ... }` interpolation is opaque: its braces must not be read as CSS
    braces, or `border: 1px solid ${colors.border}` terminates the rule early
    and the rule is lost. This is why .ui-filter was previously missed.
  - CSS comments are blanked by a character scanner that protects url(...) and
    quoted strings, so `image/*` in an accept= value cannot open a comment.
  - at-rules are recursed into so @media bodies are not skipped.

Committed 2026-10-06, unchanged in its counting rule. It produced the 85/43 inventory
(A-global 44 in 8 files, A-module 0/0, B-styledjsx 38 in 18, C-injected 3 in 2) that
design.md 1.14 rests on, and it lived in gitignored .scratch/ until now. THE COUNTING RULE
IS NOT RESTATABLE FROM THE DESIGN'S TABLES: a defensible reimplementation lands on 84 or
87, after which the committed assertion fails on day one with nothing regressed and the
expected value gets edited instead of the bug fixed. So this file is the single source of
the count. Do not reimplement it; call it.

  python scripts/census_control_skins.py                            human report, <select>
  python scripts/census_control_skins.py --elements checkbox,radio   human report, 1.3c's set
  python scripts/census_control_skins.py --json                      BOTH sets, as JSON

TWO ADDITIONS WERE MADE WHEN IT WAS COMMITTED, neither of which touches how it counts:

  1. ROOT is derived from this file's location instead of being a hardcoded absolute path
     to one worktree. The scan is identical when run from that worktree; the difference is
     that the committed script also works from the branch it is committed to.
  2. --json, plus a SELF-TEST on a planted sample, because src/test/FormControlsCss.test.ts
     asserts against the committed fixture src/test/fixtures/control-skin-census.json rather
     than re-deriving the scan in TypeScript. The self-test exists for the reason
     ScrollbarDeclarations.test.ts has one: a scanner with a parsing bug reports FEWER files
     than exist, which reads as "the gate passed".

A THIRD ADDITION LANDED WITH BATCH 1.3c, and it does not touch the counting rule either -
it WIDENS THE ELEMENT SET the same rule is applied to.

  --elements checkbox,radio

Batch 1.3c puts 53 checkboxes and 18 radios in scope, and until this flag existed nothing
inventoried them: this scanner was hardcoded to <select> and the design's assertion 10 had
no producer at all, while assertion 3 had this one. That asymmetry is what left 71 controls
uncounted for five revisions - a twenty-ninth file skinning a select failed the suite while
a twenty-first file skinning a checkbox landed unnoticed. So assertion 10 now shares
assertion 3's producer rather than getting a second scanner that could disagree with it.

The counting rule is the SAME SENTENCE with the element set substituted: one rule set = one
{...} block, counted once regardless of how many compounds its selector list holds or how
many at-rules it is nested inside; a block counts when its selector names
input[type="checkbox"] or input[type="radio"] as a whole token, OR names a class that
appears as a className literal on one, AND its body sets at least one box property.

STATED BLIND SPOT, because a census presented as exhaustive is how the select half went
wrong twice: a BARE `input` selector is invisible to this rule, and it reaches every type.
Seven of them matter and they are pinned by line in design.md 1.14c rather than by this
scan - tokens.css:420, :434, :440, inner-pages.css:279, :1999, :2021 and
MCPConnections.module.css:14. tokens.css:420 is the one that forces form-controls.css to
declare `padding: 0` on the checkbox.

--json emits BOTH sets from one invocation, because src/test/fixtures/control-skin-census.json
is one committed fixture and two scans in two files would drift apart. The select set keeps
the top-level keys it has always had; the checkbox/radio set arrives under `checkboxRadio`.
--elements selects the element set for the HUMAN report only; with --json present, --json
wins and everything is emitted.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOX_PROPS = {
    'border', 'border-width', 'border-radius', 'border-color', 'border-style',
    'padding', 'padding-block', 'padding-inline', 'height', 'min-height',
    'appearance', '-webkit-appearance', 'background-image', 'background',
    'box-shadow', 'outline', 'outline-offset', 'cursor', 'opacity', 'font-size',
}
GEOMETRY = {'border', 'border-width', 'border-radius', 'padding', 'height',
            'min-height', 'appearance', '-webkit-appearance'}
# EXTRA properties that count as skinning A CHECKBOX OR A RADIO and nothing else. This is
# the one place batch 1.3c touches how the scan counts, and it is scoped to the new element
# set so the 83/41 select baseline cannot move: adding `width` to BOX_PROPS globally would
# make `.inner-page select { width: 100% }` a counted rule set and the select total 84, which
# is precisely the "the expected value gets edited instead of the bug fixed" failure the
# header warns about.
#
# WHY THESE THREE. The two visually-hidden native controls in the tree are hidden with
# `display: none` (voice-in/index.tsx:823) and sized away with `width: auto; margin: 0`
# (engage/sms/index.tsx:591). Neither is a box property, so neither was visible to the
# select-era set - and they are exactly the two rules batch 1.3c has to SEE, because our
# appearance:none box would be drawn on top of a control a call site deliberately hid.
# A census of checkbox skins blind to `display: none` would miss the one defect the batch
# exists to avoid. `height` is already in BOX_PROPS and is not repeated.
CONTROL_BOX_PROPS = {'display', 'width', 'margin'}


# ---------------------------------------------------------------- primitives
def blank_css_comments(body):
    out = list(body)
    i, n, in_url, in_str = 0, len(body), False, None
    while i < n:
        c = body[i]
        if in_str:
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in '"\'':
            in_str = c
            i += 1
            continue
        if not in_url and body.startswith('url(', i):
            in_url = True
            i += 4
            continue
        if in_url and c == ')':
            in_url = False
            i += 1
            continue
        if not in_url and body.startswith('/*', i):
            j = body.find('*/', i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != '\n':
                    out[k] = ' '
            i = j
            continue
        i += 1
    return ''.join(out)


def mask_interpolation(body):
    """Replace ${ ... } with same-length spaces so its braces are inert."""
    out = list(body)
    i, n = 0, len(body)
    while i < n:
        if body.startswith('${', i):
            depth, j = 1, i + 2
            while j < n and depth:
                if body[j] == '{':
                    depth += 1
                elif body[j] == '}':
                    depth -= 1
                j += 1
            for k in range(i, j):
                if out[k] != '\n':
                    out[k] = ' '
            i = j
            continue
        i += 1
    return ''.join(out)


def rule_sets(body, base=0):
    """Yield (selector, decls, offset). Recurses into at-rules."""
    i, n, sel_start = 0, len(body), 0
    while i < n:
        c = body[i]
        if c == '}':            # stray close, resync
            i += 1
            sel_start = i
            continue
        if c == '{':
            selector = body[sel_start:i].strip()
            depth, j = 1, i + 1
            while j < n and depth:
                if body[j] == '{':
                    depth += 1
                elif body[j] == '}':
                    depth -= 1
                j += 1
            inner = body[i + 1:j - 1]
            if selector.startswith('@'):
                yield from rule_sets(inner, base + i + 1)
            else:
                yield selector, inner, base + sel_start
            i, sel_start = j, j
            continue
        i += 1


def box_props(decls, extra=frozenset()):
    found = {}
    wanted = BOX_PROPS | set(extra)
    for d in decls.split(';'):
        if ':' not in d:
            continue
        p, v = d.split(':', 1)
        p = p.strip().lower()
        if p in wanted:
            found[p] = ('!important' in v.lower())
    return found


def specificity(sel):
    """(ids, classes+attrs+pseudo-classes, elements) for the heaviest compound."""
    best = (0, 0, 0)
    for part in sel.split(','):
        s = part.strip()
        if not s:
            continue
        s = re.sub(r'::[\w-]+', ' ', s)                       # pseudo-elements
        inner = ' '.join(re.findall(r':not\(([^)]*)\)', s))
        outer = re.sub(r':not\([^)]*\)', ' ', s)              # avoid double count
        ids = len(re.findall(r'#[\w-]+', outer)) + len(re.findall(r'#[\w-]+', inner))
        cls = (len(re.findall(r'\.[\w-]+', outer))
               + len(re.findall(r'\[[^\]]*\]', outer))
               + len(re.findall(r':[\w-]+', outer)))
        cls += (len(re.findall(r'\.[\w-]+', inner))
                + len(re.findall(r'\[[^\]]*\]', inner))
                + len(re.findall(r':[\w-]+', inner)))
        stripped = re.sub(r':not\([^)]*\)|\[[^\]]*\]|[.#][\w-]+|:[\w-]+', ' ', s)
        el = len([t for t in re.split(r'[\s>+~]+', stripped) if t and t != '*'])
        best = max(best, (ids, cls, el))
    return best


# ------------------------------------------------------------------- sources
def iter_sources():
    """Yield (relpath, mechanism, body_offset_in_file, css_body)."""
    styles = os.path.join(ROOT, 'src/styles')
    for dirpath, _d, files in os.walk(os.path.join(ROOT, 'src')):
        if '/test' in dirpath:
            continue
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, ROOT)
            if f.endswith('.css'):
                mech = 'A-global' if dirpath == styles else 'A-module'
                yield rel, mech, 0, open(p, encoding='utf-8').read()
            elif f.endswith('.tsx'):
                src = open(p, encoding='utf-8').read()
                for m in re.finditer(r'<style\s+jsx[^>]*>\s*\{\s*`', src):
                    i, depth, j = m.end(), 0, m.end()
                    while j < len(src):
                        c = src[j]
                        if c == '\\':
                            j += 2
                            continue
                        if src.startswith('${', j):
                            depth += 1
                            j += 2
                            continue
                        if c == '}' and depth:
                            depth -= 1
                            j += 1
                            continue
                        if c == '`' and not depth:
                            break
                        j += 1
                    yield rel, 'B-styledjsx', i, src[i:j]
                if "createElement( 'style' )" in src or "createElement('style')" in src:
                    for m in re.finditer(r'^const\s+(\w+)\s*=\s*`', src, re.M):
                        i = m.end()
                        j = src.find('`', i)
                        yield rel, 'C-injected', i, src[i:j]


def classnames_on(tags):
    """Classes worn by any of `tags`, each an (element, type-attribute-or-None) pair.

    This is the same pass that resolved `<select>`'s classes; the only thing batch 1.3c
    changed is that the element it looks for is an argument. The brace-aware walk to the
    closing `>` is load-bearing and not caution: an `=>` inside an onChange handler ends a
    naive scan early, and a tag whose className sits after the handler is then read as
    having none.
    """
    out = {}
    for dirpath, _d, files in os.walk(os.path.join(ROOT, 'src')):
        if '/test' in dirpath:
            continue
        for f in sorted(files):
            if not f.endswith('.tsx'):
                continue
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, ROOT)
            src = open(p, encoding='utf-8').read()
            for tag_name, want_type in tags:
                for m in re.finditer(r'<' + tag_name + r'(?=[\s/>])', src):
                    i, depth = m.end(), 0
                    while i < len(src):
                        c = src[i]
                        if c == '{':
                            depth += 1
                        elif c == '}':
                            depth -= 1
                        elif c == '>' and not depth:
                            break
                        i += 1
                    tag = src[m.start():i + 1]
                    # An <input> only counts for the set that asked for its type.
                    if want_type and not re.search(
                            r'type=(?:"' + want_type + r'"|\{\s*[\'"]'
                            + want_type + r'[\'"]\s*\})', tag):
                        continue
                    line = src.count('\n', 0, m.start()) + 1
                    for cm in re.finditer(
                            r'className=(?:"([^"]*)"|\{\s*[\'"]([^\'"]*)[\'"]\s*\})', tag):
                        for cls in (cm.group(1) or cm.group(2) or '').split():
                            if cls.startswith(('focus:', 'hover:')):
                                continue
                            out.setdefault(cls, []).append(f'{rel}:{line}')
    return out


SELECT_TOKEN = re.compile(r'(?<![\w-])select(?![\w-])')
INPUT_TOKEN = re.compile(r'(?<![\w-])input(?![\w-])')
# `input[type="checkbox"]` as a WHOLE TOKEN. The quote style and a trailing `i` flag are
# tolerated because a selector that means the same thing must count the same.
CHECKBOX_TOKEN = re.compile(r'(?<![\w-])input\[\s*type\s*=\s*[\'"]?checkbox[\'"]?[^\]]*\]')
RADIO_TOKEN = re.compile(r'(?<![\w-])input\[\s*type\s*=\s*[\'"]?radio[\'"]?[^\]]*\]')

# One element set per name. `token` matches the element written as a selector token; `tags`
# is what classnames_on() resolves classes from. The two must describe the SAME element or
# the two match modes count different things.
ELEMENTS = {
    'select': {'token': SELECT_TOKEN, 'tags': [('select', None)], 'extra': frozenset()},
    'checkbox': {'token': CHECKBOX_TOKEN, 'tags': [('input', 'checkbox')],
                 'extra': CONTROL_BOX_PROPS},
    'radio': {'token': RADIO_TOKEN, 'tags': [('input', 'radio')],
              'extra': CONTROL_BOX_PROPS},
}
DEFAULT_ELEMENTS = ['select']


def scan(elements=None):
    elements = list(elements or DEFAULT_ELEMENTS)
    for name in elements:
        if name not in ELEMENTS:
            raise SystemExit(f'unknown element set: {name} '
                             f'(known: {",".join(sorted(ELEMENTS))})')
    tokens = [ELEMENTS[n]['token'] for n in elements]
    tags = [t for n in elements for t in ELEMENTS[n]['tags']]
    extra = frozenset().union(*[ELEMENTS[n]['extra'] for n in elements])
    classes = classnames_on(tags)
    hits = []
    for rel, mech, off, body in iter_sources():
        clean = mask_interpolation(blank_css_comments(body))
        full = open(os.path.join(ROOT, rel), encoding='utf-8').read()
        for sel, decls, o in rule_sets(clean):
            sel_one = ' '.join(sel.split())
            if not sel_one or len(sel_one) > 4000:
                continue
            mode = None
            matched = []
            if any(t.search(sel_one) for t in tokens):
                mode = 'element'
            else:
                matched = [c for c in classes
                           if re.search(r'\.' + re.escape(c) + r'(?![\w-])', sel_one)]
                if matched:
                    mode = 'class'
            if not mode:
                continue
            props = box_props(decls, extra)
            if not props:
                continue
            # o points just past the previous '}'. Advance to the first
            # non-whitespace character so the reported line is the SELECTOR's.
            k = o
            while k < len(clean) and clean[k] in ' \t\r\n':
                k += 1
            line = full.count('\n', 0, off + k) + 1
            hits.append(dict(file=rel, line=line, mech=mech, mode=mode,
                             sel=sel_one, classes=matched, props=props,
                             spec=specificity(sel_one),
                             decls=' '.join(decls.split())))
    hits.sort(key=lambda h: (h['file'], h['line']))
    for h in hits:
        h['geometry'] = bool(set(h['props']) & GEOMETRY)
        # A PAIRING rule names BOTH an input and a select as whole tokens in one selector
        # list, so form-controls.css reaches one half of it and not the other. The count is
        # the producer of design 4.3's divergence table, and a twenty-third means a new
        # pairing exists whose accept-versus-rewrite decision has not been taken.
        #
        # ONLY MEANINGFUL FOR THE SELECT SET, which is why it is gated on it rather than
        # computed and quietly ignored: every selector in the checkbox/radio set names an
        # `input` by construction, so the flag would be true for every geometry hit that
        # also happened to mention a select and false for the rest, which is not the
        # question the pairing count asks.
        h['pairing'] = bool('select' in elements and h['geometry']
                            and SELECT_TOKEN.search(h['sel'])
                            and INPUT_TOKEN.search(h['sel']))
    return hits


# The planted sample. It exercises the two parsing details a simpler scan loses: a styled-jsx
# template whose `${...}` interpolation would otherwise terminate the rule early, and a
# class-only selector that never writes the word `select`. Reported through the SAME functions
# the real scan uses, so it cannot pass while the real scan is broken.
PLANT = """
  .ui-planted{border:1px solid ${colors.border};border-radius:9px;padding:4px 8px}
  .ui-planted:focus{box-shadow:${shadow.focus}}
  .ui-untouched{color:#333}
"""


def self_test():
    clean = mask_interpolation(blank_css_comments(PLANT))
    reported = []
    for sel, decls, _o in rule_sets(clean):
        props = box_props(decls)
        if props:
            reported.append({'sel': ' '.join(sel.split()),
                             'props': sorted(props),
                             'geometry': sorted(set(props) & GEOMETRY)})
    return {
        'sample': ' '.join(PLANT.split()),
        'reported': reported,
        # The declaration AFTER the interpolation must survive. If `${...}` were read as CSS
        # braces, `border-radius` and `padding` would be lost and this list would be shorter.
        'interpolated_rule_keeps_later_declarations':
            any(r['sel'] == '.ui-planted' and 'border-radius' in r['props']
                and 'padding' in r['props'] for r in reported),
        'class_only_selector_reported':
            any(r['sel'] == '.ui-planted:focus' for r in reported),
        'non_box_rule_ignored':
            not any(r['sel'] == '.ui-untouched' for r in reported),
    }


def summarise(hits):
    geo = [h for h in hits if h['geometry']]
    mech = {}
    for name in ('A-global', 'A-module', 'B-styledjsx', 'C-injected'):
        sub = [h for h in hits if h['mech'] == name]
        subgeo = [h for h in sub if h['geometry']]
        mech[name] = {
            'ruleSets': len(sub), 'files': len({h['file'] for h in sub}),
            'geometryRuleSets': len(subgeo),
            'geometryFiles': len({h['file'] for h in subgeo}),
        }
    return {
        'ruleSets': len(hits),
        'files': len({h['file'] for h in hits}),
        'geometryRuleSets': len(geo),
        'geometryFiles': len({h['file'] for h in geo}),
        'pairings': len([h for h in hits if h['pairing']]),
        'matchModes': {'element': len([h for h in hits if h['mode'] == 'element']),
                       'class': len([h for h in hits if h['mode'] == 'class'])},
        'mechanisms': mech,
    }


COUNTING_RULE = (
    'one rule set = one {{...}} block, counted once regardless of how many compounds its '
    'selector list holds or how many at-rules it is nested inside; a block counts when its '
    'selector names {subject} as a whole token, or names a class that appears as a '
    'className literal on one, AND its body sets at least one box property. Geometry is the '
    'subset whose body sets border, border-width, border-radius, padding, height, '
    'min-height, appearance or -webkit-appearance.'
)
BLIND_SPOT = (
    'A BARE `input` selector is invisible to this counting rule and reaches every type. '
    'Seven matter and are pinned by line in design.md 1.14c rather than by this scan: '
    'tokens.css:420, :434, :440, inner-pages.css:279, :1999, :2021 and '
    'MCPConnections.module.css:14. tokens.css:420 declares padding 10px 12px on every '
    'checkbox and radio in the app, which is why form-controls.css must declare padding: 0.'
)


def parse_elements(argv):
    """--elements a,b. Returns the element-set names for the HUMAN report."""
    for i, a in enumerate(argv):
        if a == '--elements':
            if i + 1 >= len(argv):
                raise SystemExit('--elements needs a comma-separated list, e.g. '
                                 '--elements checkbox,radio')
            return [p.strip() for p in argv[i + 1].split(',') if p.strip()]
        if a.startswith('--elements='):
            return [p.strip() for p in a.split('=', 1)[1].split(',') if p.strip()]
    return list(DEFAULT_ELEMENTS)


def main():
    argv = sys.argv[1:]
    if '--json' in argv:
        # BOTH SETS FROM ONE INVOCATION. The fixture is one committed file and two scans in
        # two files would drift apart - which is the whole reason assertion 10 shares
        # assertion 3's producer instead of getting a second scanner. The select set keeps
        # the top-level keys it has always had, so the assertions written against it do not
        # move; the checkbox/radio set arrives alongside under `checkboxRadio`.
        sel = scan(['select'])
        cbr = scan(['checkbox', 'radio'])
        json.dump({
            'generator': 'scripts/census_control_skins.py --json',
            'countingRule': COUNTING_RULE.format(subject='`select`'),
            'summary': summarise(sel),
            'files': sorted({h['file'] for h in sel}),
            'selfTest': self_test(),
            'hits': sel,
            'checkboxRadio': {
                'elements': ['checkbox', 'radio'],
                'countingRule': COUNTING_RULE.format(
                    subject='`input[type="checkbox"]` or `input[type="radio"]`'),
                'blindSpot': BLIND_SPOT,
                'summary': summarise(cbr),
                'files': sorted({h['file'] for h in cbr}),
                'hits': cbr,
            },
        }, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write('\n')
        return 0

    elements = parse_elements(argv)
    hits = scan(elements)
    summary = summarise(hits)
    geo = [h for h in hits if h['geometry']]
    print(f'ELEMENT SET: {",".join(elements)}')
    print(f'TOTAL rule sets skinning {"/".join(elements)}: {len(hits)} '
          f'in {len({h["file"] for h in hits})} files')
    print(f'  of which touch GEOMETRY (border/radius/padding/height/appearance): '
          f'{len(geo)} in {len({h["file"] for h in geo})} files')
    for mech in ('A-global', 'A-module', 'B-styledjsx', 'C-injected'):
        sub = [h for h in hits if h['mech'] == mech]
        print(f'  {mech:14s} {len(sub):3d} rule sets  '
              f'{len({h["file"] for h in sub}):2d} files')
    print()
    for h in hits:
        imp = ','.join(f'{p}!' if i else p for p, i in sorted(h['props'].items()))
        print(f'{h["file"]}:{h["line"]}  [{h["mech"]}/{h["mode"]}] spec={h["spec"]}')
        print(f'    SEL  {h["sel"][:170]}')
        if h['classes']:
            print(f'    CLS  {",".join(h["classes"])}')
        print(f'    PROP {imp}')
        print(f'    DECL {h["decls"][:260]}')
    print()
    print(f'MATCH MODES: {summary["matchModes"]["element"]} on the element token, '
          f'{summary["matchModes"]["class"]} on a resolved class')
    if 'select' in elements:
        print(f'PAIRING rule sets (one selector list naming both an input and a select): '
              f'{summary["pairings"]}')
    else:
        print('PAIRING is not computed for this element set - see the note in scan().')
        print()
        print('BLIND SPOT: ' + BLIND_SPOT)
    st = self_test()
    print('SELF-TEST on the planted sample: '
          + ('PASS' if all(v is True for k, v in st.items() if k != 'sample'
                           and isinstance(v, bool)) else 'FAIL'))
    return 0


sys.exit(main())
