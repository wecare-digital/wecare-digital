#!/usr/bin/env python3
"""Repoint the Amplify app at the renamed GitHub repository.

WHY. The GitHub repo was renamed `bharat-stack` -> `wecare-digital` on 2026-09-27,
between Amplify job 960 (08:47 IST, SUCCEED) and commit `113cc75a` (09:06 IST, the
first push that produced no job at all). The app's `repository` field still names
the old path, so GitHub's push webhooks are accepted with HTTP 202 and then
dropped, and every build started by hand dies at

    !!! Unable to assume specified IAM Role.

which is emitted before the clone step and is not about `iamServiceRoleArn` -- job
966 ran with that field cleared and failed identically. `UpdateApp` refuses a
`repository` change without a token ("You should at least provide one valid
token"), and `CreateDeployment` refuses the manual-artifact route while a
repository is connected, so this field is the only lever.

SECRET HANDLING. The GitHub token is read from the `gh` CLI's keyring **into
memory** and handed to boto3. It is never an argument, never an environment
assignment on a command line, never printed, and never written to disk -- the rule
in `.kiro/steering/secret-handling.md` (retired; now .kiro/steering/00-common.md) is that secrets pass by reference, and
`gh auth token` is the reference. `subprocess` is given a list, so the value never
reaches a shell. Failures are reported by exception type, since an error string can
echo the request body.

    python scripts/amplify_repoint_repository.py --status
    python scripts/amplify_repoint_repository.py --apply
"""

from __future__ import annotations

import argparse
import subprocess
import sys

import boto3
from botocore.exceptions import ClientError

APP_ID = "d22dm4b0jn71jw"
TARGET_REPOSITORY = "https://github.com/wecare-digital/wecare-digital"


def _github_token() -> str:
    """Read the token from the gh CLI keyring. Returned value must not be logged."""
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True,
                                text=True, check=True)
    except FileNotFoundError:
        raise SystemExit("gh CLI not found -- cannot obtain a GitHub token by reference")
    except subprocess.CalledProcessError:
        raise SystemExit("gh auth token failed -- run `gh auth login` first")
    token = result.stdout.strip()
    if not token:
        raise SystemExit("gh auth token returned nothing")
    return token


def _describe(amp) -> dict:
    app = amp.get_app(appId=APP_ID)["app"]
    return {
        "repository": app.get("repository"),
        "repositoryCloneMethod": app.get("repositoryCloneMethod"),
        "iamServiceRoleArn": app.get("iamServiceRoleArn"),
        "productionBranch": (app.get("productionBranch") or {}).get("branchName"),
        "lastDeployTime": str((app.get("productionBranch") or {}).get("lastDeployTime")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--repository", default=TARGET_REPOSITORY)
    args = parser.parse_args()

    amp = boto3.client("amplify", region_name="us-east-1")
    before = _describe(amp)
    for key, value in before.items():
        print(f"before  {key}: {value}")

    if args.status or not args.apply:
        print("\n(read-only; pass --apply to change the repository field)")
        return 0

    if before["repository"] == args.repository:
        print("\nalready pointing at the target repository -- nothing to do")
        return 0

    token = _github_token()
    try:
        amp.update_app(appId=APP_ID, repository=args.repository, accessToken=token)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        message = exc.response["Error"]["Message"]
        print(f"\nUpdateApp refused: {code}: {message}", file=sys.stderr)
        return 1
    finally:
        del token

    after = _describe(amp)
    print()
    for key, value in after.items():
        print(f"after   {key}: {value}")
    ok = after["repository"] == args.repository
    print(f"\nrepository repointed: {'YES' if ok else 'NO'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
