#!/usr/bin/env python3
import argparse, csv, re, zipfile, html
from html.parser import HTMLParser
from pathlib import Path

KNOWN_SOURCE_TERMS = [
    'landmark', 'landmark education', 'landmark forum', 'landmark worldwide',
    'werner erhard', 'werner', 'erhard', 'lucent', 'lucent technologies', 'patrick',
    'est training', 'the forum', 'landmark forum', 'leadership course', 'six day course',
    'curriculum for living', 'the work of transformation', 'work of transformation',
    'world to word fit', 'word to world fit', 'who we really are'
]
SOURCE_SCAFFOLD_PATTERNS = [
    r'\bsource note\b', r'\badapted from\b', r'\bthe source\b', r'\bsource article\b',
    r'\bsource post\b', r'\bthe book says\b', r'\bthe author says\b', r'\bin this book\b',
    r'\baccording to the source\b', r'\baccording to the author\b',
    r'\bi am indebted to\b', r'\bquoted by\b', r'\binspired this conversation\b',
    r'\bw\s*erner\s+e\s*rhard\b', r'\bw\s*erner\b'
]
PLACEHOLDER_PATTERNS = [
    r'\bnot yet located\b.*\bnot yet dated\b.*\bcoming soon\b'
]
PLACEHOLDER_TITLES = {
    'new one', 'placeholder', 'placeholder ii', 'placeholder iii',
    'preferred conversations', 'work in progress'
}
EVIDENCE_PATTERNS = [
    r'\bfolklore\b', r'\boften told\b', r'\bexperiment(?:s|al)?\b',
    r'\bstud(?:y|ies) (?:show|shows|showed|found|find)\b', r'\bresearch (?:shows|showed|found|finds)\b'
]
PERSONAL_PATTERNS = [
    r'\bmy (?:mother|father|mom|dad|parents|wife|husband|spouse|partner|girlfriend|boyfriend|lover|ex|son|daughter|children|brother|sister|siblings|aunt|uncle|friend|teacher|mentor|boss|colleague|family|marriage|home|school|office|childhood|private life)\b',
    r'\bi (?:grew up|was born|was raised|worked at|studied at|met|married|divorced|remember when|learned from)\b'
]
RISK_PATTERNS = {
    'health': [r'\b(?:depression|depressed|anxiety|therapy|therapist|diagnosis|disease|cancer|medicine|medical|doctor|pain|health|healing|trauma)\b'],
    'political': [r'\b(?:president|election|government|politic|democrat|republican|congress|senate|war|terroris|wall street|white house)\w*\b'],
    'legal_financial': [r'\b(?:lawyer|legal|court|lawsuit|bankruptcy|mortgage|loan|debt|money|financial|finance|tax|estate|will|trust)\w*\b'],
    'religion': [r'\b(?:god|religion|religious|spiritual|zen|buddh|hindu|christ|jesus|church|monk|guru|soul|enlightenment)\w*\b']
}

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.skip=0
    def handle_starttag(self, tag, attrs):
        if tag.lower() in {'script','style','noscript'}: self.skip += 1
        elif tag.lower() in {'p','br','div','li','h1','h2','h3','h4','h5','h6'} and not self.skip: self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag.lower() in {'script','style','noscript'} and self.skip: self.skip -= 1
        elif tag.lower() in {'p','div','li','h1','h2','h3','h4','h5','h6'} and not self.skip: self.parts.append('\n')
    def handle_data(self, data):
        if not self.skip: self.parts.append(data)

def extract_text(raw):
    p=TextExtractor(); p.feed(raw)
    text=html.unescape(' '.join(p.parts))
    text=re.sub(r'\s+',' ',text).strip()
    return text

def yn(v): return str(v or '').strip().upper() == 'YES'
def sval(v): return str(v or '').strip()
def compile_any(patterns): return [re.compile(p, re.I) for p in patterns]
SRC_RE=compile_any(SOURCE_SCAFFOLD_PATTERNS)
PERS_RE=compile_any(PERSONAL_PATTERNS)
PLACEHOLDER_RE=compile_any(PLACEHOLDER_PATTERNS)
EVIDENCE_RE=compile_any(EVIDENCE_PATTERNS)
RISK_RE={k:compile_any(v) for k,v in RISK_PATTERNS.items()}

def article_text(row, text):
    title=sval(row.get('original_title'))
    if title:
        low=text.lower(); needle=title.lower(); idx=low.find(needle)
        if idx >= 0:
            text=text[idx+len(title):]
    text=re.sub(r'^.*?Inspired By The Ideas Of Werner Erhard And More\s*', '', text, flags=re.I)
    return text.strip()

def classify(row, text):
    text=article_text(row, text)
    route=sval(row.get('title_pass_route')).upper()
    revised=sval(row.get('revised_decision')).upper()
    hist=sval(row.get('historical_decision')).upper()
    titleopp=sval(row.get('title_level_opportunity')).upper()
    sim=float(row.get('title_similarity') or 0)
    pubname=yn(row.get('public_name_dependency'))
    program=yn(row.get('program_dependency'))
    research=sval(row.get('research_requirement'))
    lower=' '+text.lower()+' '
    source_terms=sorted({term.strip() for term in KNOWN_SOURCE_TERMS if term in lower})
    source_scaffold=any(r.search(text) for r in SRC_RE)
    personal=any(r.search(text) for r in PERS_RE)
    placeholder=(sval(row.get('original_title')).lower() in PLACEHOLDER_TITLES or (len(text) < 1000 and any(r.search(text) for r in PLACEHOLDER_RE)))
    evidence_claim=any(r.search(text) for r in EVIDENCE_RE)
    fresh_risks=[]
    for k, regs in RISK_RE.items():
        if any(r.search(text) for r in regs): fresh_risks.append(k)
    overlap_strong = hist=='MERGE' or revised.startswith('MERGE') or route=='MERGE' or titleopp=='HIGH OVERLAP' or sim >= 0.62
    overlap_medium = titleopp=='POSSIBLE OVERLAP' or sim >= 0.48
    source_exposure_risk = pubname or program or bool(source_terms) or source_scaffold
    personal_risk = personal
    factual_risk = bool(research) or evidence_claim
    if overlap_strong:
        bucket='LIKELY_EXISTING_COVERAGE'
    elif placeholder:
        bucket='NO_DISTINCT_ARTICLE'
    elif personal_risk:
        bucket='PERSONAL_REFERENCE_REWORK'
    elif source_exposure_risk:
        bucket='SOURCE_REWORK'
    elif factual_risk:
        bucket='FACT_CHECK_REQUIRED'
    elif overlap_medium:
        bucket='DEDUPE_REVIEW'
    elif titleopp=='APPARENTLY DISTINCT':
        bucket='CANDIDATE_NEW_ARTICLE'
    else:
        bucket='DEEP_REVIEW'
    return bucket, source_terms, fresh_risks, source_scaffold, personal, placeholder, evidence_claim

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--inventory', required=True)
    ap.add_argument('--archive', required=True)
    ap.add_argument('--pending', required=True)
    ap.add_argument('--out', required=True)
    args=ap.parse_args()
    with open(args.inventory, newline='', encoding='utf-8-sig') as f:
        inv={r['source_file']:r for r in csv.DictReader(f)}
    with open(args.pending, newline='', encoding='utf-8-sig') as f:
        pending=list(csv.DictReader(f))
    out=[]
    with zipfile.ZipFile(args.archive) as z:
        names=set(z.namelist())
        for p in pending:
            sf=p['source_file']
            row=inv.get(sf,{})
            raw=''
            if sf in names:
                raw=z.read(sf).decode('utf-8','ignore')
            text=extract_text(raw)
            bucket, source_terms, fresh_risks, source_scaffold, personal, placeholder, evidence_claim=classify(row,text)
            out.append({
                'pending_position':p.get('pending_position',''),
                'archive_index':p.get('archive_index',''),
                'source_file':sf,
                'original_title':p.get('original_title',''),
                'original_date':p.get('original_date',''),
                'approx_words':row.get('approx_words',''),
                'machine_bucket':bucket,
                'title_pass_route':row.get('title_pass_route',''),
                'revised_decision':row.get('revised_decision',''),
                'title_level_opportunity':row.get('title_level_opportunity',''),
                'title_similarity':row.get('title_similarity',''),
                'conceptual_overlap':row.get('conceptual_overlap',''),
                'overlap_slug':row.get('overlap_slug',''),
                'public_name_dependency':row.get('public_name_dependency',''),
                'program_dependency':row.get('program_dependency',''),
                'research_requirement':row.get('research_requirement',''),
                'fresh_risk_terms':';'.join(fresh_risks),
                'known_source_terms':';'.join(source_terms),
                'generic_source_scaffold':'YES' if source_scaffold else 'NO',
                'personal_biography_signal':'YES' if personal else 'NO',
                'placeholder_signal':'YES' if placeholder else 'NO',
                'evidence_claim_signal':'YES' if evidence_claim else 'NO',
                'source_text_chars':len(text),
                'automation_note':'MECHANICAL TRIAGE ONLY — not editorial approval; never auto-mark READY_TO_PUBLISH.'
            })
    fields=list(out[0].keys()) if out else []
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(out)
    from collections import Counter
    c=Counter(x['machine_bucket'] for x in out)
    print('rows',len(out))
    for k,v in c.most_common(): print(k,v)

if __name__=='__main__':
    main()
