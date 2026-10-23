# Decoding the Meta catalog release plan (before opening the gate)

Approved plan under review (2026-10-23):

    create 28 · update 0 · retire 21 · foreign 22
    PLAN_HASH = c2379ec6a50befa75bac281ac89a42c3909c2aeacf98fa5f4b86ebef6cc5e00a
    Catalog   = 1457045652952851   Approval = APPROVED   Release gates = Closed

This is the exact, honest meaning of each number, traced from
`amplify/functions/shared/lambda_utils/ecommerce/meta_catalog_sync.py::diff`. The plan is
computed as **ProductsTable (desired) vs. the live Meta catalogue (existing)**. ProductsTable
is authoritative for prices; Meta is a projected channel.

What each count DOES on Apply
-----------------------------
**create = 28** — ProductsTable has 28 desired items whose owned `retailer_id`
(`WECARE.DIGITAL:...`) is NOT present in the live Meta catalogue. Apply would ADD these 28.
This matches the 28-item release (the 3 promoted products — Activities, Ritva, VayuLok — expand
to 28 sellable variants).

**update = 0** — no owned item that exists on both sides differs in any COMPARED_FIELD
(`name, description, availability, price, currency, image_url, url`). Nothing is being re-priced
or re-described by this plan.

**retire = 21** — THE PART TO VERIFY. These are owned (`WECARE.DIGITAL:...`) items that exist in
the LIVE Meta catalogue but are NOT in the current 28 desired set, and are not already
out-of-stock. `retire` does NOT delete — it sets `availability: out of stock` and nothing else
(a delete would break an in-flight WhatsApp cart holding that `product_retailer_id`; out-of-stock
is a state the pipeline already handles). So Apply would mark 21 previously-published owned
variants out of stock. Interpretation: these are the remnants of the **previous (25-item) catalog
generation** that the new 28-item plan supersedes — expected IF the old variants are genuinely
being replaced. Confirm the 21 are old/superseded variants, not anything meant to stay sellable.

**foreign = 22** — items in the live Meta catalogue whose `retailer_id` is NOT ours
(`parse_retailer_id` returns None — e.g. `wix:` ids, or anything not matching the
`WECARE.DIGITAL` legacy/v2/v3 contracts). The sync **reports these and never touches them** —
not created, not updated, not retired. They are listed only so the plan is transparent. The Meta
catalogue is also hand-edited via catalog-builder, and the sync deliberately leaves work it does
not own alone. So the 22 foreign items are informational and SAFE — Apply does nothing to them.

How to see the actual ids (no code, read-only)
----------------------------------------------
The authenticated inspect already returns the full lists, so the owner can read the exact 21
retire ids and 22 foreign ids before deciding:

    GET /wa-business/catalog-sync        (staff Admin; action defaults to inspect)

The response carries `existingItems` (the live catalogue) and `desiredItems` (the 28). To list
them explicitly, run the plan decoder against that JSON:

    python scripts/decode_meta_plan.py < inspect.json
    # or: curl ... | python scripts/decode_meta_plan.py

It prints the create/update/retire/foreign retailer ids using the SAME diff logic as the live
handler, so what it shows is what Apply would do.

The safe/not-safe decision
--------------------------
- **create 28** and **foreign 22** are safe to apply as-is (additions of this release; foreign
  untouched).
- **retire 21** is the only state-changing effect on existing items, and it is reversible
  (out-of-stock, not delete). Open the gate + Apply ONLY after confirming those 21 are the
  superseded prior-generation variants. If any of the 21 should remain sellable, do NOT open the
  gate — fix the desired set (publication flags / variants in ProductsTable) first, which will
  re-compute a new plan hash and require a fresh approval.

Opening the gate itself is `scripts/open_meta_release_gate.py` (merge-based DRY_RUN flip); it
never approves or applies — Apply remains a separate, final owner action, reversible until pressed.
