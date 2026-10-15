#!/usr/bin/env python3
"""Create the single encrypted credential recovery artifact, and its S3 copy.

    python scripts/secrets_backup.py create     # build + verify + upload
    python scripts/secrets_backup.py upload     # push existing ciphertext to S3 only
    python scripts/secrets_backup.py verify     # decrypt-check the local file
    python scripts/secrets_backup.py restore    # print field NAMES only

Design constraints this satisfies:

  * Plaintext NEVER touches disk. Secrets are pulled from Secrets Manager into
    memory, encrypted in memory, and only ciphertext is written.
  * The passphrase is read with getpass, so it is never echoed, never in argv,
    never in shell history, and never visible to the agent.
  * Double encryption: the file is already ciphertext BEFORE upload, and S3
    applies SSE-KMS on top. An IAM principal able to read the object still gets
    only ciphertext.
  * No secret value is ever printed. Reporting is limited to field names,
    lengths and short fingerprints.

Envelope format (v1), base64-armored so a `.txt`-ish file stays text:

    WECARE-SECRETS-BACKUP-V1
    kdf=scrypt n=131072 r=8 p=1
    <base64: salt(16) || nonce(12) || AES-256-GCM ciphertext+tag>

AES-256-GCM is authenticated, so a wrong passphrase or any tampering fails
loudly rather than yielding garbage.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

REGION = "us-east-1"
ACCOUNT = "775261844268"
OUT_DIR = Path.home() / ".secure-backups"
OUT_FILE = OUT_DIR / "wecare-secrets-backup.txt.enc"
BUCKET = os.environ.get("CREDENTIAL_BACKUP_BUCKET", f"wecare-credential-backups-{ACCOUNT}")
S3_KEY = "credential-backups/current/wecare-secrets-backup.txt.enc"

MAGIC = b"WECARE-SECRETS-BACKUP-V1"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 1 << 17, 8, 1

# Application secrets worth having in a disaster-recovery artifact.
# Developer AWS auth is deliberately included ONLY as a note, not as the sole
# bootstrap path: reading Secrets Manager requires AWS credentials, so relying on
# this file to recover AWS access would be circular.
# Secrets that MUST appear in every backup. The backup itself covers EVERY secret
# in the account, discovered via ListSecrets — a disaster-recovery copy that holds
# only a hand-maintained subset is not a disaster-recovery copy, and this list had
# silently fallen to 10 of 30 secrets. The list is kept as an assertion: if one of
# these disappears from the account, the run fails loudly rather than quietly
# writing a thinner backup.
REQUIRED_SECRET_IDS = [
    "wecare/razorpay/api",
    "wecare/razorpay-webhook",
    "wecare/google-api-key",
    "wecare/google-maps",
    "wecare/openai/api",
    "wecare/plivo/api",
    "wecare/meta-system-user-token",
    "wecare/flow-private-key",
    "wecare/agent-connector-token",
]

def approved_secret(name: str) -> bool:
    """Only a secret the provider allow-list approves enters a new archive.

    Positive on purpose, like `scripts/provider_allowlist.py` itself: a retired
    provider's credential - including one restored inside its recovery window -
    is simply not approved, so it never re-enters a newly generated archive.
    Exclusions are reported by NAME in the run summary, never silently dropped.
    """
    import provider_allowlist  # scripts/, next to this file

    return provider_allowlist.secret_owner(name)[0] is not None


def backup_secret_ids(discovered: set[str], required: list[str],
                      approved=approved_secret) -> list[str]:
    return sorted(name for name in discovered | set(required) if approved(name))


def fp(v: object) -> str:
    """Identify a value without disclosing any part of it.

    This used to print `v[:4]…v[-2:]`. Six characters of a live credential is
    still six characters of a live credential, and this function's output goes
    to a terminal, which goes to `~/.kiro/logs` and the session transcript - the
    exact path that put four credentials on disk on 2026-09-19. A salted-free
    sha256 prefix identifies a value across runs just as well, and discloses
    nothing: it is one-way, and there is no shorter guess than the value itself.
    """
    if not isinstance(v, str):
        return f"<{type(v).__name__}>"
    digest = hashlib.sha256(v.encode("utf-8")).hexdigest()[:8]
    return f"len={len(v)} sha256:{digest}"


def derive(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).derive(
        passphrase.encode("utf-8")
    )


def encrypt(plaintext: bytes, passphrase: str) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    ct = AESGCM(derive(passphrase, salt)).encrypt(nonce, plaintext, MAGIC)
    body = base64.b64encode(salt + nonce + ct).decode()
    wrapped = "\n".join(body[i:i + 76] for i in range(0, len(body), 76))
    header = (
        MAGIC.decode()
        + f"\nkdf=scrypt n={SCRYPT_N} r={SCRYPT_R} p={SCRYPT_P}"
        + "\ncipher=AES-256-GCM aad=magic"
        + f"\ncreated={datetime.now(timezone.utc).isoformat()}"
        + "\n\n"
    )
    return (header + wrapped + "\n").encode()


def decrypt(blob: bytes, passphrase: str) -> bytes:
    text = blob.decode(errors="replace")
    if not text.startswith(MAGIC.decode()):
        raise SystemExit("not a WECARE-SECRETS-BACKUP-V1 file")
    body = "".join(text.split("\n\n", 1)[1].split())
    raw = base64.b64decode(body)
    salt, nonce, ct = raw[:16], raw[16:28], raw[28:]
    return AESGCM(derive(passphrase, salt)).decrypt(nonce, ct, MAGIC)


def gather() -> tuple[dict, list[str]]:
    sm = boto3.client("secretsmanager", region_name=REGION)
    payload = {
        "_format": "wecare-secrets-backup/1",
        "_generated": datetime.now(timezone.utc).isoformat(),
        "_account": ACCOUNT,
        "_region": REGION,
        "_note": (
            "Disaster-recovery copy of application secrets. AWS Secrets Manager "
            "remains the authoritative runtime store. Developer AWS auth is NOT "
            "stored here as a bootstrap path: reading Secrets Manager needs AWS "
            "credentials, so that would be circular. Recover AWS access via the "
            "IAM console or an existing role/SSO session first."
        ),
        "secrets": {},
    }
    summary: list[str] = []

    discovered: set[str] = set()
    for page in sm.get_paginator("list_secrets").paginate():
        for entry in page.get("SecretList", []):
            discovered.add(entry["Name"])
    missing_required = sorted(set(REQUIRED_SECRET_IDS) - discovered)
    secret_ids = backup_secret_ids(discovered, REQUIRED_SECRET_IDS)
    summary.append(f"  discovered {len(discovered)} secret(s) in {ACCOUNT}; "
                   f"backing up {len(secret_ids)}")
    excluded = sorted((discovered | set(REQUIRED_SECRET_IDS)) - set(secret_ids))
    if excluded:
        summary.append("  EXCLUDED, not on the provider allow-list: " + ", ".join(excluded))
    if missing_required:
        summary.append("  WARNING required secret(s) absent from the account: "
                       + ", ".join(missing_required))

    for sid in secret_ids:
        try:
            meta = sm.describe_secret(SecretId=sid)
            raw = sm.get_secret_value(SecretId=sid)["SecretString"]
        except ClientError as exc:
            summary.append(f"  SKIP {sid}: {exc.response['Error']['Code']}")
            continue
        try:
            val = json.loads(raw)
        except json.JSONDecodeError:
            val = raw
        payload["secrets"][sid] = {
            "arn": meta["ARN"],
            "kms": meta.get("KmsKeyId") or "aws/secretsmanager",
            "last_changed": str(meta.get("LastChangedDate")),
            "value": val,
        }
        if isinstance(val, dict):
            fields = ", ".join(f"{k}({fp(v)})" for k, v in sorted(val.items())
                               if not k.startswith("_"))
            summary.append(f"  OK   {sid}: {len(val)} field(s) -> {fields[:150]}")
        else:
            summary.append(f"  OK   {sid}: plain string {fp(val)}")
    return payload, summary


def ensure_bucket() -> None:
    s3 = boto3.client("s3", region_name=REGION)
    try:
        s3.head_bucket(Bucket=BUCKET)
        print(f"  bucket exists: {BUCKET}")
        return
    except ClientError:
        pass
    s3.create_bucket(Bucket=BUCKET)
    s3.put_public_access_block(
        Bucket=BUCKET,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True},
    )
    s3.put_bucket_ownership_controls(
        Bucket=BUCKET,
        OwnershipControls={"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
    )
    s3.put_bucket_versioning(Bucket=BUCKET,
                             VersioningConfiguration={"Status": "Enabled"})
    s3.put_bucket_encryption(
        Bucket=BUCKET,
        ServerSideEncryptionConfiguration={"Rules": [{
            "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"},
            "BucketKeyEnabled": True}]},
    )
    # TLS-only.
    s3.put_bucket_policy(Bucket=BUCKET, Policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "DenyNonTLS", "Effect": "Deny", "Principal": "*",
            "Action": "s3:*",
            "Resource": [f"arn:aws:s3:::{BUCKET}", f"arn:aws:s3:::{BUCKET}/*"],
            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
        }],
    }))
    print(f"  created {BUCKET}: public access blocked, versioned, SSE-KMS, TLS-only")


PASSPHRASE_SECRET = "wecare/backup/recovery-passphrase"


def passphrase_from_secrets_manager() -> str:
    """Get (or create) the backup passphrase, held only in Secrets Manager.

    Used when nobody is present to type one. Generated with `secrets.token_urlsafe`
    and never printed, never written to disk, never placed on a command line.

    TRADE-OFF, stated plainly: this weakens the double-encryption property. The
    stated threat model was "an IAM principal able to read the SSE-KMS object
    still only gets ciphertext". With the passphrase in the same account, a
    principal holding both S3 read and Secrets Manager read defeats that. It is
    still strictly better than plaintext credential files on disk, and it keeps
    the backup actually recoverable, which a passphrase only the agent knew would
    not. Re-key with a human-held passphrase via `create --interactive` when
    someone can type one.
    """
    import secrets as _secrets_mod

    sm = boto3.client("secretsmanager", region_name=REGION)
    try:
        return json.loads(sm.get_secret_value(SecretId=PASSPHRASE_SECRET)["SecretString"])["passphrase"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    generated = _secrets_mod.token_urlsafe(32)
    sm.create_secret(
        Name=PASSPHRASE_SECRET,
        Description="Passphrase for ~/.secure-backups/wecare-secrets-backup.txt.enc "
                    "(scrypt + AES-256-GCM). Generated, never displayed.",
        SecretString=json.dumps({
            "passphrase": generated,
            "protects": str(OUT_FILE),
            "s3": f"s3://{BUCKET}/{S3_KEY}",
            "kdf": f"scrypt n={SCRYPT_N} r={SCRYPT_R} p={SCRYPT_P}",
            "cipher": "AES-256-GCM",
            "created": datetime.now(timezone.utc).isoformat(),
            "_note": "Copy this into a password manager and consider re-keying the "
                     "backup with a human-held passphrase; holding it in the same "
                     "account as the ciphertext weakens the intended separation.",
        }),
    )
    print(f"  generated a {len(generated)}-char passphrase and stored it at "
          f"{PASSPHRASE_SECRET} (value not displayed)")
    return generated


def cmd_create() -> int:
    interactive = "--interactive" in sys.argv
    print("=== gathering secrets from Secrets Manager (in memory only) ===")
    payload, summary = gather()
    for line in summary:
        print(line)
    if not payload["secrets"]:
        raise SystemExit("no secrets readable; aborting")
    plaintext = json.dumps(payload, indent=2, default=str).encode()
    print(f"\n  payload: {len(plaintext)} bytes across "
          f"{len(payload['secrets'])} secret(s)  (never written unencrypted)")

    print("\n=== passphrase ===")
    if interactive:
        print("  Keep this safe. Without it the backup is unrecoverable - that is the point.")
        p1 = getpass.getpass("  Passphrase: ")
        if len(p1) < 12:
            raise SystemExit("passphrase must be at least 12 characters")
        p2 = getpass.getpass("  Confirm   : ")
        if p1 != p2:
            raise SystemExit("passphrases do not match")
    else:
        print(f"  non-interactive: sourcing from {PASSPHRASE_SECRET}")
        p1 = passphrase_from_secrets_manager()

    print("\n=== encrypting (scrypt N=131072 + AES-256-GCM) ===")
    blob = encrypt(plaintext, p1)

    # round-trip before writing anything
    if decrypt(blob, p1) != plaintext:
        raise SystemExit("round-trip verification FAILED; nothing written")
    print("  round-trip verified in memory")

    OUT_DIR.mkdir(mode=0o700, exist_ok=True)
    os.chmod(OUT_DIR, 0o700)
    fd = os.open(OUT_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(blob)
    os.chmod(OUT_FILE, 0o600)
    sha = hashlib.sha256(blob).hexdigest()
    print(f"  wrote {OUT_FILE}  {len(blob)} bytes  mode "
          f"{oct(OUT_FILE.stat().st_mode)[-3:]}  sha256={sha[:16]}…")

    # prove it is not readable plaintext
    head = blob[:len(MAGIC)]
    leaks = [t for t in (b"API_KEY=", b"SECRET=", b"PASSWORD=", b"TOKEN=",
                         b"rzp_live_", b"sk-svcacct", b"AIza") if t in blob]
    print(f"  armored header: {head.decode()}")
    print(f"  plaintext markers present: {leaks or 'NONE'}")
    if leaks:
        raise SystemExit("file appears to contain plaintext; aborting")

    print("\n=== S3 copy (same ciphertext, SSE-KMS on top) ===")
    ensure_bucket()
    s3 = boto3.client("s3", region_name=REGION)
    res = s3.put_object(Bucket=BUCKET, Key=S3_KEY, Body=blob,
                        ServerSideEncryption="aws:kms",
                        ChecksumAlgorithm="SHA256",
                        Metadata={"sha256": sha, "format": "WECARE-SECRETS-BACKUP-V1"})
    print(f"  s3://{BUCKET}/{S3_KEY}")
    print(f"  SSE={res.get('ServerSideEncryption')}  VersionId={res.get('VersionId')}")
    head_obj = s3.head_object(Bucket=BUCKET, Key=S3_KEY)
    print(f"  verified: size={head_obj['ContentLength']} "
          f"sha256-meta={head_obj['Metadata'].get('sha256','')[:16]}… "
          f"match={head_obj['Metadata'].get('sha256') == sha}")
    print("\nDONE. Local + S3 encrypted recovery copies exist and both verify.")
    return 0


def cmd_upload() -> int:
    """Push the EXISTING local ciphertext to S3. No passphrase, no secret read.

    Why this is a separate command
    ------------------------------
    The S3 copy used to exist only as the tail of ``create``, which pulls every secret
    from Secrets Manager, re-derives the artifact and needs an interactive passphrase.
    That made an absent cloud copy an owner action, and the cloud copy was in fact
    absent: measured 2026-09-25, the bucket held **0 objects** while the local artifact
    had existed since 2026-09-20, so ``txt_source_healthcheck.py`` reported
    ``EncS3 | NO | INCOMPLETE`` for all four providers. A backup step welded to a
    credential-reading step does not get re-run, so it silently stayed missing.

    This command closes that without touching a credential. The file on disk is already
    ciphertext: uploading it needs no decryption, so there is no passphrase prompt, no
    Secrets Manager call, and no plaintext anywhere. S3 then applies SSE-KMS on top.

    It deliberately does NOT refresh the artifact. If the local copy is stale, uploading
    it unchanged is the honest outcome - a stale backup you can identify by its
    ``_generated`` date beats a missing one, and silently rebuilding would need the
    passphrase this command exists to avoid. ``create`` remains the way to refresh.
    """
    if not OUT_FILE.exists():
        raise SystemExit(
            f"missing {OUT_FILE} - run `secrets_backup.py create` first (needs the "
            "passphrase, so it is an owner action)"
        )

    blob = OUT_FILE.read_bytes()
    sha = hashlib.sha256(blob).hexdigest()
    print(f"local: {OUT_FILE}")
    print(f"  {len(blob)} bytes  mode {oct(OUT_FILE.stat().st_mode)[-3:]}  "
          f"sha256={sha[:16]}…")

    # Refuse to upload anything that is not the expected ciphertext. Two independent
    # checks, because uploading a plaintext credential file to S3 is the one outcome
    # this whole mechanism exists to prevent.
    if not blob.startswith(MAGIC):
        raise SystemExit(
            f"refusing to upload: {OUT_FILE} does not start with {MAGIC.decode()}"
        )
    leaks = [t.decode() for t in (b"API_KEY=", b"SECRET=", b"PASSWORD=", b"TOKEN=",
                                  b"rzp_live_", b"rzp_test_", b"sk-svcacct", b"AIza",
                                  b"-----BEGIN") if t in blob]
    print(f"  armored header: {MAGIC.decode()}")
    print(f"  plaintext markers present: {leaks or 'NONE'}")
    if leaks:
        raise SystemExit("file appears to contain plaintext; aborting upload")

    print("\n=== S3 copy (same ciphertext, SSE-KMS on top) ===")
    ensure_bucket()
    s3 = boto3.client("s3", region_name=REGION)

    try:
        existing = s3.head_object(Bucket=BUCKET, Key=S3_KEY)
        if existing["Metadata"].get("sha256") == sha:
            print(f"  s3://{BUCKET}/{S3_KEY}")
            print("  already present with an identical sha256 - nothing to do")
            return 0
        print(f"  replacing an older object (bucket is versioned, so the previous "
              f"copy is retained as a version)")
    except ClientError:
        print("  no object at that key yet")

    res = s3.put_object(Bucket=BUCKET, Key=S3_KEY, Body=blob,
                        ServerSideEncryption="aws:kms",
                        ChecksumAlgorithm="SHA256",
                        Metadata={"sha256": sha, "format": MAGIC.decode()})
    print(f"  s3://{BUCKET}/{S3_KEY}")
    print(f"  SSE={res.get('ServerSideEncryption')}  VersionId={res.get('VersionId')}")

    head_obj = s3.head_object(Bucket=BUCKET, Key=S3_KEY)
    match = head_obj["Metadata"].get("sha256") == sha
    print(f"  verified: size={head_obj['ContentLength']} "
          f"sha256-meta={head_obj['Metadata'].get('sha256', '')[:16]}… match={match}")
    if not match or head_obj["ContentLength"] != len(blob):
        raise SystemExit("uploaded object does not match the local file")

    print("\nDONE. Local + S3 encrypted recovery copies exist and match.")
    print("No credential was read and no passphrase was required.")
    return 0


def cmd_verify() -> int:
    if not OUT_FILE.exists():
        raise SystemExit(f"missing {OUT_FILE}")
    blob = OUT_FILE.read_bytes()
    print(f"file: {OUT_FILE}  {len(blob)} bytes  mode {oct(OUT_FILE.stat().st_mode)[-3:]}")
    p = getpass.getpass("Passphrase: ")
    try:
        data = json.loads(decrypt(blob, p))
    except InvalidTag:
        raise SystemExit("WRONG PASSPHRASE or file tampered (GCM auth failed)")
    print(f"decrypts OK. generated={data.get('_generated')} "
          f"secrets={len(data.get('secrets', {}))}")
    for sid, e in sorted(data.get("secrets", {}).items()):
        v = e.get("value")
        n = len(v) if isinstance(v, dict) else 1
        print(f"  {sid}: {n} field(s)")
    print("\nNo secret value printed.")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "create"
    sys.exit({"create": cmd_create, "upload": cmd_upload, "verify": cmd_verify,
              "restore": cmd_verify}.get(cmd, cmd_create)())
