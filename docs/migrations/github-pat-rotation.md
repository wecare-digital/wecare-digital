# Rotate `wecare/github-pat` — exposed classic PAT

Account **775261844268** · region **us-east-1** · prepared 2026-10-16 from live
read-only metadata. Finding 3c in `docs/execution/deep-audit-20261016.md`.

🔒 **Owner-executed.** Creating/revoking a GitHub token and writing the new
secret value are credential actions — done by the owner, not the agent. The
read-only facts below were gathered without ever reading the token value.

---

## Why this is urgent (live facts)

- The secret's own description reads: *"Classic token, near-full scopes. EXPOSED
  in agent transcript 2026-08-25 - retained at owner request; replace with a
  fine-grained token when convenient."*
- `LastChangedDate = 2026-08-26` — **never rotated** since the exposure, ~7 weeks.
- `LastAccessedDate = 2026-10-13` — **still actively used**, not dormant.
- A near-full-scope classic token that is known-exposed is a standing
  account-takeover risk for every repo the GitHub owner can reach.

## What uses it (so nothing breaks on rotation)

- **One consumer:** Lambda `wecare-workspace-mcp`, which reads it at
  `amplify/functions/ai/workspace-mcp/handler.py:488` via `get_secret_value` and
  pulls the field named by env `GITHUB_TOKEN_FIELD` (default `token`). So the
  secret is a JSON object: `{"token": "<the PAT>"}`.
- **IAM:** `GetSecretValue` granted only to `wecare-workspace-mcp-runtime`
  (`amplify/infra/workspace-mcp.json`); already denied to the shared role.
- **Built-in verification lever:** the handler's `github_status()` calls
  `GET /repos/wecare-digital/wecare-digital` and returns the token's
  `permissions`. Use it to prove the new token works before revoking the old one.

---

## The rotation, step by step

### Step 1 — 🔒 create the replacement on GitHub (owner)
Prefer a **fine-grained PAT** (or a GitHub App) over another classic token:
- Repository access: only `wecare-digital/wecare-digital` (and any other repo the
  MCP genuinely touches — check what `workspace-mcp` actually calls).
- Permissions: the minimum the MCP uses. From the handler it reads repo
  metadata; grant Contents / Metadata / Pull requests / Actions **only as needed**,
  read-vs-write matched to what it does. Start minimal; widen only if a call 403s.
- Copy the new token once. Do **not** paste it into chat, a file, or a commit.

### Step 2 — 🔒 write the new value into the secret (owner, value never in history)
Put the token in a temp file so it never hits shell history, then shred it:
```sh
umask 077
cat > /tmp/ghpat.json <<'EOF'
{"token": "PASTE_NEW_FINE_GRAINED_TOKEN_HERE"}
EOF

aws secretsmanager put-secret-value \
  --secret-id wecare/github-pat \
  --secret-string file:///tmp/ghpat.json \
  --region us-east-1

rm -P /tmp/ghpat.json      # overwrite + delete
```
This creates a new `AWSCURRENT` version; the previous version becomes
`AWSPREVIOUS` (instant rollback — see below). The JSON shape must stay
`{"token": ...}` to match `GITHUB_TOKEN_FIELD=token`.

### Step 3 — verify the new token works (before revoking the old one)
Invoke the consumer's status path (adjust the payload to however the MCP exposes
`github_status`; this is the shape it checks):
```sh
aws lambda invoke --function-name wecare-workspace-mcp \
  --payload '{"action":"github_status"}' --cli-binary-format raw-in-base64-out \
  --region us-east-1 /tmp/ghstatus.json >/dev/null && cat /tmp/ghstatus.json; echo
# EXPECT: repository "wecare-digital/wecare-digital" and a permissions block.
# A 401/403 means the new token's scopes are too narrow — widen in Step 1 and
# redo Step 2. Do NOT proceed to Step 4 until this returns clean.
rm -f /tmp/ghstatus.json
```

### Step 4 — 🔒 revoke the OLD token on GitHub (this closes the exposure)
Only after Step 3 is green: on GitHub, delete/revoke the old **classic** token.
Revoking the old token is the step that actually fixes the finding — a new token
alongside a live old one changes nothing.

### Step 5 — tidy up
- Update the secret description to drop "EXPOSED …" and note the rotation date and
  that it is now fine-grained:
  ```sh
  aws secretsmanager update-secret --secret-id wecare/github-pat \
    --description "GitHub fine-grained token for wecare-digital workspace-mcp; rotated 2026-10-16; scoped to wecare-digital/wecare-digital" \
    --region us-east-1
  ```
- Confirm `LastAccessedDate` advances on the next MCP run (token in use).

### Rollback
If the new token misbehaves after Step 2 but before Step 4, restore the prior
version instantly — the old token is still valid until Step 4:
```sh
# Find the AWSPREVIOUS version id:
aws secretsmanager describe-secret --secret-id wecare/github-pat \
  --query VersionIdsToStages --region us-east-1
# Promote AWSPREVIOUS back to AWSCURRENT:
aws secretsmanager update-secret-version-stage --secret-id wecare/github-pat \
  --version-stage AWSCURRENT \
  --move-to-version-id <AWSPREVIOUS_ID> \
  --remove-from-version-id <current_AWSCURRENT_ID> \
  --region us-east-1
```
After Step 4 the old token is dead and cannot be restored — by then the new one
is proven, so there is nothing to roll back to.

---

## Verification checklist (owner signs off)

- [ ] New token is **fine-grained**, scoped to the repo(s) the MCP needs, minimum
      permissions.
- [ ] `put-secret-value` done; shape is `{"token": ...}`; temp file shredded.
- [ ] `github_status` via `wecare-workspace-mcp` returns the repo + permissions
      with the new token.
- [ ] Old classic token **revoked on GitHub**.
- [ ] Secret description updated; "EXPOSED" note removed; rotation dated.
- [ ] No new failures from `wecare-workspace-mcp` after cutover.

## Credential hygiene

The token value never belongs in chat, a tracked file, a log, or shell history.
Use the temp-file path above and shred it. This repo's secret-safety rules and
`docs/SECURITY_AND_SECRETS.md` apply.
