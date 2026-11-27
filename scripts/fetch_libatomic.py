#!/usr/bin/env python3
"""Provide libatomic.so.1 for Node 26 on the Amplify build image, without root.

WHY
---
Official Node 26 Linux binaries link libatomic.so.1. The Amplify Amazon Linux 2023 build image
does not ship it, so the first `node` call exits 127 ("error while loading shared libraries:
libatomic.so.1", jobs 779-786). The build user is not root, so `dnf install libatomic` fails
(job 786: "This command has to be run with superuser privileges").

WHAT
----
Downloads ONE pinned Amazon Linux 2023 package (content-addressed URL), refuses it unless its
SHA-256 matches, extracts only `usr/lib64/libatomic.so.1*` into OUTPUT_DIR, and prints
OUTPUT_DIR. The caller prepends that to LD_LIBRARY_PATH. Nothing is installed system-wide.

The rpm payload is a zstd-compressed cpio archive. Python 3.14+ decompresses it natively; on an
older interpreter (the Amplify image runs Python 3.10) `rpm2cpio`, which every AL2023 image has
because dnf depends on it, does the decompression. The cpio parsing is standard library only.

Usage: python3 scripts/fetch_libatomic.py OUTPUT_DIR
"""
from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# gcc 11.5.0 is the Amazon Linux 2023 system compiler, so this is the libatomic the image's own
# toolchain would install. Resolved from the AL2023 core repo primary.xml on 2026-11-28.
RPM_URL = ("https://cdn.amazonlinux.com/al2023/blobstore/"
           "d117b0d5a62e90b373479687c71d5dddbdec98d92744a06d52347430de79df6c/"
           "libatomic-11.5.0-5.amzn2023.0.5.x86_64.rpm")
RPM_SHA256 = "d117b0d5a62e90b373479687c71d5dddbdec98d92744a06d52347430de79df6c"
WANTED_PREFIX = "usr/lib64/libatomic.so.1"


def fail(message: str) -> None:
    print(f"fetch_libatomic: {message}", file=sys.stderr)
    raise SystemExit(1)


def payload_offset(rpm: bytes) -> int:
    """Byte offset of the compressed payload: after the lead, signature and main headers."""
    if rpm[:4] != b"\xed\xab\xee\xdb":
        fail("not an rpm file")

    def header_end(offset: int) -> int:
        if rpm[offset:offset + 3] != b"\x8e\xad\xe8":
            fail("malformed rpm header")
        entries, size = struct.unpack(">II", rpm[offset + 8:offset + 16])
        return offset + 16 + 16 * entries + size

    signature_end = header_end(96)
    signature_end = (signature_end + 7) // 8 * 8  # the signature header is 8-byte aligned
    return header_end(signature_end)


def cpio_stream(rpm_path: Path, rpm: bytes) -> bytes:
    compressed = rpm[payload_offset(rpm):]
    try:
        from compression import zstd  # Python 3.14+
        return zstd.decompress(compressed)
    except ImportError:
        pass
    tool = shutil.which("rpm2cpio")
    if not tool:
        fail("need Python 3.14+ or rpm2cpio to decompress the zstd payload")
    return subprocess.run([tool, str(rpm_path)], check=True, capture_output=True).stdout


def extract(cpio: bytes, output: Path) -> list[str]:
    """Parse a newc cpio archive and write only the libatomic entries."""
    written, offset = [], 0
    while True:
        magic = cpio[offset:offset + 6]
        if magic not in (b"070701", b"070702"):
            fail("unexpected cpio format")
        fields = [int(cpio[offset + 6 + 8 * i: offset + 14 + 8 * i], 16) for i in range(13)]
        mode, file_size, name_size = fields[1], fields[6], fields[11]
        name_start = offset + 110
        name = cpio[name_start:name_start + name_size - 1].decode()
        data_start = (name_start + name_size + 3) // 4 * 4
        data = cpio[data_start:data_start + file_size]
        offset = (data_start + file_size + 3) // 4 * 4
        if name == "TRAILER!!!":
            return written
        relative = name.lstrip("./")
        if not relative.startswith(WANTED_PREFIX) or ".." in Path(relative).parts:
            continue
        target = output / Path(relative).name
        kind = mode & 0o170000
        if kind == 0o120000:  # symlink: libatomic.so.1 -> libatomic.so.1.2.0
            link = data.decode()
            if "/" in link:
                fail(f"refusing symlink outside the output dir: {link}")
            if target.is_symlink() or target.exists():
                target.unlink()
            os.symlink(link, target)
        elif kind == 0o100000:
            target.write_bytes(data)
            target.chmod(0o755)
        else:
            continue
        written.append(target.name)


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: fetch_libatomic.py OUTPUT_DIR")
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        rpm_path = Path(tmp) / "libatomic.rpm"
        with urllib.request.urlopen(RPM_URL, timeout=60) as response:
            rpm = response.read()
        digest = hashlib.sha256(rpm).hexdigest()
        if digest != RPM_SHA256:
            fail(f"sha256 mismatch: got {digest}")
        rpm_path.write_bytes(rpm)
        written = extract(cpio_stream(rpm_path, rpm), output)
    if "libatomic.so.1" not in written:
        fail(f"libatomic.so.1 not found in package (got {written})")
    print(output)


if __name__ == "__main__":
    main()
