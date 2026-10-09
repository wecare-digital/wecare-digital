"""Prevent unrelated shared-code/docs changes from redeploying the SEO Lambda."""
from pathlib import PurePosixPath
import re
import subprocess
import sys


def packaged_source(path: str) -> bool:
    file = PurePosixPath(path)
    if path in ('amplify/functions/seo_tools_handler.py',
                'amplify/functions/shared/static_knowledge_base.py'):
        return True
    return (file.suffix == '.py' and str(file.parent) in (
        'amplify/functions/operations/seo-tools',
        'amplify/functions/shared/lambda_utils'))


def main(base: str, head: str) -> None:
    if not all(re.fullmatch(r'[0-9a-f]{40}', value) for value in (base, head)):
        raise ValueError('Expected immutable commit SHAs')
    if base == '0' * 40:
        raise ValueError('No previous revision; explicit workflow dispatch required')
    changed = subprocess.check_output(
        ['git', 'diff', '--name-only', '-z', base, head], text=True).split('\0')
    print('deploy=' + str(any(packaged_source(path) for path in changed)).lower())


if __name__ == '__main__':
    main(*sys.argv[1:])
