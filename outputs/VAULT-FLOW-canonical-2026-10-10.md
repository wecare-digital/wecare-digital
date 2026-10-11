# Canonical Vault Flow — owner-confirmed 2026-10-10

**This is the authoritative Vault request Flow for the WECARE.DIGITAL ₹49/24h-window model.**

- Flow name: **WD_Vault_Design_v1**
- Flow ID: **1735480734227899**
- Status: DRAFT in the retirement readback (outputs/flow-retirement-2026-10-09.json). Owner to review → clone/keep → PUBLISH, then bind the published Flow ID to the Vault keyword(s) + the ₹49 catalog item from the workspace (config-driven; no redeploy).
- Design source in repo: amplify/functions/messaging/whatsapp-business-api/flows/design-drafts/vault.json (version 7.3).

## Owner-confirmed screen 1 (SELECT_ORDER) — from a live screenshot 2026-10-10
Title: "Your order" (back arrow + kebab menu — standard WhatsApp Flow chrome).
Dropdown options shown:
- "Example order · A1B2C3D4"  (placeholder; in the published Flow the list is populated SERVER-SIDE
  with ONLY the customer's own active files via the backend data-exchange — vault_request.py)
- "I cannot find my order"  (fallback → manual order-number entry / support)

Screens (routing SELECT_ORDER → DOCUMENT → REVIEW):
1. SELECT_ORDER — pick the order linked to the document (dropdown of the customer's own orders +
   "I cannot find my order"; optional manual order-number text input). "Next" →
2. DOCUMENT — pick the document for that order.
3. REVIEW — confirm & submit → backend.

## How it drives the ₹49/24h model (both entry paths)
- Entry 1 (keyword): Vault keyword → THIS Flow → customer picks their own file → backend checks a
  deliverable active file → none = "no document available, nothing charged" → deliverable = ₹49
  wecarepay_wa Review&Pay → paid → open 24h window → wecare_default_download auto-fires (file id
  suffix only) → tap → sign in → fresh 60s S3 link → download. Re-download free within 24h; after
  the window, Path C = fresh ₹49 opens a new window (same durable entitlement).
- Entry 2 (direct ₹49 catalog item): pay ₹49 → active file known = auto download template; no
  active file = send THIS SAME Flow ("payment received — which document?") → answer → deliver;
  window starts at delivery.

## IMPORTANT — replace placeholders before publish
The draft shows example order "A1B2C3D4"/"K4M7PQR9". The published Flow MUST source the dropdown
from the live data-exchange endpoint so a customer sees only their OWN active files, never example
or other customers' data. Do not publish with static example rows.

## Durability note (why this file exists)
The prior worktree (.worktrees/vault-durable-access) and its committed feature branch were deleted
in a local re-clone on 2026-10-10 08:09; the unpushed commits were unrecoverable. This note lives
in the surviving repo at /Users/wecaredigital/wecare-digital so the Vault Flow ID and the model
survive. On rebuild: push the feature branch to origin after each committed feature.
