# Credential rotation runbook — 2026-09-19 leak

Four live credentials were found in cleartext in Kiro's workspace permissions
file. This is the rotation procedure, ordered by blast radius.

**Contains no secret values.** Only names, locations, and consumers.

## Why rotation is mandatory, not optional

The values were written to disk in cleartext in **6 files, 141 occurrences**,
including an IDE log (99) and a session transcript (10). Scrubbing files without
rotating achieves nothing: treat every value as compromised.

Verified clean, so no history rewrite is required:

- **git history** — all 19,128 objects across every ref: **0 occurrences**
- **shell history** — `.zsh_history`, `.bash_history`: **0 occurrences**
- **repo working tree** — **0 occurrences**

## Order of work

Rotate **Razorpay first**. It is the only credential that can move money, and it
is a `rzp_live_` pair, not test.

---

### 1. Razorpay — LIVE API key id + secret · CRITICAL

| | |
|---|---|
| Secrets Manager | `wecare/razorpay-webhook` → fields `key_id`, `key_secret` |
| Read by | `wecare-partner-onboarding` (`_razorpay_creds()`, handler.py:542) |
| Used for | customer-service wallet top-up — creates payment links |
| Also in that secret | `webhook_secret`, read by `wecare-razorpay-webhook` for signature verification |

**Do not rotate `webhook_secret` at the same time** unless you also update the
endpoint config in the Razorpay dashboard — that would break inbound payment
webhooks, which is the authoritative payment path.

1. Razorpay Dashboard → Account & Settings → API Keys → **Regenerate Live Key**.
   Capture the new id and secret once; Razorpay shows the secret a single time.
2. Update **only** `key_id` and `key_secret` in `wecare/razorpay-webhook`,
   preserving `webhook_secret`. Use the console or `asm-exec`; do not echo values.
3. Verify: `POST /partner/topup` should stop returning
   `501 Razorpay API keys not configured` and create a live payment link.
4. Revoke the old key in the dashboard **after** step 3 passes.

Failure mode if skipped: top-up returns 501. Payment *capture* keeps working,
because that path uses `webhook_secret`, not the API pair.

---

### 2. Google API key · HIGH

| | |
|---|---|
| Secrets Manager | `wecare/google-maps` → field `api_key` |
| Read by | `wecare-whatsapp-templates` (Google Maps Places proxy, handler.py:113-124) |
| Used for | location-template address lookup; cached in `_gmaps_key_cache` |

1. Google Cloud Console → APIs & Services → Credentials → create a **new** API
   key, restricted to the Places API and to your server IPs/referrers.
2. Update `api_key` in `wecare/google-maps`.
3. The Lambda caches the key in module scope, so **publish a new version and move
   the `live` alias** or the old key stays in the SnapStart snapshot:
   `python scripts/deploy_all_lambdas.py wecare-whatsapp-templates`
4. Verify a location template resolves an address, then delete the old key.

Note: this key was also the `ORIGINAL_KEY`/`CANONICAL_GOOGLE_KEY` in the leaked
command strings, so confirm whether anything outside this repo uses it before
deleting.

---

### 3. OpenAI service-account key · HIGH, zero production risk

| | |
|---|---|
| Secrets Manager | **none — no entry exists** |
| Read by | **no Lambda.** Verified: no `OPENAI_API_KEY` / `openai.` reference anywhere under `amplify/functions/` |
| Used for | ad-hoc local scripts only (`OPENAI_ADS_KEY=... python3`) |

This is exactly why it leaked: with no Secrets Manager home, it was passed inline.

1. platform.openai.com → Settings → API keys → revoke the service-account key.
2. Create a replacement **only if something still needs it**.
3. If it is needed, give it a proper home rather than an inline env var: create
   `wecare/openai-ads` and read it by name.

Nothing in production breaks. Revoke freely.

---

### 4. Plivo auth id + token · HIGH, zero production risk

| | |
|---|---|
| Secrets Manager | **none — no entry exists** |
| Read by | **no Lambda.** `wecare-plivo-answer` only reads `PLIVO_ANSWER_TOKEN` (an unrelated shared token for its answer URL) and returns static XML |
| Used for | ad-hoc local provisioning/testing calls |

1. Plivo Console → Account → Keys & Credentials → rotate the auth token.
2. Create `wecare/plivo-api` if ongoing programmatic use is needed.

Note: `PLIVO_ANSWER_TOKEN` on `wecare-plivo-answer` is a **different** secret and
was not leaked. Leave it alone.

---

## After rotating

1. Install the hardened permissions file (removes the six credential-bearing
   allow-patterns). Kiro hard-denies agent writes to this path, so run it yourself:
   ```
   cp ~/.local/share/kiro-maintenance-backup/20260919-063734/STAGED-workspace-permissions.yaml \
      ~/.kiro/workspace-roots/df7bb16a63efe7f7/permissions.yaml
   ```
2. Restart Kiro. The two logs holding the values belong to the **running** IDE
   session (`~/.kiro/logs/20260918T060951815/kiro.log`,
   `~/Library/Application Support/Kiro/logs/20260918T113948/.../Kiro Logs.log`)
   and rotate on restart. They were deliberately not truncated while live.
3. Handle `~/aws-new-keys-SAVE-THEN-DELETE.txt` — it holds **5 occurrences of the
   above credentials in addition to AWS keys**, so it is a broader dump than its
   name suggests. Move to a password manager, then delete.
4. The session transcript
   `~/.kiro/sessions/df7bb16a63efe7f7/sess_2100c42e-.../messages.jsonl` also
   contains occurrences. It is your conversation history, so it was left
   intact — delete that session if you want the footprint gone.
5. Confirm the guard is active: `python scripts/verify_secret_hook.py` → 18/18.

## Current footprint

Re-measure any time with `python scripts/audit_leak_footprint.py` (prints paths
and counts only, never values). As of 2026-09-19 after remediation:

| Occurrences | Location | Disposition |
|---|---|---|
| 102 | `~/Library/Application Support/Kiro/logs/20260918T113948/.../Kiro Logs.log` | live IDE log — rotates on restart |
| 12 | `~/.kiro/sessions/df7bb16a63efe7f7/sess_2100c42e-.../messages.jsonl` | your conversation history — left intact by choice |
| 9 | `~/.kiro/workspace-roots/df7bb16a63efe7f7/permissions.yaml` | replace with the staged file (step 1) |
| 9 | `~/.kiro/logs/20260918T060951815/kiro.log` | live IDE log — rotates on restart |
| 5 | `~/aws-new-keys-SAVE-THEN-DELETE.txt` | delete after saving (step 3) |
| 2 | `~/Library/Application Support/Kiro/User/globalStorage/state.vscdb` | Kiro's global storage SQLite DB; clears as the IDE ages out old state |
| **139** | **total** | |

Already clean and verified: git history (all objects, every ref), shell history,
the repo working tree, and the maintenance snapshot backup (redacted in place —
values replaced with `<REDACTED:prefix…suffix:len>` fingerprints so the record of
*what* leaked survives without the values).

**None of this matters once the four credentials are rotated.** Rotation is the
fix; file cleanup is hygiene.

---

## DEFERRED — decision recorded 2026-09-19

Rotation is deliberately deferred until the current project milestone completes.
Recorded here so the deferral is a decision with a trigger, not an omission.

**Trigger: rotate at project completion, Razorpay first.**

### What makes the deferral defensible

Exposure was measured as **local disk only**:

- **Time Machine: no destination configured.** No backups exist, so no copy has
  propagated off-machine.
- **iCloud Drive is active**, but every affected path (`$HOME` root, `~/.kiro`,
  `~/Library`) is outside the synced set. Desktop and Documents are empty.
- **git history, shell history and the repo working tree are clean** — verified
  across all objects and every ref, so nothing reached GitHub.

The material risk is therefore: anyone with read access to this machine's disk,
or any future process that ships these logs somewhere.

### Compensating controls to apply while deferring

These reduce risk without rotating anything:

1. **Restart Kiro.** 111 of the 139 occurrences live in two logs owned by the
   running IDE session. A restart rotates them and drops the footprint to ~28.
2. **Install the hardened permissions file** (step 1 above). Worth doing
   independently of rotation: it also removes the blanket `aws *`, `rm *`,
   `dd *`, `chmod *`, `kill *`, `bash *`, `eval *` allow-patterns.
3. **Restrict rather than rotate the Google key.** In GCP → Credentials, scope
   it to the Places API and to server IPs/referrers. A restricted leaked key is
   far less useful to anyone holding it, and restriction causes no downtime.
4. **Delete `~/aws-new-keys-SAVE-THEN-DELETE.txt`** once saved to a password
   manager. 5 occurrences, and it is a broader dump than its name implies.
5. **Switch from prevention to detection for Razorpay.** This is the one
   credential that can move money. Enable payment/settlement alerts and review
   recent activity for links or orders you did not create. If anything
   unexplained appears, rotate immediately and ignore this deferral.
6. **Do not add a Time Machine destination or move these paths into iCloud**
   until after rotation. Doing so would convert a local-only exposure into a
   replicated one.

### Still safe to revoke right now, at zero production risk

`OpenAI` and `Plivo` are consumed by **no Lambda** (verified: no
`OPENAI_API_KEY`, `openai.`, or `PLIVO_AUTH` reference under
`amplify/functions/`). Revoking them cannot break the project, so they need not
wait for the milestone. Only Razorpay and Google have production consumers.

### Re-check before rotating

```
python scripts/audit_leak_footprint.py    # where the values still are
python scripts/verify_secret_hook.py      # guard still active (18/18)
```

## Preventing recurrence

`.kiro/hooks/block-inline-secrets.json` now blocks inline credentials before the
command runs. See `.kiro/steering/secret-handling.md`.

Root cause worth fixing beyond rotation: **two of the four credentials had no
Secrets Manager entry at all.** Until every credential has a home to be
referenced from, inline passing stays the path of least resistance.

---

## The single Google key is a BROWSER key — and that breaks the server side

**Measured 2026-09-25 against the live project. This supersedes an earlier note in
this file that said the unified key must never go into Amplify; that note was wrong
and is deleted rather than left to be found.**

### What is actually there

```
gcloud services api-keys list --project=wecaredigitalbw
```

**One** key — `WECARE Unified Google API Key`, created 2026-08-17 — with:

| | |
|---|---|
| Restriction type | `browserKeyRestrictions` |
| Allowed referrers | `https://wecare.digital/*`, `https://*.wecare.digital/*`, `places.googleapis.com`, `*.googleapis.com/*` |
| `apiTargets` | **49 services** |
| Fingerprint | `sha256:0bd4beb6…` (same value in `wecare/google/cloud`, `wecare/google-api-key`, `wecare/google-maps`) |

So it is a **browser key**, already restricted to exactly the two referrers
`.env.local.example` asks for. A referrer-restricted browser key is public by
Google's own design — restriction, not secrecy, is the control. It is therefore a
**legitimate** `NEXT_PUBLIC_GOOGLE_MAPS_KEY` value.

### The real defect, which runs the other way

A key with referrer restrictions **cannot be used server-side at all**:

```
python scripts/check_secrets_live.py --only google

  wecare/google-api-key   INVALID  REQUEST_DENIED: API keys with referer
                                   restrictions cannot be used with this API.
  wecare/google/cloud     INVALID  REQUEST_DENIED: (same)
```

Two consumers call it from Lambda with **no `Referer` header**, so both are being
refused by Google right now:

| Consumer | Call | Consequence |
|---|---|---|
| `wecare-whatsapp-templates` | Places Autocomplete + Place Details (`handler.py:113-175`) | **Broken.** No fallback — location-template address lookup cannot work |
| `wecare-site-language` | Translate v2 (`handler.py:69-77`) | **Silently degraded.** `SITE_LANGUAGE_TRANSLATE_PROVIDER=auto` falls back to AWS Translate, which is why nobody noticed |

`whatsapp-templates`' own comment says the key is "never exposed to the browser" —
an intent the key's restrictions defeat. One key is being asked to serve two
incompatible purposes, and the browser restriction already silently disabled the
server half.

### What to do

**1. The map (safe now).** Set `NEXT_PUBLIC_GOOGLE_MAPS_KEY` to this key in the
Amplify console — app `d22dm4b0jn71jw`, branch `stack` — then redeploy, because the
value is read at build time. Paste it in the console, never on a command line
(`block-inline-secrets` refuses `AIza`-prefixed values in a command, and that rule
exists because of the 2026-09-19 incident). Verify with
`node tools/browser/contactcheck.js`, expecting 13/13.

**2. Narrow it before publishing, and this is the part that matters.** **57** API
targets — re-measured 2026-09-30, up from the 49 recorded when this was written, so the
surface is growing rather than holding. On a key that will sit in a public JS chunk that
is a wide billing surface. The eight added since include the seven Business Profile APIs
plus `businessaicode`, which an API key cannot authorise at all — Business Profile
requires OAuth — so they are inert targets that widen the list without enabling
anything.
Referrer restrictions stop casual reuse from another website; they do **not** stop
deliberate abuse, because a `Referer` header is trivially forged with `curl`. The
browser needs Maps JavaScript API (`maps-backend`) and little else. These are on the
key today and a web map does not need any of them:

`translate` · `language` · `vision` · `youtube` · `customsearch` ·
`pagespeedonline` · `webrisk` · `factchecktools` · `kgsearch` ·
`streetviewpublish` · `routeoptimization` · `mapsplatformdatasets`

**3. Create a second, server key** — IP-restricted or unrestricted, **not** referrer
restricted — and point `wecare/google-maps` (Places) and `wecare/google/cloud`
(Translate) at it. This is not tidiness; it is the fix for a feature that is
currently failing. Having done that, add the server key's fingerprint to
`FORBIDDEN_FINGERPRINTS` in `scripts/verify_public_bundle_secrets.py`, because
*that* key genuinely must never reach the export. Remember both Lambdas cache the
key at first use, so publish a new version and move the `live` alias:
`python scripts/refresh_secret_consumers.py wecare/google-maps`.

> **READ THIS BEFORE DOING STEP 3: IT HAS ALREADY BEEN DONE ONCE, AND UNDONE.**
> Added 2026-09-30, because following the step above as written would mint a *third*
> key without knowing a second ever existed.
>
> | | |
> |---|---|
> | Key | `WECARE Address Capture Server Key`, uid `d936bd15-1009-4a63-93d0-a4eca73eff54` |
> | Created | 2026-09-26 by `scripts/provision_maps_server_key.py --create` |
> | Stored as | `wecare/google-maps-server` (still exists, single `api_key` field) |
> | Proven | live at the time — Places (New) returned suggestions, legacy Geocoding `OK` |
> | **Deleted** | **2026-09-30**, in Google Cloud |
>
> So the secret is still there and the key inside it is dead:
> `check_secrets_live.py` reports `INVALID — REQUEST_DENIED: The provided API key is
> expired`, the only INVALID credential in the account. The consumers were never
> repointed at it either, so `wecare/google-maps` and `wecare/google/cloud` still hold
> the browser key and `whatsapp-templates` is still making server-side Maps calls with
> a referrer-restricted key.
>
> **Therefore step 3 is not "create a second key" any more, it is `--create` again and
> then finish the repoint that never happened.** Reuse `provision_maps_server_key.py`
> rather than minting by hand; `wecare/google-maps-server` already exists, so this is an
> overwrite of a dead value rather than a new secret. Four keys have been created and
> deleted in this project inside six weeks — unified, unified (rotated), Map Key, Address
> Capture — so the failure mode here is key sprawl, and the way to avoid adding to it is
> to check `gcloud services api-keys list --show-deleted` before creating anything.

### Step 0, done 2026-09-30: every consumer now reads ONE secret id

The owner's instruction was "use only one key", and **not** to rotate anything yet — they will
rotate and update AWS themselves once the project is complete. Nothing was rotated. What changed
is the plumbing, because with three ids live a single rotation is unsafe:

| | before | after |
|---|---|---|
| `wecare-site-language` (Translate) | `wecare/google/cloud` | `wecare/google/cloud` |
| `wecare-whatsapp-templates` (Places) | `wecare/google-maps` | `wecare/google/cloud` |
| read by any code | 2 ids for 1 key | **1 id** |

`wecare/google-api-key` and `wecare/google-maps` are now read by **no code**. They still exist in
AWS — deleting a secret is an owner action, not something a code change should do — but nothing in
the repository depends on them. `tests/test_one_google_key.py` fails if any Lambda reads them
again.

**Why before the rotation rather than after.** Both consumers degrade quietly: `site-language`
falls back to Amazon Translate, and the Places proxies returned HTTP 200 with an empty list. A
rotation that updated one of three copies would have left the other consumers on a dead key with
nothing in the application to show it. Consolidating first is what makes the planned rotation
land everywhere.

**A contradiction this repository could not settle about itself.** Two files disagree on the field
name inside `wecare/google/cloud`:

| file | claims the field is |
|---|---|
| `scripts/store_provider_secret.py` | `api_key` |
| `scripts/check_secrets_live.py` | `unified_google_api_key` |

One is wrong and it is not decidable from the repository. Both possibilities were bad, and both
were invisible: if the field is `api_key`, then `check_secrets_live.py` has been probing a field
that does not exist and its `INVALID` verdict for this secret was a false negative rather than a
refused key; if it is `unified_google_api_key`, then `site-language` has been reading nothing and
silently serving Amazon Translate since it shipped. Both handlers now try both names in order and
log which one answered, by NAME — a field name is not a secret, and no value reaches a log.

**Two silent failures made loud.** `_google_status_problem()` in `whatsapp-templates` now returns
a diagnosis instead of letting `REQUEST_DENIED` reach the caller as HTTP 200 with an empty
prediction list, and it names the referrer case specifically. `ZERO_RESULTS` stays a success,
because it is a correct answer. `site-language` now logs *why* it fell back — unreadable secret
versus missing field — and notes that `AccessDeniedException` there is most likely `kms:Decrypt`
on the CMK rather than `GetSecretValue`, since `amplify/iam-policies.ts` grants `GetSecretValue`
on the wildcard `wecare/*` and contains no `kms:Decrypt` grant at all.

**What "one key" still cannot do, and this consolidation does not pretend to fix.** A
referrer-restricted key cannot authorise a server-side call, and an unrestricted key must not ship
in a public JS bundle. So the browser half and the server half genuinely need different keys. One
*secret id* is now true; one *key* is not achievable while any Lambda calls a Google API. Step 3
below is still outstanding, and the choice is the owner's: mint the server key again, or stop
calling Google from Lambda — `site-language` already has a working Amazon Translate path, so for
Translate the second option costs nothing.

**4. Drop the two meaningless referrer entries.** `places.googleapis.com` and
`*.googleapis.com/*` are in `allowedReferrers`. Referrer matching applies to the
`Referer` header a *client* sends, so naming Google's own API hosts there achieves
nothing — it looks like a previous attempt to make the server-side calls work, and
it did not.

### What the build gate can and cannot do

`scripts/verify_public_bundle_secrets.py` runs in the **`amplify.yml`** build, which
is the only build with the branch environment variables — GitHub Actions has none,
so the copy in `build-test.yml` is a backstop that only catches a credential
committed into the tree.

It reports any Google key found in the export with its fingerprint, and refuses
shapes with no public form at all (Razorpay live, OpenAI, AWS, GitHub, Slack, Stripe
live, PEM). It **cannot** verify that a published key is referrer-restricted:
matching a bundle fingerprint back to a GCP key would require reading key strings.
That check is step 2 above, done in the console — treat it as part of the procedure,
not something the gate will catch for you.

---

## Wix credentials — EXPOSED 2026-10-02, rotation DEFERRED to project completion

Two Wix credentials were pasted into the Kiro chat on 2026-10-02 while wiring the
catalogue-sync webhook, so both are exposed on local disk (session transcript +
IDE logs), the same exposure class as the 2026-09-19 leak above. **Contains no
values — only names, locations, and consumers.**

Rotation is deferred to project completion by owner decision (recorded 2026-10-02),
consistent with the deferral above. Trigger: rotate at PROJECT COMPLETE.

### 1. Wix App Secret Key · HIGH

| | |
|---|---|
| What | OAuth app secret for the `apiwx` Wix app (app id `6cbf8eaf-264d-495a-bde1-d63d016d58a9`) |
| Secrets Manager | `wecare/wix/app-oauth` → fields `app_id`, `app_secret` (created 2026-10-02) |
| Read by | no Lambda yet — stored for a future OAuth/token-exchange flow |
| Exposure | pasted in chat 2026-10-02; local disk only |

Rotate: Wix app dashboard → regenerate the App Secret Key, then update **only**
the `app_secret` field in `wecare/wix/app-oauth`. No consumer to redeploy today;
if one is added before rotation, add it here.

### 2. Wix headless API key · HIGH (pre-existing, owner already flagged)

| | |
|---|---|
| Secrets Manager | `wecare/wix/headless-api-key` → field `api_key` |
| Read by | `wecare-checkout` (`wix_ecom.py` `_api_key()`), and other Wix REST callers |
| Exposure | owner-noted earlier; owner will rotate later |

Rotate: Wix dashboard → regenerate the API key → update `api_key` in
`wecare/wix/headless-api-key` → then refresh warm consumers so the cached value is
dropped: `python scripts/refresh_secret_consumers.py wecare/wix/headless-api-key`.

### NOT a credential — do not rotate

The Wix webhook `public_key` in `wecare/wix/catalog-webhook` is an RSA **public**
key, not a secret. It only needs changing if the Wix app's webhook signing key is
regenerated on the Wix side (which also forces a new app version release).
