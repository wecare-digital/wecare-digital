# SCOPE EXTENSION #3 — order-number format: mint/display the LATEST format only (owner, 2026-10-09)

Owner instruction: "use the latest order-number format and remove the old form where applicable."
Binding, additive. All safety rules still apply (fail-closed, no secret reads, no deploy/gate,
scoped `git commit --only`, preserve historical data). Add this as **FEAT-005** in the build
loop AFTER FEAT-003/FEAT-004, through the same test + dual-review gate. Do NOT bolt it onto an
in-flight FEAT.

## The two formats (verified in order_keys.py at the worktree base)
- **LATEST / current:** `WD-ORD-` + 8 symbols from PUBLIC_ORDER_NUMBER_ALPHABET
  ("23456789ABCDEFGHJKMNPQRSTVWXYZ"). Minted by `mint_public_order_number` (:286) /
  `reserve_public_order_number`. `is_current_public_order_number` (:238) matches ONLY this.
- **LEGACY:** a bare 12-char form and a spaced `WD-ORD - A1B2C3D4 - ...` form, minted by
  `reserve_order_number` (:640) via `wix_domain._generate_wd_order_number`.
  `is_public_order_number` (:222) deliberately accepts BOTH forms.

## The decision (safe interpretation of "use latest, remove old")
"Remove old" = stop PRODUCING the old form; it does NOT mean stop RECOGNIZING it. Real
historical orders exist in production with the legacy form, so lookups/ownership must keep
accepting legacy or existing customers' past orders stop resolving (data-integrity breakage).

1. **Checkout (our own new orders):** ALREADY uses `reserve_public_order_number` (new format)
   at order_creation.py:376 — leave as-is, confirm it with a test that asserts the minted
   number passes `is_current_public_order_number`.
2. **Wix backfill minter `reserve_order_number` / `_generate_wd_order_number`:** switch it to
   produce the LATEST `WD-ORD-`+8 shape so NOTHING new is minted in the legacy shape. Keep the
   function name/call-site (wix-store sync/backfill); only the generated SHAPE changes. Add a
   test asserting new backfill numbers satisfy `is_current_public_order_number`, and that a
   collision retry still works.
3. **Lookups/validators:** `is_public_order_number` KEEPS accepting legacy (backward compat) —
   do NOT narrow it. Where DISPLAY/OWNERSHIP logic was recently changed to require
   `is_public_order_number` (FEAT-003 F-6 list_orders), that stays as-is: it still accepts
   legacy for old orders, which is correct. The point of this FEAT is minting, not rejecting.
4. **Placeholder / example strings only (cosmetic, safe):** modernize the old-format EXAMPLES
   to the new shape where they are illustrative, NOT where they are fixtures asserting legacy
   acceptance on purpose:
   - flows/design-drafts/*.json `__example__` and `id` values `WD-ORD - A1B2C3D4 - ... - IST`
     → a representative new-format value (these are UNPUBLISHED drafts; confirm none is a
     published Flow before editing).
   - template_presets.py `WD-ORD-A1B2C3D4` example → a valid new-format value.
   - Do NOT touch tests that deliberately assert LEGACY acceptance in `is_public_order_number`
     (those prove backward-compat and must stay). Leave `WD-PAY-`, `WD-REQ-`, `WD-SR-`,
     `WD-SUB-`, `WD-REF-` prefixes alone unless the owner names them — this instruction is
     about the ORDER number (`WD-ORD-`) only.

## Acceptance
- New checkout orders and new Wix-backfill orders both satisfy `is_current_public_order_number`.
- `is_public_order_number` still returns True for a legacy 12-char and spaced value (regression
  test proving historical orders still resolve).
- Example/placeholder old-format strings in drafts/templates updated; no published Flow JSON
  altered without owner confirm.
- Whole venv pytest suite green except the one inherited OIDC failure; frontend typecheck/lint/
  vitest/build green for any src/ change. Scoped commits. No deploy (OWNER CONFIRM).
- If modernizing a draft Flow example would require editing a PUBLISHED Flow, STOP and record
  it as OWNER CONFIRM instead.
