# Post-call templates — final spec, no redirects and no old links

Drafted 2026-09-27 for approval. Every URL here was followed to its terminal
address and the hop count recorded; nothing is quoted from memory.

---

## 0. BLOCKER — fix this before any template ships

**`[retired public path 68ca05fc]` returns 404.**

```
[retired public path 68ca05fc]   301 -> [retired public path b180810d]/
[retired public path 68ca05fc]/  404
```

That is the primary call to action in the **DLT-approved SMS body**, in the
approved `rcsmenu` / `wecaremenu` / `wdorder` RCS cards, and behind the
`/r/getstarted` short link every RCS "Get Started" button uses.

Cause, dated rather than guessed: PR **#47** (`6bc44a35`, 2026-09-24 18:08)
removed the in-repo `[retired public path b180810d]` and `/product-page` redirect stubs. No Amplify
rule replaced them — the live app has **zero** custom rules mentioning
`customerservice`, out of 104. So the route has been dead for three days.

It is **not** a side effect of the `/workspace/` nesting (`c143301d`,
2026-09-27 05:44), which landed three days later and is what added the working
`[retired public path 169e0fd8]/<*>` redirect.

The page itself is alive at `https://wecare.digital/workspace/forms/customerservice/`
(200). The fix is one Amplify rule. **The SMS body cannot be changed to route
around it** — it is frozen by DLT approval — so the rule is the only option that
repairs SMS.

---

## 1. Terminal URLs — measured

| Candidate | First | Hops | Terminal | Verdict |
|---|---|---:|---|---|
| `wecare.digital/customerservice` | 301 | 1 | **404** | **broken** |
| `wecare.digital/r/getstarted` | 302 | → above | **404** | broken + a redirect |
| `wecare.digital/workspace/forms/customerservice/` | **200** | **0** | itself | terminal ✓ |
| `wecare.digital/r/wa` | 302 | 2 | api.whatsapp.com | 2 redirects |
| `wa.me/message/APDM5HUWH26SG1` | 302 | 1 | api.whatsapp.com | 1 redirect |
| `api.whatsapp.com/message/APDM5HUWH26SG1` | **200** | **0** | itself | terminal ✓ |
| `api.whatsapp.com/send?phone=919330994400` | **200** | **0** | itself | terminal ✓ |

So the only zero-redirect pair is:

```
Get Started   https://wecare.digital/workspace/forms/customerservice/
WhatsApp      https://api.whatsapp.com/message/APDM5HUWH26SG1
Call          dialer action — no URL at all
```

**One thing to decide.** The terminal customer-service URL sits inside
`/workspace/`, which is the *authenticated* namespace. It serves 200 to an
anonymous visitor today, but sending customers into an internal-looking path is a
naming decision, not a technical one. Two options:

* **A —** point the buttons at `/workspace/forms/customerservice/`. Zero redirects
  today, but a customer-facing URL that reads as internal.
* **B —** restore a real page at `[retired public path b180810d]` (not a redirect stub), then point
  the buttons there. Zero redirects **and** a clean public URL. Needs one page
  added, and it repairs the DLT-frozen SMS at the same time.

**B is the recommendation.** It is the only option that also fixes SMS, because
the SMS body already says `wecare.digital/customerservice` and cannot be edited.

---

## 2. The image

`wd-brand-16x9.png` — 1440 × 810, exactly 16:9, 782 KB, live at
`https://wecare.digital/get/o/stream/media/m/wd-brand-16x9.png` (200, `image/png`).

Built from the card artwork's branding block (x 64–1189, y 136–690 of the 1254²
original), recomposed with even margins on the sampled brand green `#01643F`.
Contains the logo, the WECARE.DIGITAL wordmark and the tagline pill. The phone,
email, website and QR were **dropped** — the buttons carry those actions now.

No video anywhere in this spec.

---

## 3. SMS

**Cannot be changed.** Body must match DLT template `ivr-default`
(`1007277993798259629`) character for character; the registry table
`stack-wecare-digital-DLTTemplates` is empty, so no other content is approved.

| | |
|---|---|
| Sender | `WDBEEP` |
| Route | AWS End User Messaging, `ap-south-1` |
| Image | none — SMS carries no media |
| Buttons | none — SMS has no buttons |

Text, exactly as approved and as sent today:

```
Thanks for contacting WECARE.DIGITAL!

Submit your request here: [retired public path 68ca05fc] or send us a
message / voice note on WhatsApp: https://wecare.digital/r/wa.

We'll review it and follow up if needed.
```

This is the one place the old short link and the broken URL **must** remain, until
new DLT content is registered. Delivery measured healthy: 60 of 68 parts in 7 days.

**Needs you:** register new DLT content on the portal if the copy is to change.

---

## 4. WhatsApp — WABA1, +91 93309 94400

| | |
|---|---|
| Name | `wd_call_menu` |
| Language / category | `en` / `UTILITY` |
| Header | **IMAGE** — `wd-brand-16x9.png` |
| Footer | `WECARE.DIGITAL` |

Body — no links, no variables:

```
Thanks for contacting WECARE.DIGITAL!

Building digital railroads for Everyday Bharat.

Tap a button below and we'll follow up.
```

Buttons and actions:

| # | Label | Type | Action | Redirects |
|---|---|---|---|---|
| 1 | `Get Started` | `URL` | opens the customer-service page | **0** once §1 is settled |
| 2 | `Call us` | `PHONE_NUMBER` | dials `+919330994400` | n/a |

**No "WhatsApp us" button** — the reader is already in WhatsApp, so it would waste
a slot on a no-op.

---

## 5. RCS — Sinch India

| | |
|---|---|
| Name | `wd_card_clean` |
| Type / orientation | `rich_card` / `VERTICAL` |
| Media | `wd-brand-16x9.png`, height `MEDIUM` |
| Title | `WECARE.DIGITAL` |

Body — no links:

```
Thanks for contacting us.
Building digital railroads for Everyday Bharat.

Choose an option below and we'll follow up.
```

Buttons and actions — 3 of the 4 a rich card allows:

| # | Label | Type | Action | Redirects |
|---|---|---|---|---|
| 1 | `Get Started` | `openUrlAction` | customer-service page | **0** once §1 is settled |
| 2 | `WhatsApp us` | `openUrlAction` | `api.whatsapp.com/message/APDM5HUWH26SG1` | **0** |
| 3 | `Call us` | `dialAction` | `+919330994400` | n/a |

The dialer type **was accepted** by this provider — tested, not assumed. The 4th
slot is left free.

---

## 6. Summary of link policy

| Channel | Old / redirect links remaining |
|---|---|
| SMS | **2** — `wecare.digital/customerservice`, `wecare.digital/r/wa`. Frozen by DLT. |
| WhatsApp | **0** |
| RCS | **0** |

Nothing in the two new templates uses `r.wecare.digital`, `wecare.digital/r/*`, or
`wa.me`. The live approved `wd_menu` and `rcsmenu` still carry the old
`r.wecare.digital/wa` host; approved bodies are frozen, so they were left rather
than pushed back into review — and that is why `r.wecare.digital` cannot be retired.

---

## 7. State, stated plainly

| Channel | Template | Status |
|---|---|---|
| SMS | `ivr-default` | unchanged; new copy needs DLT registration by you |
| WhatsApp | `wd_call_menu`, id `2168548787028295` | **created, PENDING** Meta review |
| RCS | `wd_card_clean` | **created, approved**, test-sent `01M3GEM24ZZ79YYN8T5GH5PQYB` |

Both created templates currently point `Get Started` at
`[retired public path 68ca05fc]`, which is the 404 in §0. **Neither is wired to
anything** — a real call still sends `wd_menu` and `rcsmenu`. So nothing customer
facing is broken by them, and both can be deleted or recreated.

## 8. What I need decided

1. **§1 option A or B** for the customer-service URL. B is recommended and is the only
   one that also repairs SMS.
2. Whether to **fix `[retired public path b180810d]`** now — it is a live 404 on the primary CTA,
   independent of this template work.
3. Whether to **recreate** the two templates once the URL is settled, so they ship
   with a terminal, working link rather than the 404.

---

## 9. RE-MEASURED 2026-09-28 — nothing needs re-filing; one redirect fixes nine of ten

Asked to check RCS "re-filing". There is **no filing queue to check**. Read live
through `wecare-rcs-send:live action=templates`:

    HTTP 200 · 15 templates · status tally {approved: 15} · non-approved: 0

Nothing is pending Sinch review and nothing is rejected — this provider approves
synchronously at creation, so a re-filing backlog cannot exist. A full re-sync
(`python scripts/rcs_template_sync.py`) produced **zero** substantive drift against
the 2026-09-27 snapshot; only `generatedAt` moved.

### 9.1 What is actually broken: links, not filings

Every URL in every live template was probed — button actions and media pulled from
the structured fields, body URLs from the decoded body text. 45 URLs, 10 dead:

| Template | Where | Code | URL | Sent by code? |
|---|---|---:|---|---|
| `rcsmenu` | **body text** | **404** | `wecare.digital/customerservice` | **YES — the only template any code sends** |
| `wd_card_clean` | **button** | **404** | `wecare.digital/customerservice` | no |
| `get_started` | body text | 404 | `wecare.digital/customerservice` | no |
| `wecaremenu` | body text | 404 | `wecare.digital/customerservice` | no |
| `wdorder` | body text | 404 | `wecare.digital/customerservice` | no |
| `rcsorder` | body text | 404 | `wecare.digital/customerservice` | no |
| `rcsmenu_apex` | body text | 404 | `wecare.digital/customerservice` | no |
| `wd_card_front` | body text | 404 | `wecare.digital/customerservice` | no |
| `wd_card_front_wide` | body text | 404 | `wecare.digital/customerservice` | no |
| `wecare_order_update` | body text | 404 | `wecare.digital/track` | no |

**Every button and every media asset in `rcsmenu` returns 200.** Its 404 is the
plain-text line in the body ("Submit your request: …[retired public path b180810d]"), which is inert
until a customer long-presses it — so the live post-call card is degraded, not
broken. That is a narrower claim than §0 implied, and it is the measured one.

### 9.2 §1 is now stale in one row — `/r/getstarted` was repaired

Re-measured, and it contradicts the table in §1:

| URL | §1 said (2026-09-27) | Measured 2026-09-28 |
|---|---|---|
| `wecare.digital/r/getstarted` | 302 → **404** | **200**, 1 hop → `/contact/` |
| `wecare.digital/customerservice` | 404 | **404** (unchanged) |
| `wecare.digital/contact/` | not listed | **200**, terminal |
| `wecare.digital/workspace/forms/customerservice/` | 200 | 200 |
| `wecare.digital/get/o/stream/media/m/wd-brand-16x9.png` | 200 | 200 |

`faa956e8` made `/contact/` canonical and fixed the short link. So the URL question
§8 asked to be decided **has been decided by code**: the destination is `/contact/`.
Option B in §1 is therefore moot — `[retired public path b180810d]` was deliberately removed, not
pending restoration.

### 9.3 Re-filing ten templates is the wrong fix

All ten dead links are **one** root cause: `wecare.digital/customerservice` returns 404.
Zero of the app's **104** live Amplify custom rules mention `customerservice` or `track`.

One redirect rule, `[retired public path b180810d]` → `/contact/`, repairs **nine of the ten** with no
provider review, no new approvals, and no frozen-body problem. Re-filing cannot
compete with that:

* An approved body cannot be edited in place, so "fixing" nine templates means
  creating nine successors and reprovisioning whatever points at them.
* It would not repair SMS at all. The DLT-approved `ivr-default` body names
  `wecare.digital/customerservice` and is frozen character-for-character, so a redirect
  is the *only* thing that can fix the SMS path — exactly as §0 said.
* `wecare_order_update`'s `[retired public path 282d0fd5]` is a separate second rule, or a deliberate
  retirement — it is a text template nothing sends.

**The one template that genuinely warrants re-filing is `wd_card_clean`**, because
its 404 is a *button* rather than body text, and a dead button on the primary CTA is
not something a redirect should be papering over. It is also free to redo: nothing
sends it. Point `Get Started` at `https://wecare.digital/contact/` (terminal, 0 hops)
and recreate.

### 9.4 Not done here, and why

The `[retired public path b180810d]` redirect was **not** applied in this pass. Amplify `customRules`
is replaced as a whole array by `UpdateApp`, and another session is concurrently
editing exactly that surface — `scripts/provision_legacy_redirects.py` is modified in
the working tree and `docs/execution/snapshots/amplify-custom-rules-before-seo404.json`
had just been written. Writing the array from two sessions is last-writer-wins and
would silently drop their rules. Per `.kiro/steering/multi-session-parallel-agents.md`
this is sequenced, not raced.

Handover, precisely: that script's map does **not** currently contain `[retired public path b180810d]`
(its only related entry is `[retired public path 44011e36]` → `/workspace/contacts`), so the rule is
unowned. Add to whoever holds the Amplify rule array:

    [retired public path b180810d]   ->  /contact/    301
    [retired public path 282d0fd5]         ->  /contact/    301   (or retire wecare_order_update)

Then re-probe with the command in §9.1 and the table above should go fully green
without touching a single template.
