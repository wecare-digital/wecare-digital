#!/usr/bin/env python3
"""Keep the unpatched braces advisory visible and notice upstream remediation."""
import argparse
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADVISORY = 'GHSA-vfj7-8cjw-p6xm'


def inspect_locks(root=ROOT):
    copies = []
    for relative in ('package-lock.json', 'amplify/package-lock.json'):
        packages = json.loads((root / relative).read_text())['packages']
        for name, meta in packages.items():
            if name.endswith('/braces'):
                copies.append({'lockfile': relative, 'path': name, 'version': meta['version'],
                               'devOnly': bool(meta.get('dev'))})
    return copies


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-upstream', action='store_true')
    args = parser.parse_args()
    report = {'advisory': ADVISORY, 'copies': inspect_locks(),
              'status': 'OPEN; no upstream patch at review, do not dismiss'}
    if args.check_upstream:
        request = urllib.request.Request('https://api.github.com/advisories/' + ADVISORY,
                                         headers={'User-Agent': 'wecare-advisory-check'})
        with urllib.request.urlopen(request, timeout=20) as response:
            advisory = json.load(response)
        patches = [v.get('first_patched_version') for v in advisory['vulnerabilities']
                   if v['package']['name'] == 'braces' and v['package']['ecosystem'] == 'npm']
        report['upstreamPatchedVersions'] = patches
        print(json.dumps(report, indent=2))
        return 1 if any(patches) else 0
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
