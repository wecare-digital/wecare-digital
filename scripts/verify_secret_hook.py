#!/usr/bin/env python3
"""Verify the block_inline_secrets hook end to end.

Secret-shaped test values are ASSEMBLED AT RUNTIME from fragments, so this
file itself contains no literal that would trip the very guard it tests
(and no literal that could be recorded anywhere).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = json.loads((ROOT / ".kiro/hooks/block-inline-secrets.json").read_text())
HOOK_CMD = HOOK["hooks"][0]["action"]["command"]

def _join(*parts: str) -> str:
    """Concatenate through a function call so the compiler cannot fold it.

    CPython constant-folds `"ks" + "k_" + "d" * 32` at COMPILE time, which put the
    fully assembled test value into scripts/__pycache__/*.pyc as a literal - found
    2026-09-29 by grepping the tree for a new issuer prefix and hitting this file's
    own bytecode. Splitting a string across `+` therefore protects the source and
    not the artifact, which is the opposite of what the docstring promised. A call
    is opaque to the folder, so the pieces stay pieces on disk.
    """
    return "".join(parts)


A = "A" * 24
# assembled, never literal - see _join on why this is not plain `+`
RZP = _join("rzp", "_live_", "ABCDEFGH1234")
OAI = _join("sk", "-svcacct-", A)
GK = _join("AIz", "a", "Sy", "B" * 33)
AWSK = _join("AKI", "A", "IOSFODNN7EXAMPLE")
GH = _join("ghp", "_", "c" * 36)
PEM = _join("-----BEGIN ", "RSA PRIVATE KEY-----")
KIRO = _join("ks", "k_", "d" * 32)

CASES = [
    # (label, payload dict, expected exit)
    ("razorpay live inline",   {"command": f'RZP_ID="{RZP}" python3 -c 1'}, 2),
    ("openai svcacct inline",  {"command": f'OPENAI_ADS_KEY="{OAI}" python3 x.py'}, 2),
    ("google api key inline",  {"command": f'GOOGLE_KEY="{GK}" python3 x.py'}, 2),
    ("aws access key id",      {"command": f"AWS_ACCESS_KEY_ID={AWSK} aws s3 ls"}, 2),
    ("github token in url",    {"command": f"git clone https://{GH}@github.com/x/y"}, 2),
    ("private key pem",        {"command": f'echo "{PEM}" > k.pem'}, 2),
    ("generic SECRET= literal", {"command": f'SOME_API_SECRET="{A}" ./run.sh'}, 2),
    # Both halves, because the assignment pattern and the issuer pattern fail
    # independently: the bare form is what a paste into a gh command looks like.
    ("kiro key inline",        {"command": f'KIRO_API_KEY="{KIRO}" ./run.sh'}, 2),
    ("kiro key bare",          {"command": f"gh secret set KIRO_API_KEY -b {KIRO}"}, 2),

    ("plain build",            {"command": "npm run build"}, 0),
    ("pytest",                 {"command": ".venv/bin/python -m pytest -q"}, 0),
    ("git push",               {"command": "git push origin wecare.digital"}, 0),
    ("listening port",         {"command": "lsof -nP -iTCP:5476 -sTCP:LISTEN"}, 0),
    ("NODE_ENV",               {"command": "NODE_ENV=production npm run build"}, 0),
    ("secret by NAME boto3",   {"command": "py -c \"c.get_secret_value(SecretId='wecare/razorpay-webhook')\""}, 0),
    ("secret by NAME cli",     {"command": "asm-exec --secret-id wecare/google-maps"}, 0),
    ("cfn resolve ref",        {"command": "deploy --p {{resolve:secretsmanager:wecare/google-maps:SecretString:api_key}}"}, 0),
    ("env var NAME not value", {"command": "RAZORPAY_WEBHOOK_SECRET=wecare/razorpay-webhook python3 app.py"}, 0),
    ("brew install",           {"command": "brew install ffmpeg"}, 0),
    ("empty",                  {}, 0),

    # The MCP route, added 2026-09-20. `aws___run_script` is auto-approved in
    # ~/.kiro/settings/mcp.json and runs arbitrary Python, so its `code` payload
    # can carry a literal credential exactly as a shell command can. The guard
    # script needed no change - extract_text() flattens the whole payload - but
    # the hook MATCHER had to be widened, and that is the part that can silently
    # regress. See also test_matcher_covers_mcp().
    ("mcp run_script openai key in code",
     {"toolName": "mcp_aws_mcp_aws___run_script",
      "code": f"key = '{OAI}'"}, 2),
    ("mcp run_script razorpay key in code",
     {"toolName": "mcp_aws_mcp_aws___run_script",
      "code": f"RZP_ID = '{RZP}'"}, 2),
    ("mcp run_script google key in code",
     {"toolName": "mcp_aws_mcp_aws___run_script",
      "code": f"k = '{GK}'"}, 2),
    ("mcp run_script by-NAME secret work",
     {"toolName": "mcp_aws_mcp_aws___run_script",
      "code": "await call_boto3(service_name='secretsmanager',"
              " operation_name='DescribeSecret',"
              " params={'SecretId': 'wecare/razorpay-webhook'})"}, 0),
    ("mcp run_script ordinary read",
     {"toolName": "mcp_aws_mcp_aws___run_script",
      "code": "await call_boto3(service_name='lambda',"
              " operation_name='ListFunctions')"}, 0),
]

# Tool names the guard must actually be wired to. A guard whose matcher does not
# match is a silent no-op, which is worse than a known gap: the self-test above
# would still pass, because it invokes the script directly and never consults the
# matcher. Verified against the `toolName` field recorded in session transcripts.
MUST_MATCH_TOOLS = [
    "execute_bash",
    "control_bash_process",
    "mcp_aws_mcp_aws___run_script",
]


def run(payload: dict) -> int:
    p = subprocess.run(
        ["sh", "-c", HOOK_CMD],
        input=json.dumps(payload).encode() if payload else b"",
        capture_output=True,
    )
    return p.returncode


def test_matcher_covers_mcp() -> tuple[int, int]:
    """The matcher is a regex tested against the tool name; prove it fires."""
    matcher = HOOK["hooks"][0].get("matcher", "")
    ok = bad = 0
    print(f"matcher under test:\n  {matcher!r}\n")
    for tool in MUST_MATCH_TOOLS:
        hit = bool(re.search(matcher, tool)) if matcher else False
        verdict = "PASS" if hit else "FAIL"
        ok, bad = (ok + 1, bad) if hit else (ok, bad + 1)
        print(f"  {verdict}  matcher fires on  {tool}")
    print()
    return ok, bad


def main() -> int:
    ok, bad = test_matcher_covers_mcp()
    print(f"hook command under test:\n  {HOOK_CMD}\n")
    for label, payload, want in CASES:
        got = run(payload)
        verdict = "PASS" if got == want else "FAIL"
        if got == want:
            ok += 1
        else:
            bad += 1
        kind = "block" if want == 2 else "allow"
        print(f"  {verdict}  expect-{kind:5s} got={got}  {label}")
    print(f"\n{ok} passed, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
