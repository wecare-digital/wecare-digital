---
inclusion: always
---

# Never put a credential on a command line

## What happened, so the rule makes sense

On 2026-09-19 an audit found **four live credentials in plaintext inside Kiro's
own workspace permissions file**, `~/.kiro/workspace-roots/<hash>/permissions.yaml`:

| Credential | Consumed by | Rotated |
|---|---|---|
| Razorpay **LIVE** key id + secret | `wecare-partner-onboarding` via `wecare/razorpay-webhook` | see runbook |
| Google API key | `wecare-whatsapp-templates` and `wecare-site-language`, both via `wecare/google/cloud` | see runbook |
| OpenAI service-account key | **nothing** - ad-hoc local use only | see runbook |
| Plivo auth id + token | **nothing** - ad-hoc local use only | see runbook |

Nobody pasted them into a config. They arrived because commands were run with
the credential inline:

```
RZP_ID='rzp_live_...' RZP_SECRET='...' python3 -c '...'
```

When that was approved with **"Always allow"**, Kiro recorded the *entire
command string* as a shell allow-pattern. The secret became a permission rule,
on disk, in cleartext, permanently.

Blast radius measured at the time: **141 copies across 6 files**, including an
IDE log with 99 occurrences and a session transcript with 10. Shell history was
clean, and no history rewrite was needed - but that was luck, not design.

**Correction, 2026-09-29: git history is not clean, and the original sentence here
claimed it was.** `scripts/txt_source_healthcheck.py` scans every blob ever
committed, and it reports one hit: the **Plivo AUTH ID**, added by `3eaead21`
(2026-09-19) in `tests/test_pstn_browser_token.py`, replaced by `55ba7844`
(2026-09-20) with a placeholder, still reachable in the blob `3eaead21` added.

**Correction, 2026-10-01: the footprint is far larger than one auth id, and the
"the token has never been committed" claim above is FALSE.** The healthcheck only
compares against a narrow value set; the deeper `scripts/scan_repo_secrets.py`
historically loaded live secret fields and compared them with the working tree
and history. That old mode is prohibited for agents. The current scanner uses
secret metadata and issuer-shaped patterns only; it cannot revalidate prefixless
values or prove that historical exposures were rotated. Historical run
2026-10-01 (10,149 blobs, 447 MB scanned, 0 errors), it reports **80 credential
occurrences across six distinct live secret values in git history**, plus one in
the current working tree. Values are never printed; only paths, counts and commit
ids:

| Secret : field | In history (blobs) | Commits |
|---|---:|---|
| `wecare/razorpay-webhook:webhook_secret` | 69 | adfaaa8c 514ec02c d3907404 fb838fb1 8f4329dd 48959f81 92097f8c |
| `wecare/plivo:auth_token` | 3 | 12c97747 8f2b6823 |
| `wecare/plivo/api:auth_token` | 3 | 12c97747 8f2b6823 |
| `wecare/plivo:sip_auth_credential_uuid` | 3 | c665c596 12c97747 f2f0a788 |
| `wecare/meta-system-user-token:client_token` | 1 | d3907404 0a01933d |
| `wecare/meta-system-user-token:client_token_waba2` | 1 | d3907404 0a01933d |

Working tree, 2026-10-01: `wecare/plivo:sip_auth_credential_uuid` appears once in
the committed file `docs/execution/snapshots/plivo-application-before-api-path.json`.

Read this precisely: the Plivo **auth token** (not just the auth id), the Razorpay
**webhook_secret** and the Meta **client_token(s)** are real, current Secrets
Manager values sitting in the git object database. The earlier statement that "the
token has never been committed" is contradicted by direct measurement — trust the
scanner over the prose. So unlike the lone auth id, this **does** imply rotation:
treat all six as exposed. Rotation is deferred to project completion by owner
decision and is a standing refusal for the agent regardless; it is owner-only work
tracked in `docs/CREDENTIAL-ROTATION-RUNBOOK.md`.

Do not "fix" this with a history rewrite. A rewrite plus force push is explicitly
prohibited, and — decisively — scrubbing history **before** rotating is theatre:
the values must be rotated first, and rotation is deferred, so history cleanup is
correctly blocked until then. The correct state is: recorded, understood, rotation
pending at project close. Preserve the historical exposure evidence and do not
allowlist known exposures to obtain a clean result. The current
`python scripts/scan_repo_secrets.py` performs **metadata and issuer-shape scanning
only**, without fetching secret values. Its shape verdict is not an exact-value
comparison and does not certify credential rotation or a clean secret history.
Review metadata errors separately from the tree/history shape result. The owner
must verify prefixless exposed families and perform the existing rotation runbook.
Agents must never run a value-fetching historical scanner mode.

## The rule

**A secret value must never appear in a command, a script argument, an
environment assignment on a command line, or a log line.** Pass secrets *by
reference*.

Correct:

```python
# inside the Lambda, at request time
raw = boto3.client('secretsmanager').get_secret_value(SecretId='wecare/razorpay-webhook')
key_id = json.loads(raw['SecretString'])['key_id']
```

```
# infrastructure
{{resolve:secretsmanager:wecare/razorpay-webhook:SecretString:key_id}}
```

Wrong, in every case:

```
KEY='sk-...' python3 script.py          # recorded by "Always allow"
export TOKEN=abc123 && ./deploy.sh      # lands in shell history
echo "$SECRET"                          # lands in logs
aws secretsmanager get-secret-value ... # pulls the value into context
```

## Corollary: a secret must not appear in a logging expression at all

Not "must not be logged" — must not **appear in the expression**. CodeQL
(`py/clear-text-logging-sensitive-data`) failed the build twice on
`amplify/functions/core/site-language/handler.py` over a line that could not leak
anything:

```python
logger.info(json.dumps({"provider": "google" if key else "aws"}))   # blocked
```

A ternary on the secret's truthiness, yielding a string literal. The key can
never reach the output. CodeQL flags it anyway, and it is right to: the analysis
cannot prove the value is discarded, and neither can a reviewer at a glance.

**CodeQL tracks taint across function boundaries.** The second attempt moved the
log to a different function and reduced the value to a bool, and still failed,
because `provider <- _google_enabled() <- _google_key() <- the secret` is one
call chain. Reducing a secret to a boolean does not launder it.

Do not suppress the alert. Remove the log, or derive the logged value from
something that never touched the secret. In that case the information was already
available on the API response and in the failure log, so the line simply went.

Exception messages count too. Log `type(exc).__name__`, and log an exception's
text only when your own code constructed that message from known-safe parts.

## Enforcement

`.kiro/hooks/block-inline-secrets.json` runs `scripts/block_inline_secrets.py`
as a **PreToolUse** hook on `execute_bash` and `control_bash_process`. It exits 2
and blocks the call when it sees an issuer-shaped token (`rzp_live_`, `sk-`,
`AIza`, `ghp_`, `xoxb-`, `AKIA`/`ASIA`, `sk_live_`, `ksk_`, PEM private-key headers) or a
`*SECRET*=`/`*TOKEN*=`/`*API_KEY*=` assignment of a quoted 20+ character literal.

It deliberately allows by-reference forms: `SecretId='wecare/...'`,
`--secret-id wecare/...`, `{{resolve:secretsmanager:...}}`, and
`SECRET_NAME=wecare/...` (a name, not a value).

It is high-precision on purpose. A noisy guard gets switched off, and a
switched-off guard protects nothing. It will not catch an arbitrary
high-entropy string with no issuer prefix - it is a backstop, not a substitute
for the rule above.

Verify it with `python scripts/verify_secret_hook.py` (25 cases; test values are
assembled at runtime so the file contains no literal secret shape).

## If a credential does leak

1. **Rotate first.** Scrubbing files before rotating is theatre - assume any
   value written to disk is compromised.
2. Update the Secrets Manager entry, not the code. See the table above for which
   secret feeds which function.
3. Then measure the on-disk footprint and clean what is safe. Do **not** delete
   session transcripts (user data) or truncate logs belonging to a running IDE;
   those rotate on restart.
4. Check git history explicitly (`git rev-list --objects --all` piped through
   `git cat-file --batch`) before assuming a rewrite is or isn't needed.

## Related

- `.kiro/steering/aws-agent-rules.md` - never call `get-secret-value`; use
  `{{resolve:secretsmanager:...}}` with `asm-exec`.
- `docs/CREDENTIAL-ROTATION-RUNBOOK.md` - the rotation procedure and which
  secret each function reads.
