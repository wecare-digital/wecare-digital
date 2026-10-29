"""Run every customer-commerce source/package check and write one diagnostic report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def run(command: list[str]) -> dict:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        'command': command,
        'returnCode': completed.returncode,
        'stdout': completed.stdout,
        'stderr': completed.stderr,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        shutil.rmtree(args.output)

    commands = [
        [sys.executable, str(HERE / 'verify.py')],
        [sys.executable, str(HERE / 'verify_oauth.py')],
        [sys.executable, str(HERE / 'verify_auth_isolation.py')],
        [
            sys.executable,
            str(HERE / 'prepare_release.py'),
            '--output',
            str(args.output),
        ],
        [
            sys.executable,
            str(HERE / 'verify_release.py'),
            str(args.output / 'customer-commerce-runtime.zip'),
        ],
    ]

    results = []
    success = True
    for command in commands:
        result = run(command)
        results.append(result)
        if result['returnCode'] != 0:
            success = False
            break

    report = {
        'schemaVersion': 'customer-commerce-validation-v1',
        'success': success,
        'results': results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if not success:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
