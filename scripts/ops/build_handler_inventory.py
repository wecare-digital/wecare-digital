#!/usr/bin/env python3
"""Build a backend handler/function inventory PURELY from committed repo data.

OFFLINE / REPO-ONLY. This script does NOT import boto3 and makes NO network or
AWS call of any kind. Every input is a file already committed to this repository:

  (a) scripts/deploy_all_lambdas.py  - the authoritative SPECS table mapping a
      live function name to its handler source under amplify/functions/** plus
      packaging flags. Parsed with ast (NOT imported) because that module
      imports boto3 at load time and we must stay offline.
  (b) amplify/functions/**           - walked to enumerate every .py handler and
      the shared/ (lambda_utils) modules, distinguishing standalone-deployable
      handlers from shared modules packaged INTO functions.
  (c) os.environ references in handlers - collected as env KEY NAMES ONLY. The
      values of those variables are never read, never resolved, never emitted.
  (d) config/lambda-env-manifest.json - the committed live function -> env-key map.
      Only the KEY names are copied into the report, never the recorded values.
  (e) config/backend-retirement.json  - retired functions / routes / tables and
      the retained shared module, used to flag retired entries.

The companion live-AWS registry generator (scripts/ops/generate_backend_registry.py)
stays BLOCKED and is NOT used here. This tool is the SAFE / OFFLINE subset: it
classifies each resource (script-managed vs cdk-cloudformation) from repo data
BEFORE any pipeline change, per the audit section 7 release standards.

The default output path is a gitignored scratch path (.scratch/) because the
report, while it emits only key names here, is an operational artifact that must
not be committed. The script refuses to write outside .scratch/ unless an
explicit --out is given, and prints a "do not commit" reminder.

Usage:
    python3 scripts/ops/build_handler_inventory.py            # writes .scratch/backend-handler-inventory.json
    python3 scripts/ops/build_handler_inventory.py --print    # also print to stdout
    python3 scripts/ops/build_handler_inventory.py --out .scratch/x.json
    python3 scripts/ops/build_handler_inventory.py --expected-account 123  # accepted, UNUSED (no AWS)
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# This script is deliberately network-free. boto3 must never be imported here;
# if a future edit adds it, this guard fails loudly rather than quietly reaching
# out to AWS.
assert "boto3" not in sys.modules, "build_handler_inventory must stay offline (boto3 imported)"

ROOT = Path(__file__).resolve().parents[2]
FUNCTIONS = ROOT / "amplify" / "functions"
DEPLOY_ALL = ROOT / "scripts" / "deploy_all_lambdas.py"
ENV_MANIFEST = ROOT / "config" / "lambda-env-manifest.json"
RETIREMENT = ROOT / "config" / "backend-retirement.json"

DOMAINS = ["ai", "auth", "core", "ecommerce", "edge", "messaging",
           "operations", "payments", "shared"]

# Resources whose shell/role/table are owned by amplify/backend.ts (Amplify Gen 2
# CDK) or infra/*.yml (CloudFormation), independent of the imperative code deploy.
# The log-retention enforcer is a standalone CloudFormation stack
# (infra/cloudwatch-retention-enforcer.yml) and is not in the SPECS code-deploy map.
CDK_CLOUDFORMATION_FUNCTIONS = {
    "wecare-log-retention-enforcer": "infra/cloudwatch-retention-enforcer.yml",
}

# os.environ.get("KEY") / os.environ["KEY"] / os.getenv("KEY"). We capture the
# KEY name only; the matched group never includes the default value.
_ENV_KEY_RE = re.compile(
    r"""os\.(?:environ\.get|getenv)\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""
    r"""|os\.environ\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]"""
)


def _literal(node: ast.AST) -> Any:
    """Best-effort literal eval of an AST node, tolerant of names/attributes.

    Names and attributes (e.g. PILLOW_LAYER_ARN) are returned as a symbolic
    "<NAME>" string so we record THAT a layer is required without resolving the
    constant, keeping zero ARNs in our output.
    """
    try:
        return ast.literal_eval(node)
    except Exception:
        if isinstance(node, ast.Name):
            return f"<{node.id}>"
        if isinstance(node, ast.Attribute):
            return f"<{node.attr}>"
        if isinstance(node, (ast.List, ast.Tuple)):
            return [_literal(e) for e in node.elts]
        return None


def parse_specs(deploy_all_path: Path) -> List[Dict[str, Any]]:
    """Extract the SPECS Spec(...) entries via AST (no import, no boto3)."""
    tree = ast.parse(deploy_all_path.read_text(encoding="utf-8"))
    specs: List[Dict[str, Any]] = []

    # Find the `SPECS: List[Spec] = [ ... ]` assignment.
    spec_list_node: Optional[ast.AST] = None
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.target is not None:
            targets = [node.target]
        else:
            continue
        for t in targets:
            if isinstance(t, ast.Name) and t.id == "SPECS":
                spec_list_node = node.value
    if spec_list_node is None or not isinstance(spec_list_node, (ast.List, ast.Tuple)):
        raise RuntimeError("could not locate SPECS list in deploy_all_lambdas.py")

    for element in spec_list_node.elts:
        if not (isinstance(element, ast.Call)
                and isinstance(element.func, ast.Name)
                and element.func.id == "Spec"):
            continue
        args = element.args
        name = _literal(args[0]) if len(args) >= 1 else None
        source = _literal(args[1]) if len(args) >= 2 else None
        flags: Dict[str, Any] = {
            "standalone": False,
            "extra_dirs": [],
            "extra_files": [],
            "external_dirs": [],
            "external_files": [],
            "required_layers": [],
            "required_memory": None,
            "required_timeout": None,
            "provisioned_by": "",
        }
        for kw in element.keywords:
            if kw.arg in flags:
                flags[kw.arg] = _literal(kw.value)
        specs.append({"name": name, "source": source, "packaging": flags})
    return specs


def _collect_env_keys(text: str) -> List[str]:
    keys = set()
    for m in _ENV_KEY_RE.finditer(text):
        keys.add(m.group(1) or m.group(2))
    return sorted(k for k in keys if k)


def _domain_of(rel_path: str) -> str:
    first = rel_path.split("/", 1)[0]
    return first if first in DOMAINS else "root"


def build_inventory() -> Dict[str, Any]:
    specs = parse_specs(DEPLOY_ALL)
    manifest = json.loads(ENV_MANIFEST.read_text(encoding="utf-8"))
    manifest_functions: Dict[str, Dict[str, str]] = manifest.get("functions", {})
    retirement = json.loads(RETIREMENT.read_text(encoding="utf-8"))

    retired_functions = set(retirement.get("retiredFunctions", []))
    retained_shared = set(retirement.get("retainedSharedModules", []))

    # Map SPECS source path (relative to amplify/functions) -> spec record.
    spec_by_source: Dict[str, Dict[str, Any]] = {}
    spec_by_name: Dict[str, Dict[str, Any]] = {}
    for spec in specs:
        # First spec that claims a source wins, so a strangler duplicate
        # (wecare-commerce reusing ecommerce/checkout) does not displace the
        # primary handler (wecare-checkout).
        if spec["source"] and spec["source"] not in spec_by_source:
            spec_by_source[spec["source"]] = spec
        if spec["name"]:
            spec_by_name[spec["name"]] = spec

    # Enumerate every .py file under amplify/functions.
    all_py = sorted(
        p for p in FUNCTIONS.rglob("*.py")
        if "__pycache__" not in p.parts
    )

    # A standalone handler is a handler.py whose parent dir is reachable as a
    # SPECS source, or any handler.py outside the shared/ subtree.
    domains: Dict[str, List[Dict[str, Any]]] = {d: [] for d in DOMAINS}
    domains["root"] = []

    shared_module_count = 0
    standalone_handler_count = 0
    unclassified_handler_count = 0

    seen_sources: set = set()

    for py in all_py:
        rel = py.relative_to(FUNCTIONS).as_posix()
        repo_rel = py.relative_to(ROOT).as_posix()
        domain = _domain_of(rel)

        # shared/ files (lambda_utils) are MODULES packaged into functions, not
        # standalone Lambdas.
        if domain == "shared":
            shared_module_count += 1
            continue

        # Only handler.py entry points are candidate standalone Lambdas.
        if py.name != "handler.py":
            continue

        source_dir = py.parent.relative_to(FUNCTIONS).as_posix()
        spec = spec_by_source.get(source_dir)

        text = py.read_text(encoding="utf-8", errors="replace")
        referenced_env_keys = _collect_env_keys(text)

        function_name = spec["name"] if spec else None
        manifest_env_keys: List[str] = []
        if function_name and function_name in manifest_functions:
            # KEY names only, never the recorded values.
            manifest_env_keys = sorted(manifest_functions[function_name].keys())

        # A handler mapped to a SPECS row is script-managed (the SPECS table in
        # deploy_all_lambdas.py creates and updates its shell). A CloudFormation
        # /CDK-owned function is handled separately, outside this walk (see the
        # synthetic entries appended below), because such functions do not carry
        # a SPECS row. A handler with NO SPECS row is NOT asserted script-managed:
        # several (the MCP functions, the image-package docs-scraper) are
        # delegated to a dedicated script or a CloudFormation stack. Asserting
        # "script-managed" for a CloudFormation-owned resource is exactly the
        # mislabel the audit section 7 guardrail 4 guards against, so unmapped
        # handlers are emitted "unclassified" with the owning script/stack left
        # null for code-review assignment (mirroring the live generator).
        cdk_source = None
        if function_name in CDK_CLOUDFORMATION_FUNCTIONS:
            classification = "cdk-cloudformation"
            cdk_source = CDK_CLOUDFORMATION_FUNCTIONS[function_name]
        elif spec is not None:
            classification = "script-managed"
        else:
            classification = "unclassified"

        retired = bool(function_name and function_name in retired_functions)

        entry = {
            "name": function_name,
            "source_path": repo_rel,
            "domain": domain,
            "classification": classification,
            "cdk_source": cdk_source,
            "spec_mapped": spec is not None,
            "referenced_env_keys": referenced_env_keys,
            "manifest_env_keys": manifest_env_keys,
            "packaging": spec["packaging"] if spec else None,
            "retired": retired,
        }
        domains.setdefault(domain, []).append(entry)
        standalone_handler_count += 1
        if classification == "unclassified":
            unclassified_handler_count += 1
        if spec:
            seen_sources.add(source_dir)

    # Synthetic entries for CloudFormation/CDK-owned functions that have NO
    # handler.py under amplify/functions/ and no SPECS row (so the handler walk
    # above never reaches them). The log-retention enforcer is owned by the
    # standalone CloudFormation stack infra/cloudwatch-retention-enforcer.yml.
    # Emitting it here is what makes the inventory actually carry at least one
    # classification == "cdk-cloudformation" entry, matching the classification
    # doc and the design doc, and representing the CDK/CFN subset the audit
    # section 7 wants visible in the inventory.
    cdk_cloudformation_count = 0
    for function_name, cfn_source in sorted(CDK_CLOUDFORMATION_FUNCTIONS.items()):
        # Skip any that DID resolve to a handler in the walk (none today, but keep
        # the inventory honest if one is ever added with a handler.py).
        already_emitted = any(
            e["name"] == function_name
            for entries in domains.values()
            for e in entries
        )
        if already_emitted:
            continue
        domain = _domain_of(cfn_source) if "/" in cfn_source else "root"
        # infra/*.yml lives outside amplify/functions, so it has no domain here.
        domain = "operations" if domain not in DOMAINS else domain
        entry = {
            "name": function_name,
            "source_path": cfn_source,
            "domain": domain,
            "classification": "cdk-cloudformation",
            "cdk_source": cfn_source,
            "spec_mapped": False,
            "referenced_env_keys": [],
            "manifest_env_keys": (
                sorted(manifest_functions[function_name].keys())
                if function_name in manifest_functions else []
            ),
            "packaging": None,
            "retired": bool(function_name in retired_functions),
        }
        domains.setdefault(domain, []).append(entry)
        cdk_cloudformation_count += 1

    # SPECS entries whose source did not resolve to a handler.py on disk
    # (two SPECS can share one source, e.g. wecare-commerce reuses
    # ecommerce/checkout). Record them so the mapping is complete.
    spec_mapped_names = sorted(s["name"] for s in specs if s["name"])
    unresolved_specs = []
    for spec in specs:
        src = spec["source"]
        if not src:
            continue
        handler = FUNCTIONS / src / "handler.py"
        if not handler.exists():
            unresolved_specs.append({"name": spec["name"], "source": src})

    # Any SPECS entry that shares a source already emitted as a different
    # function (strangler duplicates) is added as an alias entry so the count of
    # SPECS-mapped functions is honest.
    emitted_names = {
        e["name"]
        for entries in domains.values()
        for e in entries
        if e["name"]
    }
    alias_specs = []
    for spec in specs:
        if spec["name"] and spec["name"] not in emitted_names:
            src = spec["source"] or ""
            handler = FUNCTIONS / src / "handler.py"
            alias_specs.append({
                "name": spec["name"],
                "source_path": (handler.relative_to(ROOT).as_posix()
                                if handler.exists() else src),
                "domain": _domain_of(src),
                "classification": "script-managed",
                "shares_source_with": src,
                "retired": spec["name"] in retired_functions,
                "packaging": spec["packaging"],
            })

    retired_entries = {
        "functions": sorted(retired_functions),
        "routes": retirement.get("retiredRoutes", []),
        "tables": retirement.get("retiredTables", []),
        "retained_shared_modules": sorted(retained_shared),
    }

    # Verify none of the retired functions leaked into active entries.
    active_names = emitted_names | {a["name"] for a in alias_specs
                                    if not a["retired"]}
    resurrected = sorted(n for n in retired_functions if n in active_names)

    report = {
        "_generated_by": "scripts/ops/build_handler_inventory.py",
        "_mode": "static-offline (no AWS, no boto3, repo-only)",
        "_note": "env values are NEVER emitted; only env KEY names appear below",
        "_sources": [
            "scripts/deploy_all_lambdas.py (SPECS table, parsed via ast)",
            "amplify/functions/** (handler + shared module walk)",
            "config/lambda-env-manifest.json (env KEY names only)",
            "config/backend-retirement.json (retired entries)",
            "infra/cloudwatch-retention-enforcer.yml (CloudFormation-owned)",
        ],
        "summary": {
            "total_py_files": len(all_py),
            "shared_modules": shared_module_count,
            "standalone_handlers": standalone_handler_count,
            "specs_total": len(specs),
            # NOTE: these two SPECS counts measure different things and are NOT a
            # drift signal when they differ by the number of strangler aliases:
            #   specs_total_names      = count of distinct SPECS function NAMES
            #                            (includes strangler aliases such as
            #                            wecare-commerce held in spec_aliases).
            #   emitted_spec_mapped_handlers = count of emitted handler entries
            #                            that resolved to a SPECS source on disk.
            # The difference equals strangler_alias_specs (aliases share one
            # source directory, so they are recorded as aliases, not as a second
            # emitted handler). See spec_aliases for the held names.
            "specs_total_names": len(spec_mapped_names),
            "emitted_spec_mapped_handlers": sum(
                1 for entries in domains.values() for e in entries
                if e.get("spec_mapped")
            ),
            # Kept as an alias of specs_total_names for backward compatibility
            # with earlier consumers/tests; prefer the two explicit fields above.
            "specs_mapped_functions": len(spec_mapped_names),
            "cdk_cloudformation_functions": cdk_cloudformation_count,
            "unclassified_handlers": unclassified_handler_count,
            "manifest_functions": len(manifest_functions),
            "retired_functions": len(retired_functions),
            "retired_routes": len(retirement.get("retiredRoutes", [])),
            "retired_tables": len(retirement.get("retiredTables", [])),
            "unresolved_specs": len(unresolved_specs),
            "strangler_alias_specs": len(alias_specs),
            "resurrected_retired": resurrected,
        },
        "retired": retired_entries,
        "domains": domains,
        "spec_aliases": alias_specs,
        "unresolved_specs": unresolved_specs,
    }
    return report


def _is_within_scratch(out_path: Path) -> bool:
    try:
        out_path.resolve().relative_to((ROOT / ".scratch").resolve())
        return True
    except ValueError:
        return False


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--out",
        default=".scratch/backend-handler-inventory.json",
        help="output JSON path (default: .scratch/backend-handler-inventory.json, gitignored)",
    )
    parser.add_argument(
        "--expected-account",
        default=None,
        help="ACCEPTED but UNUSED in static mode (no AWS call is made and no account "
             "value is read). Present only for CLI parity with "
             "scripts/ops/generate_backend_registry.py.",
    )
    parser.add_argument("--print", dest="do_print", action="store_true",
                        help="also print the report to stdout")
    args = parser.parse_args(argv)

    if args.expected_account is not None:
        print("note: --expected-account is a no-op in static mode (no AWS call).",
              file=sys.stderr)

    report = build_inventory()

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    # Refuse to write outside .scratch/ unless the operator explicitly chose --out.
    default_used = args.out == ".scratch/backend-handler-inventory.json"
    if default_used and not _is_within_scratch(out_path):
        parser.error("refusing to write the default output outside .scratch/")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not _is_within_scratch(out_path):
        print(f"WARNING: {out_path} is OUTSIDE .scratch/. This report is an "
              f"operational artifact; do NOT commit it.", file=sys.stderr)
    print(f"wrote inventory to {out_path}", file=sys.stderr)
    print("reminder: this output may contain operationally sensitive strings; "
          "do NOT commit it (.scratch/ is gitignored).", file=sys.stderr)

    if args.do_print:
        print(json.dumps(report, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
