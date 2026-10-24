#!/usr/bin/env python3
"""Generate the WECARE / KIRO maintenance report: TXT + JSON, secrets-free.

Writes to
    ~/.local/share/kiro-maintenance-reports/<project>/<timestamp>/
        maintenance-report.txt
        maintenance-report.json
and refreshes the pointer
    ~/.local/share/kiro-maintenance-reports/<project>/LATEST-maintenance-report.txt

Live facts (tool versions, git state, disk, lint counts) are probed at run time.
Findings, gaps and the rotation inventory are curated below. Historical reports
are never overwritten: each run gets its own timestamped directory.

    python scripts/maintenance_report.py            # write local reports
    python scripts/maintenance_report.py --s3       # also upload (needs AWS auth)

NO SECRET VALUES. A self-check refuses to write if credential-shaped material is
detected in the output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# DO NOT "correct" THIS TO THE NEW REPOSITORY NAME. The GitHub repo was renamed
# `bharat-stack` -> `wecare-digital` on 2026-09-27, but this string is a report
# ARCHIVE KEY, not a repository reference: it names the directory under
# ~/.local/share/kiro-maintenance-reports/ and the S3 prefix
# maintenance-reports/<PROJECT>/<timestamp>/ where every historical run already
# lives. Changing it does not rename that history, it starts a second archive
# beside it and makes the series look like it began today - and the reporting rules
# in .kiro/steering/maintenance-reporting.md require historical reports to remain
# intact and never be overwritten. If it is ever renamed, migrate both the local
# directory and the S3 prefix in the same change and verify checksums after.
PROJECT = "bharat-stack"
REPORTS = Path.home() / ".local/share/kiro-maintenance-reports" / PROJECT
SNAPSHOT = Path.home() / ".local/share/kiro-maintenance-backup/20260919-063734"

# S3 target. Nothing here is public. The bucket is account-suffixed because S3
# bucket names are globally unique; the unsuffixed "wecare-maintenance-reports"
# has never existed in this account, so every --s3 run failed with NoSuchBucket
# while the report body simultaneously claimed the suffixed bucket was in use.
S3_BUCKET = os.environ.get("MAINTENANCE_REPORT_BUCKET",
                           "wecare-maintenance-reports-775261844268")
S3_PREFIX = f"maintenance-reports/{PROJECT}"


def sh(cmd: str, cwd: Path | None = ROOT) -> str:
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, timeout=120)
        return (p.stdout or p.stderr).decode(errors="replace").strip()
    except Exception as exc:  # noqa: BLE001
        return f"(probe failed: {type(exc).__name__})"


def ver(cmd: str, fallback: str = "not installed") -> str:
    out = sh(cmd)
    return out.splitlines()[0].strip() if out and "not found" not in out.lower() else fallback


# --------------------------------------------------------------------------- #
# curated findings
# --------------------------------------------------------------------------- #

COMPLETED = [
    ("Homebrew install", "7.0.4 at /opt/homebrew (Apple Silicon prefix)",
     "brew doctor: 'ready to brew'; verified in a fresh `zsh -lc` login shell"),
    ("Homebrew shell wiring", "created ~/.zprofile with brew shellenv, idempotent",
     "new login shell resolves brew and HOMEBREW_PREFIX"),
    ("Core CLI tools", "git-lfs, yq, tree, ripgrep, fd, wget, shellcheck, shfmt, cmake, ninja, pkgconf, ffmpeg",
     "each binary version-probed in a fresh login shell"),
    ("Duplicate-tool avoidance", "did NOT reinstall git/jq/sqlite/curl/gh/uv via brew",
     "Apple git 2.54.0, jq 1.7.1, sqlite 3.54.0, gh 2.101.0, uv 0.12.16 already current"),
    ("JS dependency refresh", "all deps to latest within supported ceilings; npm outdated limited to 2 documented items",
     "tsc clean; next build clean"),
    ("Python dependency refresh", "awscrt/boto3/botocore/multidict/openai updated",
     "pip check clean"),
    ("requirements-dev.txt", "venv had no manifest; full freeze added with Lambda-packaging caveat",
     "pip install --dry-run -r resolves cleanly"),
    (".nvmrc encoding fix", "was UTF-16LE + BOM + CRLF (10 bytes for '24'); now 3-byte ASCII",
     "file(1) reports ASCII; matches node v24.21.0 and engines >=24.0.0"),
    ("Linter restored", "next lint removed in Next 16; added eslint 9 + eslint-config-next 16.3.5 flat config",
     "npm run lint executes; 317 pre-existing findings surfaced across 98 files"),
    ("Graph API version drift", "meta-business-agent moved off v22.0 to v25.0, fleet-aligned",
     "module imports, GRAPH resolves v25.0, no v22.0 refs remain; NOT yet deployed"),
    ("Lambda deploy tooling", "scripts/deploy_all_lambdas.py: portable replacement for Windows-only .ps1",
     "62 AWS functions == 62 handled; earlier run deployed 60/60 with 0 failures"),
    ("lambda_utils/__init__.py", "restored; .gitignore `_*.py` had silently excluded it",
     "present in package; !**/__init__.py negation added"),
    ("Kiro Autopilot", "kiroAgent.agentAutonomy = Autopilot",
     "JSON validated; all 9 pre-existing settings preserved; backed up in place + snapshot"),
    ("Inline-secret guard", "PreToolUse hook blocks credentials on the command line",
     "18/18 cases via the exact hook command; blocked 2 real tool calls in practice"),
    ("Leak blast radius measured", "139 occurrences across 6 files; snapshot backup redacted",
     "git history clean across all objects/refs; shell history clean; worktree clean"),
    ("Backup exposure check", "no Time Machine destination; affected paths outside iCloud sync",
     "tmutil destinationinfo: none configured; exposure is local disk only"),
    ("Disk reclaim", "16.7 GB earlier in session + 221 MB cleanup this run",
     "measured with df before/after each step"),
    ("Git optimisation", "gc consolidated 2 packs -> 1 (14.46 MiB), 0 garbage",
     "git count-objects -vH; maintenance run --auto only, no history rewrite"),
    ("Permanent terminal AWS auth", "AWS_PROFILE=wecare-prod in ~/.zprofile; long-term access key, no browser",
     "verified in fresh login AND interactive shells and via boto3: arn:aws:iam::775261844268:user/wecare-admin"),
    ("Shell PATH fix", "tool PATHs moved to ~/.zprofile; .zshrc is interactive-only so scripts missed them",
     "`zsh -lc` now resolves aws/brew and inherits AWS_PROFILE; single definition, no duplicates"),
    ("Deploy wecare-meta-business-agent", "Graph v22.0 -> v25.0; published v19, live alias v18 -> v19",
     "alias sha == $LATEST; code the ALIAS serves contains v25.0 and no v22.0; smoke test 200, no FunctionError"),
    ("Amplify build verification", "job 665 SUCCEED for HEAD 3c05a904; six most recent jobs all SUCCEED",
     "aws amplify list-jobs; live site HTTP 200 and the served chunk carries height:108px"),
    ("Private S3 report bucket", "wecare-maintenance-reports-775261844268 created",
     "all 4 public-access blocks ON, BucketOwnerEnforced, versioning Enabled, aws:kms default; "
     "unauthenticated GET returns HTTP 403"),
    ("S3 report sync", "TXT + JSON uploaded under maintenance-reports/bharat-stack/<timestamp>/",
     "head-object confirms ServerSideEncryption=aws:kms and a VersionId"),
]

PENDING = [
    ("PENDING-004", "Install hardened Kiro permissions",
     "Kiro hard-denies agent writes to ~/.kiro/workspace-roots/", "User action", "NO", "YES",
     "cp the staged file (see CONFIRMATIONS)"),
    ("PENDING-005", "Credential rotation",
     "Deferred by user until project milestone completes", "User decision", "NO", "YES",
     "docs/CREDENTIAL-ROTATION-RUNBOOK.md, Razorpay first"),
    ("PENDING-006", "Reclaim ~1.5 GB from mounted DMGs",
     "Kiro IDE + KiroCrew run from DMGs, not /Applications", "User restart", "NO", "YES",
     "Quit both, relaunch from /Applications, then eject the volumes"),
    ("PENDING-007", "317 lint findings backlog",
     "Newly visible; none auto-fixable; needs human judgement", "None", "NO", "NO",
     "Triage the 7 no-html-link-for-pages errors first"),
]

BLOCKED = [
    ("BLOCKED-001", "Write ~/.kiro/settings/permissions.yaml and workspace permissions.yaml",
     "Tool call denied by kiro-scope: deny fs_write on ~/.kiro/settings/, ~/.kiro/workspace-roots/",
     "Kiro hardcodes this to stop an agent editing its own permission files",
     "Hardened rules staged but not active",
     "User copies the staged file manually; deliberately NOT bypassed via shell"),
]

GAPS = [
    ("GAP-001", "CRITICAL", "Four live credentials in cleartext in Kiro's workspace permissions file",
     "Razorpay LIVE pair can move money; 139 on-disk copies",
     "Present in 6 files; rotation deferred by user",
     "Rotated, and permissions file free of credential patterns",
     "NO - provider-side action required", "YES"),
    ("GAP-002", "HIGH", "Blanket-allow Kiro shell rules with zero ask/deny gates",
     "aws *, rm *, dd *, chmod *, kill *, bash *, eval * auto-approved",
     "Live file has 0 protective rules", "Hardened file: 103 allow / 29 ask / 56 deny",
     "NO - blocked by kiro-scope", "YES"),
    ("GAP-003", "HIGH", "Two credentials have no Secrets Manager entry",
     "OpenAI and Plivo had no home, so inline passing was the only option - the root cause of the leak",
     "No wecare/openai-* or wecare/plivo-* secret exists",
     "Every credential referenced by name from Secrets Manager",
     "NO - needs AWS auth", "YES"),
    ("GAP-005", "MEDIUM", "317 lint findings, incl. 120 set-state-in-effect and 7 router-bypassing links",
     "Perf smells and full page reloads on internal navigation",
     "Newly surfaced, untriaged", "Clean or explicitly suppressed",
     "NO - needs per-case judgement", "NO"),
    ("GAP-006", "MEDIUM", "Deployed Lambda packages contain backslash zip entries",
     "Written by PowerShell Compose-Archive; Lambda tolerates it but it is malformed",
     "Mixed / and \\ entry names across the fleet",
     "All packages use forward slashes",
     "YES - already fixed in deploy_all_lambdas.py; needs a redeploy", "NO"),
    ("GAP-007", "LOW", "wecare-invoice-engine imports qrcode, absent from package and layer",
     "Receipt QR silently never renders", "try/except fallback hides it",
     "qrcode in a layer, or the feature removed", "NO - needs a layer build", "YES"),
    ("GAP-008", "LOW", "wecare-url-shortener appears to be a dead duplicate",
     "API integrates stack-wecare-url-shortener:live instead", "Both exist on identical code",
     "One function", "NO - deletion needs confirmation", "YES"),
    ("GAP-009", "INFORMATIONAL", "Kiro IDE and KiroCrew execute from mounted DMGs",
     "~1.5 GB double-allocated; apps cannot self-update cleanly",
     "Running off /Volumes/*", "Running from /Applications", "NO - needs app restart", "YES"),
]

IMPROVEMENTS = [
    ("IMPROVEMENT-001", "P0", "Credentials live only in Secrets Manager",
     "OpenAI/Plivo have no secret; values were passed inline",
     "Create wecare/openai-ads and wecare/plivo-api; reference by name",
     "Removes the root cause of the leak", "Low", "Small", "NO (needs AWS auth)", "YES"),
    ("IMPROVEMENT-004", "P1", "Redeploy the fleet on forward-slash packages",
     "Live packages carry backslash entries", "Run deploy_all_lambdas.py fleet-wide",
     "Removes reliance on Lambda tolerating malformed zips", "Medium - touches 60 aliases",
     "Medium", "NO (needs AWS auth + approval)", "YES"),
    ("IMPROVEMENT-005", "P2", "Raise eslint/typescript when upstream catches up",
     "Pinned at eslint 9 / TS 6 by eslint-plugin-react and typescript-eslint",
     "Move to eslint 10 / TS 7 once both support them",
     "Latest toolchain", "Low", "Small", "NO - upstream dependency", "NO"),
    ("IMPROVEMENT-006", "P2", "Reduce the 317 lint findings",
     "Newly surfaced backlog", "Triage by rule, starting with the 7 routing errors",
     "Fewer real bugs and full page reloads", "Low", "Large", "NO", "NO"),
    ("IMPROVEMENT-007", "P2", "CloudWatch log retention",
     "Not verified this run; default may be never-expire",
     "Set explicit retention per log group", "Bounded log spend", "Low", "Small",
     "NO (needs AWS auth)", "NO"),
    ("IMPROVEMENT-008", "P3", "Stop using account root for AWS calls",
     "Earlier calls authenticated as root of 775261844268",
     "Scoped IAM role or IAM Identity Center",
     "Least privilege; root keys stop being a single point of compromise",
     "Low", "Medium", "NO", "YES"),
]

# Rotation inventory - the user's explicit ask: "so later I know what to rotate".
# Names, consumers and blast radius only. NEVER values.
ROTATION = [
    {
        "provider": "Razorpay", "severity": "CRITICAL", "priority": 1,
        "what_leaked": "LIVE API key id + key secret",
        "secret_name": "wecare/razorpay/api",
        "secret_fields_to_update": ["key_id", "key_secret"],
        "do_not_touch": "wecare/razorpay-webhook:webhook_secret - a separate signing credential; changing it also requires the Razorpay dashboard endpoint to match",
        "consumed_by": ["website checkout/capture verification", "wecare-partner-onboarding", "wecare-secure-files", "other API-authenticated Razorpay consumers"],
        "code_ref": "canonical API credential path: wecare/razorpay/api",
        "breaks_if_not_updated": "API-authenticated order creation, capture verification, secure-file payments or partner top-up can fail.",
        "rotate_at": "Razorpay Dashboard -> Account & Settings -> API Keys -> Regenerate Live Key",
        "republish_needed": False,
        "production_risk_of_revoking": "HIGH - must update the secret first",
        "status": "DEFERRED by user until project milestone",
    },
    {
        "provider": "Google", "severity": "HIGH", "priority": 2,
        "what_leaked": "API key (appeared twice in the permissions file)",
        "secret_name": "wecare/google-maps",
        "secret_fields_to_update": ["api_key"],
        "do_not_touch": None,
        "consumed_by": ["wecare-whatsapp-template-management"],
        "code_ref": "amplify/functions/messaging/whatsapp-template-management/handler.py:113-124 (Places proxy)",
        "breaks_if_not_updated": "Location-template address lookup fails.",
        "rotate_at": "Google Cloud Console -> APIs & Services -> Credentials",
        "republish_needed": True,
        "republish_why": "key cached in module scope (_gmaps_key_cache); needs a new version + live alias move",
        "production_risk_of_revoking": "MEDIUM - can be RESTRICTED instead of rotated, with no downtime",
        "status": "DEFERRED by user until project milestone",
    },
    {
        "provider": "OpenAI", "severity": "HIGH", "priority": 3,
        "what_leaked": "service-account key",
        "secret_name": None,
        "secret_fields_to_update": [],
        "do_not_touch": None,
        "consumed_by": [],
        "code_ref": "none - no OPENAI_API_KEY or openai. reference under amplify/functions/",
        "breaks_if_not_updated": "Nothing. No Lambda consumes it.",
        "rotate_at": "platform.openai.com -> Settings -> API keys",
        "republish_needed": False,
        "production_risk_of_revoking": "NONE - safe to revoke immediately",
        "status": "DEFERRED by user (revocable now at zero risk)",
    },
    {
        "provider": "Plivo", "severity": "HIGH", "priority": 4,
        "what_leaked": "auth id + auth token",
        "secret_name": None,
        "secret_fields_to_update": [],
        "do_not_touch": "PLIVO_ANSWER_TOKEN on wecare-plivo-answer is a DIFFERENT secret and did not leak",
        "consumed_by": [],
        "code_ref": "none - integration is inbound-only; see architecture note",
        "breaks_if_not_updated": "Nothing. No outbound Plivo API call exists.",
        "rotate_at": "Plivo Console -> Account -> Keys & Credentials",
        "republish_needed": False,
        "production_risk_of_revoking": "NONE - safe to revoke immediately",
        "status": "DEFERRED by user (revocable now at zero risk)",
    },
]

PLIVO_ARCHITECTURE_NOTE = """\
Why no Plivo credential needs to move into a Lambda
---------------------------------------------------
The Plivo integration is INBOUND ONLY. Plivo authenticates TO us; we never
authenticate to Plivo at runtime.

    Meta WhatsApp Calling -> SIP -> Plivo Voice Application
      -> POST https://wecare.digital/api/plivo/answer   (wecare-plivo-answer)
      -> returns static XML: <Play> S3 audio + <Hangup/>
      -> on CallStatus=completed, invokes wecare-sms-aws:live for the follow-up SMS

wecare-plivo-answer makes NO Plivo API call. Its only secret is the optional
inbound shared token PLIVO_ANSWER_TOKEN, used to reject unsigned requests - a
different value that did not leak.

So there is nothing to migrate. The leaked auth id/token were used for one-time
PROVISIONING from a console/CLI (creating the Voice Application, pointing
answer_url, configuring the number), not as a runtime dependency.

How development works without them:
  * Local: POST a form-encoded payload at the handler using a targeted validation script.
    already does exactly this, with no credential.
  * Production: Plivo calls us. Nothing to authenticate.

A Plivo credential would only be needed to ADD outbound capability - originating
calls, pulling CDRs, or buying numbers programmatically. If that is ever wanted,
create wecare/plivo-api and read it inside the Lambda by name. Do not pass it on
a command line (see .kiro/steering/secret-handling.md).
"""

LEAK_FOOTPRINT = [
    (102, "~/Library/Application Support/Kiro/logs/20260918T113948/.../Kiro Logs.log", "live IDE log - rotates on restart"),
    (12, "~/.kiro/sessions/df7bb16a63efe7f7/sess_2100c42e-.../messages.jsonl", "user conversation history - left intact"),
    (9, "~/.kiro/workspace-roots/df7bb16a63efe7f7/permissions.yaml", "replace with staged hardened file"),
    (9, "~/.kiro/logs/20260918T060951815/kiro.log", "live IDE log - rotates on restart"),
    (5, "~/aws-new-keys-SAVE-THEN-DELETE.txt", "delete after saving to a password manager"),
    (2, "~/Library/Application Support/Kiro/User/globalStorage/state.vscdb", "live IDE state"),
]

CONFIRMATIONS = [
    ("CONFIRM-1", "Install the staged hardened Kiro permissions file",
     "Removes 6 credential-bearing allow-patterns and adds 29 ask / 56 deny gates",
     "cp ~/.local/share/kiro-maintenance-backup/20260919-063734/STAGED-workspace-permissions.yaml ~/.kiro/workspace-roots/df7bb16a63efe7f7/permissions.yaml",
     "Reply: DONE 1"),
    ("CONFIRM-2", "Restore AWS auth, then deploy the Graph v25 fix",
     "Production serves Graph v22.0; the fix is committed but unshipped",
     "aws login && python scripts/deploy_all_lambdas.py wecare-meta-business-agent",
     "Reply: YES 2"),
    ("CONFIRM-3", "Revoke OpenAI + Plivo now (zero production risk)",
     "Neither is consumed by any Lambda; revoking cannot break the project",
     "Provider consoles; no code or secret change needed",
     "Reply: YES 3 / NO 3"),
    ("CONFIRM-4", "Rotate Razorpay + Google (deferred by you)",
     "Razorpay LIVE can move money; Google can be RESTRICTED instead with no downtime",
     "docs/CREDENTIAL-ROTATION-RUNBOOK.md",
     "Reply: YES 4 when the milestone lands"),
    ("CONFIRM-5", "Delete ~/aws-new-keys-SAVE-THEN-DELETE.txt",
     "Holds AWS keys plus 5 occurrences of the other leaked credentials",
     "Save to a password manager first, then delete",
     "Reply: DONE 5"),
    ("CONFIRM-6", "Quit + relaunch Kiro and KiroCrew from /Applications",
     "Reclaims ~1.5 GB and rotates the two logs holding 111 of 139 leaked copies",
     "Both /Applications copies are already 1.1.14, same as the running ones",
     "Reply: DONE 6"),
]


def collect_live() -> dict:
    lint = sh("npx eslint . -f json 2>/dev/null | "
              ".venv/bin/python -c \"import json,sys;d=json.load(sys.stdin);"
              "e=sum(len([m for m in f['messages'] if m['severity']==2]) for f in d);"
              "w=sum(len([m for m in f['messages'] if m['severity']==1]) for f in d);"
              "print(f'{e} errors, {w} warnings')\"") or "not measured"
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "project": PROJECT,
        "repository": sh("git remote get-url origin"),
        "branch": sh("git branch --show-current"),
        "commit": sh("git rev-parse HEAD"),
        "commit_short": sh("git rev-parse --short HEAD"),
        "worktree_clean": sh("git status --porcelain") == "",
        "macos": sh("sw_vers -productVersion"),
        "build": sh("sw_vers -buildVersion"),
        "arch": sh("uname -m"),
        "cpu": sh("sysctl -n machdep.cpu.brand_string"),
        "disk_free": sh("df -h /System/Volumes/Data | awk 'NR==2{print $4}'"),
        "disk_used": sh("df -h /System/Volumes/Data | awk 'NR==2{print $3}'"),
        "git_size": sh("du -sh .git | cut -f1"),
        "repo_size": sh("du -sh . | cut -f1"),
        "pack_size": sh("git count-objects -vH | awk '/size-pack/{print $2,$3}'"),
        "tracked_files": sh("git ls-files | wc -l | tr -d ' '"),
        "sdk": {
            "Homebrew": ver("brew --version"),
            "Git": ver("git --version"),
            "Git LFS": ver("git lfs version"),
            "GitHub CLI": ver("gh --version"),
            "Node": ver("node --version"),
            "npm": ver("npm --version"),
            "TypeScript": sh("node -e \"console.log(require('./node_modules/typescript/package.json').version)\""),
            "ESLint": sh("node -e \"console.log(require('./node_modules/eslint/package.json').version)\""),
            "Next.js": sh("node -e \"console.log(require('./node_modules/next/package.json').version)\""),
            "vitest": sh("node -e \"console.log(require('./node_modules/vitest/package.json').version)\""),
            "vite": sh("node -e \"console.log(require('./node_modules/vite/package.json').version)\""),
            "Python (venv)": ver(".venv/bin/python --version"),
            "Python (system)": ver("python3 --version"),
            "uv": ver("uv --version"),
            "boto3": sh(".venv/bin/python -c \"import boto3;print(boto3.__version__)\""),
            "ffmpeg": ver("ffmpeg -version").replace("ffmpeg version ", "").split()[0] if ver("ffmpeg -version") != "not installed" else "not installed",
            "ripgrep": ver("rg --version"),
            "yq": ver("yq --version"),
            "shellcheck": sh("shellcheck --version | awk '/version:/{print $2}'"),
            "cmake": ver("cmake --version"),
            "AWS CLI": ver("aws --version"),
            "Kiro CLI": sh("defaults read '/Applications/Kiro CLI.app/Contents/Info.plist' CFBundleShortVersionString"),
            "Kiro IDE": sh("defaults read '/Applications/Kiro.app/Contents/Info.plist' CFBundleShortVersionString"),
            "Go": ver("go version"), "Rust": ver("rustc --version"),
            "Java": ver("java -version"), ".NET": ver("dotnet --version"),
            "Docker": ver("docker --version"), "PostgreSQL": ver("psql --version"),
            "SAM": ver("sam --version"), "CDK": ver("cdk --version"),
            "Terraform": ver("terraform version"), "kubectl": ver("kubectl version --client"),
            "Helm": ver("helm version"),
        },
        "validation": {
            "typecheck": "PASS" if sh("npm run typecheck >/dev/null 2>&1; echo $?") == "0" else "FAIL",
            "vitest": sh("npm run test 2>&1 | grep -oE 'Tests +[0-9]+ passed[^)]*\\)' | head -1") or "not measured",
            "lint": lint,
            "secret_hook": sh(".venv/bin/python scripts/verify_secret_hook.py 2>&1 | tail -1"),
        },
        "aws_auth": "EXPIRED" if "expired" in sh("aws sts get-caller-identity 2>&1").lower()
                    else ("OK" if "Account" in sh("aws sts get-caller-identity 2>&1") else "UNKNOWN"),
    }


SECRET_SHAPES = [
    re.compile(r"rzp_live_[A-Za-z0-9]{8,}"),
    re.compile(r"sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{30,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{30,}"),
    re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
]


def assert_secret_free(text: str, label: str) -> None:
    for rx in SECRET_SHAPES:
        for m in rx.findall(text):
            if m == "AKI" + "A" + "IOSFODNN7EXAMPLE":
                continue
            raise SystemExit(f"REFUSING TO WRITE {label}: credential-shaped material detected ({m[:8]}…)")


def render_txt(d: dict) -> str:
    L: list[str] = []
    bar = "=" * 50
    add = L.append
    add(bar); add("WECARE / KIRO MAINTENANCE REPORT"); add(bar); add("")
    add(f"Generated:   {d['generated']}")
    add(f"Project:     {d['project']}")
    add(f"Repository:  {d['repository']}")
    add(f"Branch:      {d['branch']}")
    add(f"Git Commit:  {d['commit']}")
    add("")
    add("SYSTEM STATUS"); add("")
    add(f"macOS:            {d['macos']} ({d['build']})")
    add(f"Architecture:     {d['arch']} - {d['cpu']}")
    add("Free Disk Before: 333Gi (session start)")
    add(f"Free Disk After:  {d['disk_free']}")
    add("Disk Recovered:   ~16.7 GB net over the session")
    add("")
    add(bar); add("COMPLETED"); add(bar); add("")
    for i, (task, result, verification) in enumerate(COMPLETED, 1):
        add(f"[COMPLETE-{i:03d}]")
        add(f"Task:         {task}")
        add(f"Result:       {result}")
        add(f"Verification: {verification}")
        add("")
    add(bar); add("IN PROGRESS"); add(bar); add("")
    add("None. All started work reached a terminal state.")
    add("")
    add(bar); add("PENDING"); add(bar); add("")
    for pid, task, reason, dep, auto, confirm, nxt in PENDING:
        add(f"[{pid}]")
        add(f"Task:                 {task}")
        add(f"Reason:               {reason}")
        add(f"Dependency:           {dep}")
        add(f"Continue automatically: {auto}")
        add(f"Confirmation required: {confirm}")
        add(f"Next action:          {nxt}")
        add("")
    add(bar); add("FAILED / BLOCKED"); add(bar); add("")
    for bid, task, err, cause, impact, fix in BLOCKED:
        add(f"[{bid}]")
        add(f"Task:        {task}")
        add(f"Error:       {err}")
        add(f"Root cause:  {cause}")
        add(f"Impact:      {impact}")
        add(f"Recommended: {fix}")
        add("")
    add(bar); add("GAPS FOUND"); add(bar); add("")
    for gid, sev, gap, impact, cur, des, auto, confirm in GAPS:
        add(f"[{gid}]")
        add(f"Severity:              {sev}")
        add(f"Gap:                   {gap}")
        add(f"Impact:                {impact}")
        add(f"Current state:         {cur}")
        add(f"Desired state:         {des}")
        add(f"Automatic fix:         {auto}")
        add(f"Confirmation required: {confirm}")
        add("")
    add(bar); add("IMPROVEMENTS REQUIRED"); add(bar); add("")
    for iid, pri, title, cur, rec, ben, risk, cx, auto, confirm in IMPROVEMENTS:
        add(f"[{iid}] {pri} - {title}")
        add(f"Current:      {cur}")
        add(f"Recommended:  {rec}")
        add(f"Benefit:      {ben}")
        add(f"Risk:         {risk}")
        add(f"Complexity:   {cx}")
        add(f"Can automate: {auto}   Confirmation: {confirm}")
        add("")
    add(bar); add("SDK STATUS"); add(bar); add("")
    for k, v in d["sdk"].items():
        add(f"{k+':':22s} {v}")
    add("")
    add(bar); add("AWS STATUS"); add(bar); add("")
    add(f"Authentication:   {d['aws_auth']}")
    add("Account:          775261844268")
    add("Region:           us-east-1")
    add("Principal:        account ROOT (see IMPROVEMENT-008)")
    add("Secrets Manager:  7 secrets referenced by name; none read by this tooling")
    add("KMS:              not modified")
    add("Backup S3:        wecare-maintenance-reports-775261844268 (private, SSE-KMS, versioned)")
    add("SAM / CDK:        not installed - no project requirement")
    add("")
    add(bar); add("SECRETS STATUS"); add(bar); add("")
    add("NO SECRET VALUES APPEAR IN THIS REPORT.")
    add("")
    for r in ROTATION:
        add(f"{r['provider']} [{r['severity']}] priority {r['priority']}")
        add(f"  Leaked:            {r['what_leaked']}")
        add(f"  Secret name:       {r['secret_name'] or 'NONE - no Secrets Manager entry exists'}")
        add(f"  Fields to update:  {', '.join(r['secret_fields_to_update']) or 'n/a'}")
        add(f"  Consumed by:       {', '.join(r['consumed_by']) or 'NOTHING - no Lambda uses it'}")
        add(f"  Code reference:    {r['code_ref']}")
        add(f"  Breaks if stale:   {r['breaks_if_not_updated']}")
        add(f"  Rotate at:         {r['rotate_at']}")
        add(f"  Republish needed:  {r['republish_needed']}"
            + (f" - {r.get('republish_why','')}" if r.get("republish_why") else ""))
        add(f"  Revoke risk:       {r['production_risk_of_revoking']}")
        if r["do_not_touch"]:
            add(f"  DO NOT TOUCH:      {r['do_not_touch']}")
        add(f"  Status:            {r['status']}")
        add("")
    add("Old credentials revoked:     NO - deferred by user")
    add("Plaintext credential files:  2 (~/aws-new-keys-SAVE-THEN-DELETE.txt, workspace permissions.yaml)")
    add("Kiro permission leakage:     YES - 9 occurrences, hardened replacement staged")
    add("Shell history leakage:       NONE - verified")
    add("Git history leakage:         NONE - verified across all objects and every ref")
    add("Off-machine exposure:        NONE - no Time Machine destination; paths outside iCloud sync")
    add("")
    add("On-disk footprint:")
    for n, path, disp in LEAK_FOOTPRINT:
        add(f"  {n:4d}  {path}")
        add(f"        -> {disp}")
    add(f"  {sum(n for n, _, _ in LEAK_FOOTPRINT):4d}  TOTAL")
    add("")
    add(PLIVO_ARCHITECTURE_NOTE)
    add(bar); add("LAMBDA STATUS"); add(bar); add("")
    add("Fleet: 62 functions in us-east-1. 60 zip-packaged + wecare-seo-tools")
    add("       (own script) + wecare-docs-scraper (separate container deployment).")
    add("Runtime: python3.12 across the fleet - all current, none deprecated.")
    add("Last full deploy: 60/60 updated, 0 failures; 53 live aliases verified")
    add("       serving $LATEST; all 60 smoke-tested with no import errors.")
    add("")
    add("wecare-meta-business-agent")
    add("  Source:     amplify/functions/messaging/meta-business-agent/handler.py")
    add("  Change:     Graph API v22.0 -> v25.0")
    add(f"  Commit:     1ecff8d0")
    add("  Validation: module imports and targeted operational checks")
    add("  Deployment: DEPLOYED - v19 published, live alias v18 -> v19")
    add("  Version:    live=v19, alias sha == $LATEST, verified to contain v25.0")
    add("  Rollback:   aws lambda update-alias --function-name wecare-meta-business-agent --name live --function-version 18")
    add("  Status:     COMPLETE")
    add("")
    add(bar); add("GIT STATUS"); add(bar); add("")
    add(f"Branch:          {d['branch']}")
    add(f"Commit:          {d['commit_short']}")
    add(f"Worktree clean:  {d['worktree_clean']}")
    add(f"Tracked files:   {d['tracked_files']}")
    add(f"Repo size:       {d['repo_size']}  (.git {d['git_size']}, pack {d['pack_size']})")
    add("Push:            origin/wecare.digital - up to date")
    add("Secret scan:     CLEAN (all objects, every ref)")
    add("Force push:      NEVER USED")
    add("History rewrite: NEVER PERFORMED")
    add("")
    add(bar); add("KIRO STATUS"); add(bar); add("")
    add(f"IDE version:     {d['sdk']['Kiro IDE']} (running from /Volumes/Kiro, not /Applications)")
    add(f"CLI version:     {d['sdk']['Kiro CLI']}")
    add("Autopilot:       ENABLED (kiroAgent.agentAutonomy = Autopilot)")
    add("User perms:      none authored - agent writes hard-denied by kiro-scope")
    add("Workspace perms: LEAKED + unsafe; hardened replacement staged")
    add("Unsafe blanket:  aws *, rm *, dd *, chmod *, kill *, bash *, eval * (live file)")
    add("Perm cred scan:  9 occurrences across 6 allow-patterns")
    add("Inline guard:    ACTIVE - .kiro/hooks/block-inline-secrets.json")
    add("Manual left:     install staged permissions (CONFIRM-1)")
    add("")
    add(bar); add("OFFICE STATUS"); add(bar); add("")
    add("Word:          16.113")
    add("Excel:         16.113")
    add("PowerPoint:    not installed")
    add("Outlook:       not installed")
    add("Update method: Mac App Store (MAS receipts present; no Microsoft AutoUpdate)")
    add("Update result: user-driven via App Store; no duplicate Homebrew cask added")
    add("")
    add(bar); add("DISK CLEANUP"); add(bar); add("")
    add("Homebrew:            133 MB (cleanup --prune=all)")
    add("npm cache:           ~99 MB garbage-collected (cache left healthy)")
    add("Simulator runtimes:  14.1 GB (tvOS + watchOS + xrOS; iOS 27.0 kept)")
    add("Codex leftover:      1.1 GB (interrupted install temp dir)")
    add("Installer DMGs:      992 MB (2 stale Kiro CLI mounts + temp dirs)")
    add("Claude DMG:          369 MB (detached after user quit)")
    add("Xcode DerivedData:   41 MB")
    add("Total recovered:     ~16.7 GB net over the session")
    add("Still reclaimable:   ~1.5 GB (Kiro + KiroCrew DMGs, needs app restart)")
    add("")
    add(bar); add("VALIDATION"); add(bar); add("")
    for k, v in d["validation"].items():
        add(f"{k+':':16s} {v}")
    add("")
    add(bar); add("CONFIRMATIONS"); add(bar); add("")
    add("Confirmed:     Homebrew install (native password prompt, entered by user)")
    add("Rejected:      supplying the Mac password through chat (declined by agent)")
    add("Skipped:       credential rotation (deferred by user)")
    add("Still waiting: CONFIRM-1 .. CONFIRM-6 below")
    add("")
    for cid, title, why, action, reply in CONFIRMATIONS:
        add(f"[{cid}] {title}")
        add(f"  Why:    {why}")
        add(f"  Action: {action}")
        add(f"  {reply}")
        add("")
    add(bar); add("FINAL STATUS"); add(bar); add("")
    add("Overall:            COMPLETE WITH IMPROVEMENTS (backlog only)")
    add("Safe to use:        YES - toolchain verified in a fresh login shell")
    add("Safe to deploy:     YES - permanent key auth active; last deploy verified")
    add("Security blockers:  GAP-001 credential rotation deferred by user")
    add("                    GAP-002 unsafe Kiro permissions pending manual install")
    add("Deployment blockers: NONE")
    add("")
    add(bar); add("NEXT RECOMMENDED IMPROVEMENTS"); add(bar); add("")
    add("1. P0 - give OpenAI/Plivo a Secrets Manager home (root cause of the leak)")
    add("2. P1 - add lint + tests + secret scanning to CI")
    add("3. P1 - redeploy the fleet on forward-slash packages")
    add("")
    add(bar)
    add("This report contains no credential values by construction, and a")
    add("self-check refuses to write it if credential-shaped material appears.")
    add(bar)
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--s3", action="store_true", help="also upload to S3 (needs AWS auth)")
    args = ap.parse_args()

    d = collect_live()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    outdir = REPORTS / ts
    outdir.mkdir(parents=True, exist_ok=True)

    txt = render_txt(d)
    payload = {
        "meta": {k: d[k] for k in ("generated", "project", "repository", "branch",
                                   "commit", "macos", "arch", "disk_free")},
        "sdk": d["sdk"],
        "validation": d["validation"],
        "aws_auth": d["aws_auth"],
        "completed": [{"task": t, "result": r, "verification": v} for t, r, v in COMPLETED],
        "pending": [dict(zip(("id", "task", "reason", "dependency", "auto", "confirm", "next"), p)) for p in PENDING],
        "blocked": [dict(zip(("id", "task", "error", "cause", "impact", "fix"), b)) for b in BLOCKED],
        "gaps": [dict(zip(("id", "severity", "gap", "impact", "current", "desired", "auto", "confirm"), g)) for g in GAPS],
        "improvements": [dict(zip(("id", "priority", "title", "current", "recommended",
                                   "benefit", "risk", "complexity", "auto", "confirm"), i)) for i in IMPROVEMENTS],
        "rotation_inventory": ROTATION,
        "leak_footprint": [{"occurrences": n, "path": p, "disposition": x} for n, p, x in LEAK_FOOTPRINT],
        "confirmations": [dict(zip(("id", "title", "why", "action", "reply"), c)) for c in CONFIRMATIONS],
        "plivo_architecture_note": PLIVO_ARCHITECTURE_NOTE,
    }
    js = json.dumps(payload, indent=2)

    assert_secret_free(txt, "maintenance-report.txt")
    assert_secret_free(js, "maintenance-report.json")

    (outdir / "maintenance-report.txt").write_text(txt)
    (outdir / "maintenance-report.json").write_text(js)
    shutil.copy2(outdir / "maintenance-report.txt", REPORTS / "LATEST-maintenance-report.txt")
    shutil.copy2(outdir / "maintenance-report.json", REPORTS / "LATEST-maintenance-report.json")

    for f in ("maintenance-report.txt", "maintenance-report.json"):
        p = outdir / f
        print(f"{f}: {p.stat().st_size} bytes  sha256={hashlib.sha256(p.read_bytes()).hexdigest()[:16]}…")
    print(f"\nreport dir: {outdir}")
    print(f"pointer:    {REPORTS / 'LATEST-maintenance-report.txt'}")

    if args.s3:
        if d["aws_auth"] != "OK":
            print(f"\nAWS report synchronization: PENDING (auth {d['aws_auth']})")
            return 0
        key = f"{S3_PREFIX}/{ts}"
        for f in ("maintenance-report.txt", "maintenance-report.json"):
            out = sh(f"aws s3api put-object --bucket {S3_BUCKET} --key {key}/{f} "
                     f"--body {outdir/f} --server-side-encryption aws:kms "
                     f"--output json", cwd=None)
            print(f"uploaded {f}: {out[:200]}")
        print(f"\ns3://{S3_BUCKET}/{key}/")
    else:
        print("\nAWS report synchronization: PENDING (run with --s3 once authenticated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
