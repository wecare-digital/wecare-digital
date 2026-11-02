"""Stage deterministic checkout Lambda zips; NEVER publish or move a live alias.

This is a narrowly scoped build helper. It packages the exact reviewed source
that Amplify already cloned and writes three versioned binaries + sha manifest.
Only a separate explicit, revision-checked AWS release promotes any bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from scripts import deploy_all_lambdas as deploy

TARGETS = ("wecare-commerce", "wecare-checkout", "wecare-invoice-engine")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise SystemExit("Refusing artifact without a pinned 40-hex source commit")
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    specs = {s.name: s for s in deploy.SPECS if s.name in TARGETS}
    if set(specs) != set(TARGETS):
        raise SystemExit("Checkout package spec missing")
    summary = {"sourceCommit": args.commit, "packages": {}}
    for name in TARGETS:
        data, members = deploy.build_zip(specs[name])
        if "handler.py" not in members or not any(
                key.endswith("ecommerce/unified_pricing.py") for key in members):
            raise SystemExit("Checkout package missing handler/pricing module")
        sha = hashlib.sha256(data).hexdigest()
        path = out / (name + ".zip")
        path.write_bytes(data)
        summary["packages"][name] = {
            "file": path.name, "sha256": sha,
            "bytes": len(data), "members": len(members),
        }
    if summary["packages"]["wecare-commerce"]["sha256"] != (
            summary["packages"]["wecare-checkout"]["sha256"]):
        raise SystemExit("Commerce and checkout must be byte-identical")
    (out / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
