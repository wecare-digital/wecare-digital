"""Build the dedicated public reader package without AWS access or admin modules."""
from __future__ import annotations

import argparse
import io
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'amplify/functions/operations/blog-public'
MEMBERS = ('handler.py', 'storage.py', 'faq.py')


def package() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for member in MEMBERS:
            info = zipfile.ZipInfo(member, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (SOURCE / member).read_bytes())
    return buffer.getvalue()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_bytes(package())
    print(f'Built dedicated public blog reader: {args.output.stat().st_size} bytes')
