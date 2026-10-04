# RCS template proposal — no video, card artwork instead

Drafted 2026-09-27. **Nothing here has been created.** These are proposals for you
to edit; §6 has the exact commands when you are ready.

Goal: replace the video-carrying rich cards with something lighter — either pure
text, or a card using the WECARE.DIGITAL card artwork.

---

## 1. What is actually in S3

Measured, not assumed: dimensions decoded from the PNG headers, content types read
from S3, dominant colour sampled from the pixels.

| Key under `stream/media/m/` | Pixels | Ratio | Size | Verdict |
|---|---|---|---|---|
| `wecare-digital-rcs-h.png` | 2800 × 1200 | **7:3** | 89 KB | **Correct shape already.** Used by `rcsmenu` today |
| `wdf.png` | 1254 × 1254 | 1:1 | 1.33 MB | Card **front** — logo, tagline, phone, email, QR |
| `wdb.png` | 1254 × 1254 | 1:1 | 1.08 MB | Card **back** — "hello" + #EverydayBharat |
| `customerservice.png` | 3375 × 3375 | 1:1 | 578 KB | Square, very large |
| `wecare-digital-rcs-v` | 1091 × 1441 | 0.76:1 | 1.16 MB | Portrait, **and no file extension** |
| `wecare-digital-rcs` | 3375 × 3375 | 1:1 | 578 KB | **No file extension** |
| `wecare-digital.png` | 1080 × 1080 | 1:1 | 86 KB | Logo tile |
| `WECARE+SC.png` | — | — | — | **Does not exist** — referenced by `get_started`, dead |

Card artwork brand green sampled from the pixels: **`#01643F`**. Note this is *not*
the site's CSS `--color-primary: #1a3a2a` — the print artwork uses a brighter
green, so anything composited against it must use `#01643F` or the seam shows.

---

## 2. The constraint that decides everything

For a **vertical** rich card the media sits across the top and must be
*horizontal*. Sinch names three acceptable ratios — **2:1, 16:9 or 7:3** —
and Google gives 1440 × 720 as the optimal 2:1 resolution with a **2 MB
recommended maximum** for images. A vertical card with `SHORT` height wants
roughly 3:1 (about 1440 × 480). For a **horizontal** card the thumbnail is
nearer 4:3 (around 605 × 452). Guidance also warns that media alone is a poor
rich card — always pair it with a suggested reply or action.

Sources: [Sinch — sending rich files with RCS](https://support.sinch.com/hc/en-us/articles/53771584704019-Sending-rich-files-with-RCS),
[Google RCS overview](https://pepipost.readme.io/docs/google-rcs-overview),
[RCS rich card media and layout requirements](https://www.smsgatewaycenter.com/blog/kb/what-are-the-media-and-layout-requirements-for-rcs-rich-cards/),
[MessageFlow technical specifications](https://docs.messageflow.com/rcs/first-steps/technical-specifications),
[EnableX rich media reference](https://developer.enablex.io/messaging/rcs-rich-media.html).
*Content was rephrased for compliance with licensing restrictions.*

**So the card artwork cannot be dropped in as-is.** `wdf.png` and `wdb.png` are
1:1. In a vertical card a square gets centre-cropped to roughly 2:1 or 3:1, which
on the front would slice off the QR code and the contact block — the two things
that make it a business card. That is why option C letterboxes rather than crops.

---

## 3. Option A — text only, no media at all

The literal answer to "without video + image". Nothing to host, nothing to crop,
no size limit, renders identically on every handset.

```
name : wd_menu_text
type : text_message
```

```
Thanks for contacting WECARE.DIGITAL!

Submit your request: [retired public path 68ca05fc]
Or message / voice note us on WhatsApp: https://wecare.digital/r/wa

We'll review it and follow up if needed.
```

Trade-off: no branding, and no tappable button — an RCS text template carries no
suggestions, so the links are plain text the user must long-press.

---

## 4. Option B — rich card, image only, no video  ← recommended

Uses the image that is **already the right shape**: `wecare-digital-rcs-h.png`,
2800 × 1200 = exactly 7:3, 89 KB. No new asset, no upload, no crop, and it is
already proven in production inside `rcsmenu`.

```
name        : wd_menu_img
type        : rich_card
orientation : VERTICAL
media height: MEDIUM
media       : https://wecare.digital/get/o/stream/media/m/wecare-digital-rcs-h.png
title       : Thanks for contacting WECARE.DIGITAL!
description : Submit your request here: [retired public path 68ca05fc]
              or send us a message / voice note on WhatsApp:
              https://wecare.digital/r/wa.

              We'll review it and follow up if needed.
              WECARE.DIGITAL
suggestion  : "Get Started" → https://wecare.digital/r/getstarted
```

This is `rcsmenu` with the video swapped for its own thumbnail image, and the two
retired hosts replaced by the migrated ones. Lowest risk of the three.

---

## 5. Option C — rich card using the WECARE.DIGITAL card artwork

I letterboxed both faces to 7:3 on the sampled `#01643F`, so **nothing is
cropped** — the QR and contact block survive in full — and the pad is invisible
because the colour matches the artwork exactly.

Generated, not yet uploaded:

| Local file | Pixels | Ratio | Size |
|---|---|---|---|
| `.scratch/rcsimg/wdf-rcs-7x3.png` | 1440 × 617 | 7:3 | 498 KB |
| `.scratch/rcsimg/wdb-rcs-7x3.png` | 1440 × 617 | 7:3 | 408 KB |

Both are comfortably under the 2 MB guidance.

**C1 — card front** (`wdf`): full business card, QR included.

```
name        : wd_card_front
type        : rich_card
orientation : VERTICAL
media height: TALL          ← TALL, so the card is as large as possible
media       : https://wecare.digital/get/o/stream/media/m/wd-card-front-7x3.png
title       : WECARE.DIGITAL
description : Building digital railroads for Everyday Bharat.

              Submit a request: [retired public path 68ca05fc]
              WhatsApp us: https://wecare.digital/r/wa
suggestion  : "Get Started" → https://wecare.digital/r/getstarted
```

> **QR caveat.** At 1440 px wide the QR is about 190 px. Rendered in a TALL
> vertical card it lands near 60–70 px on a typical handset, which is marginal to
> scan. The card already prints the URL and phone number as text, so treat the QR
> as decoration here, not as the call to action. If scanning matters, use the
> horizontal-thumbnail layout instead and accept a smaller overall card, or crop
> the QR out and let the button do the work.

**C2 — card back** (`wdb`): the "hello" / #EverydayBharat face. Decorative, so
nothing is lost at any crop or size, and it is the stronger *greeting* image.
My pick if this is the post-call "thanks for calling" card.

```
name        : wd_card_hello
type        : rich_card
orientation : VERTICAL
media height: MEDIUM
media       : https://wecare.digital/get/o/stream/media/m/wd-card-hello-7x3.png
title       : Thanks for contacting WECARE.DIGITAL!
description : Submit your request here: [retired public path 68ca05fc]
              or send us a message / voice note on WhatsApp:
              https://wecare.digital/r/wa.

              We'll review it and follow up if needed.
suggestion  : "Get Started" → https://wecare.digital/r/getstarted
```

Option C needs the asset uploaded first:

```bash
aws s3 cp .scratch/rcsimg/wdf-rcs-7x3.png \
  s3://wecare-digital-get/o/stream/media/m/wd-card-front-7x3.png \
  --content-type image/png --cache-control 'public, max-age=31536000'

aws s3 cp .scratch/rcsimg/wdb-rcs-7x3.png \
  s3://wecare-digital-get/o/stream/media/m/wd-card-hello-7x3.png \
  --content-type image/png --cache-control 'public, max-age=31536000'
```

Upload to **`wecare-digital-get/o/`**, not `app.wecare.digital`. New assets should
not add to the 6 approved templates already pinning the host we are trying to
retire.

---

## 6. Creating them

`create_template` takes `type` and, for `rich_card`, the card JSON as a **string**
in the `text` field. Creation on this provider returned `status: approved`
immediately for `rcsmenu_apex`, so there is no approval wait.

Text template:

```bash
aws lambda invoke --function-name wecare-rcs-send --cli-binary-format raw-in-base64-out \
  --payload '{"body":"{\"action\":\"create_template\",\"name\":\"wd_menu_text\",\"type\":\"text_message\",\"text\":\"Thanks for contacting WECARE.DIGITAL!\\n\\nSubmit your request: https://wecare.digital/customerservice\\nOr message / voice note us on WhatsApp: https://wecare.digital/r/wa\\n\\nWe will review it and follow up if needed.\"}"}' \
  /dev/stdout
```

Rich card — build the payload in Python rather than escaping JSON inside JSON by
hand:

```python
import boto3, json
card = {"richCard": {"standaloneCard": {
    "cardOrientation": "VERTICAL",
    "cardContent": {
        "title": "Thanks for contacting WECARE.DIGITAL!",
        "description": ("Submit your request here: [retired public path 68ca05fc] "
                        "or send us a message / voice note on WhatsApp: "
                        "https://wecare.digital/r/wa.\n\nWe'll review it and follow "
                        "up if needed."),
        "media": {"height": "MEDIUM", "contentInfo": {
            "fileUrl": "https://wecare.digital/get/o/stream/media/m/wd-card-hello-7x3.png",
            "forceRefresh": False}},
        "suggestions": [{"action": {
            "text": "Get Started", "postbackData": "wd_card_hello",
            "openUrlAction": {"url": "https://wecare.digital/r/getstarted",
                              "application": "BROWSER"}}}],
    }}}}

boto3.client("lambda", region_name="us-east-1").invoke(
    FunctionName="wecare-rcs-send",
    Payload=json.dumps({"requestContext": {"http": {"method": "POST"}},
                        "body": json.dumps({"action": "create_template",
                                            "name": "wd_card_hello",
                                            "type": "rich_card",
                                            "text": json.dumps(card)})}).encode())
```

Note `thumbnailUrl` is **omitted** on purpose in all three options — it is only
needed alongside a video. With an image as the media, a thumbnail is redundant,
and a wrong one is how `get_started` ended up pointing at a file that does not
exist.

Then test to the owner-nominated QA number before pointing anything at it:

```bash
aws lambda invoke --function-name wecare-rcs-send --cli-binary-format raw-in-base64-out \
  --payload '{"body":"{\"action\":\"send\",\"phoneNumber\":\"+918100640044\",\"template\":\"wd_card_hello\",\"language\":\"en\"}"}' \
  /dev/stdout
```

---

## 7. Switching the post-call card over

Creating a template changes nothing on its own. Two places name the template, and
both default to `rcsmenu`:

| Where | How to change |
|---|---|
| `lambda_utils/sinch_rcs.send_rcs_ivr_notification` | hardcoded `'rcsmenu'` — a code change plus deploy and alias move |
| `notifications/policy.RCS_INDIA_TEMPLATE` | env `NOTIF_RCS_TEMPLATE_NAME`, no deploy needed |

Leave `rcsmenu` in place until the replacement has been sent to a handset and
looked right — it is the template every post-call RCS currently uses.

---

## 8. Recommendation

1. **Option B** if you want this done with no new assets and no risk. It is
   `rcsmenu` minus the video, on the migrated URLs, using an image that is already
   exactly 7:3.
2. **Option C2** (`hello` face) if you want the card artwork — it is the better
   greeting and loses nothing to cropping.
3. **Option C1** (front face) only where the recipient will actually read details;
   the QR is too small to rely on at card size.
4. **Option A** as a fallback for handsets or routes where rich cards are not
   worth the weight.

---

## 9. Text and button colour — what is actually settable

Short version: **an RCS template carries no colour field.** Checked both ways —
the only colour-adjacent string in the entire RCS code path
(`rcs-send/handler.py`, `lambda_utils/sinch_rcs.py`) is the word `brand` inside a
redaction key list. There is no `color`, no `theme`, no `style`.

### 9.1 Who controls what

| Element | Controlled by | Light mode | Dark mode |
|---|---|---|---|
| Card background | handset Messages theme | near-white | near-black `#1f1f1f` |
| Title | handset theme | `#1f1f1f` | `#e8eaed` |
| Description | handset theme | `#5f6368` | `#9aa0a6` |
| Inline links in the description | handset theme | `#1a73e8` | `#8ab4f8` |
| **Suggestion / action button** | **your RBM agent colour** | agent colour | auto-lightened |
| Media image | your asset | as uploaded | as uploaded |

So the only colour you own is the **button tint**, and it is set **once on the
agent**, not per template. Google lists colour among the agent fields edited in
the Business Communications console — alongside display name, description, images
and contact details — which for us means Sinch/ACL sets it during agent
verification. Vonage documents the binding constraint: the brand colour must reach
at least **4.5:1 contrast against white** (WCAG 2.0) so it stays legible.

Sources: [Google — edit agent information](https://developers.google.com/business-communications/rcs-business-messaging/guides/build/agents/edit-agent-information),
[Vonage — branding your RCS agent](https://api.support.vonage.com/hc/en-us/articles/20710366656668-Branding-Your-RCS-Agent-Guidelines-for-Logo-Banner-and-Color-Theme).
*Content was rephrased for compliance with licensing restrictions.*

### 9.2 Measured contrast for our candidate colours

Computed with the WCAG 2.0 relative-luminance formula, not eyeballed:

| Colour | Source | vs white | vs `#1f1f1f` | RBM rule |
|---|---|---:|---:|---|
| **`#01643F`** | sampled from the card artwork | **7.25:1** | 2.27:1 | **PASS — recommended** |
| `#1a3a2a` | site CSS `--color-primary` | 12.48:1 | 1.32:1 | PASS, but darker than the art |
| `#0f2a1d` | CSS `--color-primary-hover` | 15.34:1 | 1.07:1 | PASS, very dark |
| `#d1f470` | UI lime accent | 1.24:1 | 13.25:1 | **FAIL — illegible on white** |
| `#25D366` | WhatsApp green | 1.98:1 | 8.31:1 | **FAIL**, and off-brand here |

`#01643F` is the right choice: it clears the rule with margin at 7.25:1 **and** it
is the exact green in `wdf.png` / `wdb.png`, so the button and the card image
match instead of clashing by a few degrees of hue.

Do **not** propose `#d1f470`. It is the workspace UI accent and reads well on
dark chrome, but at 1.24:1 on white it would be effectively invisible in a light
mode card — and light mode is the default.

### 9.3 What I could not verify

* **The agent's current colour.** The ACL Conversation API `/apps` probe returns
  rate limits, retention, callback and fallback settings — no branding block. The
  RBM agent's colour lives on the Google side, held by the partner. Ask Sinch/ACL
  what the agent is set to, or read it in the Business Communications console.
* **Exact dark-mode rendering.** `#01643F` is only 2.27:1 against `#1f1f1f`, so
  Messages will lighten the tint rather than render it unreadably. I have not
  confirmed the algorithm or the resulting value — check it on a real handset.
  The mock in this section is a mock, not a measurement.

### 9.4 If you want a different look

Because the chrome is not ours, the ways to change the card's feel are:

1. **The media image** — the one part fully under our control, and the reason
   option C matters. The 7:3 banner is the card's visual identity.
2. **The agent colour**, once, via the provider. Changing it moves every button in
   every template at the same time.
3. **The button label.** `"GET STARTED"` is our string; the handset uppercases and
   tints it. Shorter labels survive narrow screens better.

---

## 10. BUILT 2026-09-27 — card front, two variants

Option C1 chosen. Two variants were created rather than one, because the right
media height for a 1:1 source is not something a probe can settle — only a handset
can.

### 10.1 Why two

The 7:3 letterbox is the *safe* ratio, but it costs QR legibility: padding a
square to 7:3 leaves the card occupying only **43% of the width** (617 of 1440 px),
so on a vertical card the artwork renders small and the QR shrinks with it.

A `TALL` vertical card is roughly 280dp wide by 264dp high — about **1.06:1** —
which is very nearly square. Padding the 1254 × 1254 source on the **width only**
to 1.06:1 crops nothing and lets the artwork fill the full card width, making the
QR roughly 2.3× larger than in the 7:3 version.

The trade: 1.06:1 is **not** one of the three ratios Sinch documents (2:1, 16:9,
7:3). The provider accepted it, but acceptance is not rendering. Hence both.

| Template | Media | Pixels | Ratio | Size | Height |
|---|---|---|---|---|---|
| `wd_card_front` | `wd-card-front-tall.png` | 1080 × 1017 | 1.062 | 1.05 MB | `TALL` |
| `wd_card_front_wide` | `wd-card-front-wide.png` | 1440 × 617 | 2.334 | 0.47 MB | `MEDIUM` |

Both under the 2 MB guidance. The `TALL` source was reduced from 1440 px wide,
where it reached 1.78 MB — uncomfortably close to the ceiling for a marginal gain,
since 1080 px is still about 3× density for a 280dp card.

### 10.2 What both contain

```
orientation : VERTICAL
title       : WECARE.DIGITAL
description : Building digital railroads for Everyday Bharat.

              Submit your request: [retired public path 68ca05fc]
              Message / voice note us on WhatsApp: https://wecare.digital/r/wa
suggestion  : "Get Started" -> https://wecare.digital/r/getstarted
```

No `thumbnailUrl` — there is no video, so it would be redundant. No colour fields,
because none exist (§9): the button renders in the agent colour, everything else
follows the handset theme.

### 10.3 Verification

Assets uploaded to `wecare-digital-get/o/`, **not** `app.wecare.digital`, so these
add nothing to the host being retired:

```
wd-card-front-tall.png   200  image/png  1099743 bytes
wd-card-front-wide.png   200  image/png   497916 bytes
```

Templates created, both `status: approved` immediately. Test-sent to the
owner-nominated QA number `+918100640044`:

| Template | messageId |
|---|---|
| `wd_card_front` | `01M3GD25KJ3S59PDNN28SS69NP` |
| `wd_card_front_wide` | `01M3GD28QXFKH13MAQ80JZA5BB` |

Template count 12 → 14. Both new templates carry **zero** references to
`app.wecare.digital` or `r.wecare.digital`.

### 10.4 Still to decide, on the handset

Compare the two messages and pick one. Specifically:

1. Does the `TALL` near-square render full-width, or does the provider letterbox
   it back down? That is the whole reason both exist.
2. Is the QR scannable in the `TALL` variant? If it is not at full card width, it
   never will be, and the front face is the wrong choice — use the `hello` back
   (§5 C2) and let the button carry the action.
3. Does the button pick up `#01643F`, or a different agent colour? That answers
   the open question in §9.3 about what the agent is actually set to.

Nothing points at these yet. `rcsmenu` remains the template every post-call RCS
sends, unchanged, until you have chosen — see §7 for the two places that name it.

---

## 11. DRAFT — no links in the body, actions on buttons

**Not built.** Draft for review.

The change: strip every URL out of `description` and move each action onto a
suggestion button. Two reasons it is the right shape, not just tidier:

1. **A URL in the description is inert.** It is plain text — long-press, then pick
   "open" from a menu. A suggestion is one tap.
2. **The body currently repeats the card image.** The artwork already carries the
   phone number, the site, the email and the QR. Printing the same URLs underneath
   spends three lines saying it again, and pushes the one real button further down.

### 11.1 The limit that shapes the draft

A rich card accepts **at most 4 suggestions**, actions and replies combined, and a
label runs to roughly 25 characters. Three button types are available: suggested
**reply**, **dialer**, and **open URL**.

Sources: [Google — rich cards](https://developers.google.com/business-communications/rcs-business-messaging/guides/learn/rich-cards),
[AWS — configuring RCS suggestions](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-suggestions.html),
[CM.com — rich card messages](https://developers.cm.com/messaging/docs/rcs-rich-card-messages),
[Route Mobile — RCS message types](https://route-mobile-group.readme.io/route-mobile-project/docs/rcs-message-types).
*Content was rephrased for compliance with licensing restrictions.*

### 11.2 Draft copy — `wd_card_clean`

```
title       : WECARE.DIGITAL

description : Thanks for contacting us.
              Building digital railroads for Everyday Bharat.

              Choose an option below and we'll follow up.

media       : wd-card-front-tall.png   (VERTICAL, TALL)

buttons     : 1. GET STARTED    url     wecare.digital/r/getstarted
              2. WHATSAPP US    url     wa.me/message/APDM5HUWH26SG1
              3. CALL US        dialer  +919330994400
                                        (4th slot left free)
```

Zero URLs in the body. Three taps available, one slot spare.

### 11.2a The WhatsApp button goes direct, matching the widget

Revised 2026-09-27: button 2 was `wecare.digital/r/wa`; it is now the **direct**
link, taken from what the site widget actually uses rather than invented.

`SupportWidget.tsx:747` links to `https://wa.me/message/APDM5HUWH26SG1`, and its
comment records that the href was read out of the retired `wecare-wa-widget.js`
"rather than guessed, so retiring that script did not move where people land."
`/r/wa` 302s to exactly the same URL, so this is a change of hop count, not of
destination.

Verified the destination rather than assuming it:

```
https://wa.me/message/APDM5HUWH26SG1
  -> 302 https://api.whatsapp.com/message/APDM5HUWH26SG1?autoload=1&app_absent=0
  -> phone=919330994400        og:description "Official Business Account"
```

`919330994400` is **WABA1 — the same number printed on the card image**, so the
button and the artwork agree. Worth stating because a WhatsApp button landing on a
different number than the card shows would be a quiet inconsistency.

Two things this costs, both worth knowing before it ships:

* **Click analytics.** The shortener counts clicks — 742 recorded on `/r/*` — and a
  direct link is invisible to it. If WhatsApp taps from RCS need measuring, the
  short link is the only thing here that measures them.
* **Retargetability.** A template is *approved* by the provider, so the URL inside
  it is effectively frozen; changing it later means a new template. `/r/wa` could be
  repointed in seconds without touching RCS at all.

Neither is a blocker — just the trade being made. `wa.me/message/…` is itself one
internal redirect (`wa.me` → `api.whatsapp.com`), which is Meta's own hop and not
avoidable.

**Observation, not a change:** the code `APDM5HUWH26SG1` is the one labelled
**`subscribe`** in `customerservice.tsx`'s `MESSAGE_LINKS`, while `submit_request` is a
different code, `J3ZJ4W52TPJEN1`. The widget has pointed at the `subscribe` deep
link since before this work, deliberately preserved from the old script. Flagging it
in case the RCS button ought to open `submit_request` instead — that is a product
call, so nothing was changed.

`GET STARTED` is left as `wecare.digital/r/getstarted` (which 302s to
`wecare.digital/customerservice`). Say if you want that one direct too; the same
analytics trade applies.

### 11.3 Copy alternatives

Pick one — the only constraint is that it contains no URL.

**A — shortest.**
```
Thanks for contacting us. Choose an option below and we'll follow up.
```

**B — keeps the tagline (drafted above).**
```
Thanks for contacting us.
Building digital railroads for Everyday Bharat.

Choose an option below and we'll follow up.
```

**C — sets an expectation.**
```
Thanks for contacting WECARE.DIGITAL.

Submit a request, message us on WhatsApp, or call — whichever suits you.
We review everything and follow up if needed.
```

C reads best but names the actions in prose *and* on the buttons, which is the
same duplication in a milder form. B is the recommendation.

### 11.4 Button label alternatives

Labels are uppercased by the handset and truncate on narrow screens, so short wins.

| Slot | Recommended | Alternatives |
|---|---|---|
| 1 | `Get Started` | `Submit request`, `New request` |
| 2 | `WhatsApp us` | `WhatsApp`, `Chat on WhatsApp` (17 chars, still fits) |
| 3 | `Call us` | `Call`, `Call support` |
| 4 | *(unused)* | `Visit website`, or a suggested **reply** such as `Talk to a human` |

Leaving slot 4 empty is deliberate. Four buttons on a small screen crowds the card,
and a spare slot is somewhere to put a reply chip later without a redesign.

### 11.5 The one unknown

`CALL US` needs a **dialer** suggestion. Every template on this account today uses
only `openUrlAction`, so the dialer type is **unproven with this provider**.
`_create_template` passes rich-card JSON through untouched when a `richCard` key is
present, so the provider decides — it will either accept it or return a 4xx.

If it is rejected, the fallback is a **2-button card**. Nothing is lost: the phone
number is printed on the card image and encoded in the QR.

Proposed shape:

```json
{"action": {"text": "Call us", "postbackData": "wd_call",
            "dialAction": {"phoneNumber": "+919330994400"}}}
```

### 11.6 What this does not touch

* `rcsmenu` stays exactly as it is — still the template every post-call RCS sends.
* No media changes. It reuses `wd-card-front-tall.png`, already uploaded and
  verified 200.
* Nothing is repointed. Switching the post-call card over is the separate step in
  §7.
* The SMS fallback is unaffected: if RCS is not delivered the recipient gets the
  DLT-approved `ivr-default` SMS, which carries its own links by design.

### 11.7 On approval

Say the word and I will create `wd_card_clean` with copy B and the three buttons,
report whether the dialer type was accepted, and send it to the QA number next to
the two existing variants so all three can be compared on one handset.
