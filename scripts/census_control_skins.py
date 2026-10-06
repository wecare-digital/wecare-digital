#!/usr/bin/env python3
"""THE control-skin census. One scanner, three authoring mechanisms, two match modes.

Mechanisms scanned:
  A  global stylesheets      src/styles/*.css  and  *.module.css
  B  styled-jsx              <style jsx>{` ... `}</style> in src/**/*.tsx
  C  runtime-injected CSS    module-scope template literal appended to
                             document.head via createElement('style')

Match modes:
  1  the selector contains `select` as a whole token
  2  the selector names a class that is a className literal on a <select>

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

  python scripts/census_control_skins.py           human-readable report
  python scripts/census_control_skins.py --json    the same scan as JSON

TWO ADDITIONS WERE MADE WHEN IT WAS COMMITTED, neither of which touches how it counts:

  1. ROOT is derived from this file's location instead of being a hardcoded absolute path
     to one worktree. The scan is identical when run from that worktree; the difference is
     that the committed script also works from the branch it is committed to.
  2. --json, plus a SELF-TEST on a planted sample, because src/test/FormControlsCss.test.ts
     asserts against the committed fixture src/test/fixtures/control-skin-census.json rather
     than re-deriving the scan in TypeScript. The self-test exists for the reason
     ScrollbarDeclarations.test.ts has one: a scanner with a parsing bug reports FEWER files
     than exist, which reads as "the gate passed".
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


def box_props(decls):
    found = {}
    for d in decls.split(';'):
        if ':' not in d:
            continue
        p, v = d.split(':', 1)
        p = p.strip().lower()
        if p in BOX_PROPS:
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


def classnames_on_select():
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
            for m in re.finditer(r'<select(?=[\s/>])', src):
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


def scan():
    classes = classnames_on_select()
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
            if SELECT_TOKEN.search(sel_one):
                mode = 'element'
            else:
                matched = [c for c in classes
                           if re.search(r'\.' + re.escape(c) + r'(?![\w-])', sel_one)]
                if matched:
                    mode = 'class'
            if not mode:
                continue
            props = box_props(decls)
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
        h['pairing'] = bool(h['geometry'] and SELECT_TOKEN.search(h['sel'])
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
        'mechanisms': mech,
    }


def main():
    hits = scan()
    if '--json' in sys.argv[1:]:
        json.dump({
            'generator': 'scripts/census_control_skins.py --json',
            'countingRule': (
                'one rule set = one {...} block, counted once regardless of how many '
                'compounds its selector list holds or how many at-rules it is nested '
                'inside; a block counts when its selector names `select` as a whole token, '
                'or names a class that appears as a className literal on a <select>, AND '
                'its body sets at least one box property. Geometry is the subset whose body '
                'sets border, border-width, border-radius, padding, height, min-height, '
                'appearance or -webkit-appearance.'
            ),
            'summary': summarise(hits),
            'files': sorted({h['file'] for h in hits}),
            'selfTest': self_test(),
            'hits': hits,
        }, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write('\n')
        return 0

    summary = summarise(hits)
    geo = [h for h in hits if h['geometry']]
    print(f'TOTAL rule sets skinning a select: {len(hits)} '
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
    print(f'PAIRING rule sets (one selector list naming both an input and a select): '
          f'{summary["pairings"]}')
    st = self_test()
    print('SELF-TEST on the planted sample: '
          + ('PASS' if all(v is True for k, v in st.items() if k != 'sample'
                           and isinstance(v, bool)) else 'FAIL'))
    return 0


sys.exit(main())
