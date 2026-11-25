#!/usr/bin/env python3
"""Run provider-free release checks shared by GitHub Verify and Amplify."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
CHECKS = (
    "check_gitignore_safety.cjs",
    "check_action_ui_contracts.cjs",
    "check_production_data_safety.cjs",
    "check_payflow_release_safety.cjs",
    "check_vayulok_cost_and_map.cjs",
)


def main() -> int:
    files = sorted((ROOT / "amplify/functions").rglob("*.py"))
    if not files:
        raise SystemExit("No Lambda sources were found")
    for path in files:
        if "__pycache__" not in path.parts:
            compile(path.read_bytes(), str(path.relative_to(ROOT)), "exec")
    print(f"Compiled {len(files)} Python sources without imports.", flush=True)
    for name in CHECKS:
        print(f"== {name} ==", flush=True)
        subprocess.run(["node", str(ROOT / "scripts" / name)], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
