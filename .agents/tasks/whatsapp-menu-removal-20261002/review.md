# Scorched-earth removal of the remaining WhatsApp menu and interactive surface

PHASE 2 / OPTION B deletes the IVR button menu, the inbound IVR/list-reply routers, the
follow-up button chooser, the AI handler's list tool and `menuResponses` block, the two
generic interactive senders in `whatsapp-business-api`, the four menu-shaped branches of
`outbound-whatsapp._handle_interactive_send`, the `wd_menu` template sends in both voice-in
CDR paths, and the `wd_menu` default in the notifications policy. 1,215 lines deleted across
ten source files; the two live `welcome_message` DynamoDB rows were rewritten to drop "Tap
*Menu*". Every path that could previously answer a tap now answers with the phase-1
plain-text placeholder, and every withdrawn route answers with an explicit error rather than
a 404 or a crash.

Watch for: one acceptance criterion was deliberately not met — `_handle_interactive_send`
was kept and narrowed to five non-menu types rather than deleted (confirmed), because
deleting it takes out the Razorpay post-payment flow send and India checkout address
collection; the owner should ratify that carve-out. Three staff-facing frontend surfaces
(the Interactive Lists page, its nav entry, the `InteractiveMessageComposer` list/button
modes) still build menus and now receive 410/400 from the backend (confirmed). `WA_TEMPLATE_NAME`
is now empty, so the WhatsApp notification channel is permanently ineligible until a
replacement template is approved (confirmed, and the pipeline flag is off today).

**Verdict**: APPROVED

## High-level view

`_get_ivr_menu(...)['greeting']` was the only non-menu consumer of the deleted menu dicts,
and it became the module constant `IVR_GREETING_TEXT`, so the Polly path still has words to
speak. Two residues: the SystemConfig override row `ivr_menu_{phone_number_id}` is now read
by nobody, and `_generate_ivr_tts_audio` keeps a `phone_number_id` parameter it no longer
uses.

Inbound `button_reply` and `list_reply` now log a correlation event and send
`_send_menu_placeholder` inline, so a tap on a stale button or row gets text rather than
silence or a `NameError`; `nfm_reply` (India address submissions, post-payment flow
completions) still routes. One behaviour change: `button_reply` previously fell through for
unrecognised ids and now always returns early. Nothing in the repo still produces a
reply-button id, so there is no live producer to strand.

The one deviation from the brief is `_handle_interactive_send`. The brief asks for deletion
and, in the same breath, for checkout and payment paths to stay intact; those cannot both
happen, because that function carries `flow` (Razorpay webhook plus three inbound call
sites), `address_message` (India checkout), `cta_url` (eight inbound call sites),
`location_request` and `catalog_message`. The plan resolved this as D1 before coding: keep
the function, delete `list`, `button`, `product` and `product_list`, and have the `else` arm
return a JSON error naming the removal. The riskiest mechanical step — promoting the first
surviving branch from `elif` to `if` — was done correctly and exercised by calling the
function, not inferred.

`whatsapp-business-api` returns 410 on both `/messages/send/interactive` and
`/interactive-list`, deliberately distinct from the 404 an unknown send path still returns.
Dashboard callers of the deleted types were left in place by plan decision, so the
Interactive Lists page and the composer's list/button modes now surface backend errors
instead of sending.

`WA_TEMPLATE_NAME` dropped from `wd_menu` to empty, guarded twice — `decide_whatsapp` refuses
with `INELIGIBLE_TEMPLATE_UNCONFIGURED` ahead of the verified-sender check, and
`worker._send_whatsapp` refuses with `PERMANENT`/`TEMPLATE_UNCONFIGURED` before invoking the
sender. Both guards are needed, because `outbound-whatsapp` gates on
`if is_template and template_name:` and would otherwise fall through to a content send with
empty content.

The two `welcome_message` rows were a real customer-facing data change, not the dead config
the original request assumed: both are read at runtime by
`inbound-whatsapp-handler._load_welcome_text` and `ai-generate-response._get_welcome_config`.
The write was conditional, round-tripped unknown fields, and re-read to confirm no "menu"
wording survives. No `get-secret-value`, no credential on a command line.

Test coverage was inverted rather than dropped: nine menu tests across three files became
assertions that the symbols are absent, that the inline dispatch still sends the placeholder
for both reply types, and that both correlation log events survive. 13 failed / 6861 passed
against a 13 failed / 6854 passed baseline — the same 13 names, all other sessions' work.

<details>
<summary>Issues (6)</summary>

1. **`_handle_interactive_send` kept, against an explicit acceptance criterion** — narrowed
   to `location_request`, `cta_url`, `flow`, `address_message`, `catalog_message` per plan D1
   instead of deleted, because deletion breaks the Razorpay post-payment flow send, the
   submit/track-request flows and India checkout address collection. Needs owner
   ratification, not a code change; deleting it now would be a regression in a
   steering-protected path.
2. **Staff menu-building UI still shipped** — `src/pages/workspace/engage/whatsapp/interactive-lists.tsx`
   plus its nav entry at `src/config/navigation.ts:212` now hit a 410, and
   `InteractiveMessageComposer` still defaults to `'button'` and offers `'list'`, both of
   which get a 400. Declared as a known consequence in the plan, but it is residual WhatsApp
   menu surface under the "any menu anywhere" instruction. Follow-up: remove the page, the
   nav entry and the two composer modes.
3. **`src/api/client.ts` still advertises removed types** — the `SendInteractiveRequest`
   union keeps `'list' | 'button' | 'product' | 'product_list'` and `sendWhatsAppProducts`
   still posts `product`/`product_list`, so the types compile while the calls 400. Trim the
   union to the five surviving types.
4. **WhatsApp notification channel is now permanently ineligible** — with `WA_TEMPLATE_NAME`
   empty, every WhatsApp delivery records `TEMPLATE_UNCONFIGURED`. Harmless today because
   `PSTN_CONNECTED_NOTIFICATIONS_ENABLED` is absent, but turning that flag on needs an
   approved `wd_call_followup_v1` first.
5. **Three customer-service actions lost their only entry point** — `toggle_audio`,
   `toggle_notifications` and `human_handoff` were reachable only from the deleted menu rows
   and have no typed keyword. The coder measured this and recorded it; restoring any of them
   is new work, not a revert.
6. **Minor dead surface in whatsapp-calling** — `_generate_ivr_tts_audio` keeps an unused
   `phone_number_id` parameter, and the `ivr_menu_{phone_number_id}` SystemConfig override
   row (if any exist) is now read by nobody. Cosmetic; no runtime effect.

</details>

<details>
<summary>Details</summary>

### Per-criterion findings

| Criterion | Result | Evidence |
|---|---|---|
| IVR button menu gone from `whatsapp-calling`, lifecycle intact | **PASS** | `_SHARED_IVR_MENU`, `IVR_MENUS`, `IVR_DEFAULT_MENU`, `IVR_RESPONSES`, `_get_ivr_menu` all deleted; `IVR_GREETING_TEXT` constant feeds the Polly path; `_auto_pickup_and_play` keeps pre_accept → accept → audio → terminate; `TestIVRAutoPickup` untouched and passing |
| inbound routers gone, replies route to the placeholder | **PASS** | `_handle_ivr_response`, `_handle_list_reply`, `_send_reply_buttons`, `_send_followup_buttons` deleted with all five `_send_followup_buttons` call sites; both reply branches log and call `_send_menu_placeholder`; `nfm_reply` untouched |
| voice-in c2c + obd `wd_menu` sends and CDR writes gone | **PASS** | Template block, `urllib` imports, `secrets_client`, `wa_message_id`, the four `whatsappMessage*` CDR attributes and the `urllib.error.HTTPError` handler all removed symmetrically in both files; SMS and RCS blocks and their CDR writes unchanged; no residual `wa_message_id` reference |
| ai-generate-response menu surface gone | **PASS** | `send_whatsapp_list` tool spec, its `_execute_internal_tool` branch and `_tool_send_whatsapp_list` deleted; `menuResponses` block, `show_main_menu` / `show_sub_menu` / `show_language_picker` actions and the `showMainMenu` emits gone; `_detect_language` (line 4209) untouched; `_detect_language_selection` keeps its four typed patterns |
| governance: only `send_whatsapp_list` removed | **PASS** | One three-line `CATALOG` entry removed; `send_whatsapp_flow`, `send_whatsapp_buttons`, `send_whatsapp_pay` and the rest kept |
| whatsapp-business-api senders deleted, routes error clearly | **PASS** | `_send_interactive_msg` and `_send_interactive_list` deleted; both routes return `_resp(410, …)`; unknown send path still 404; `_send_product_msg`, `_send_flow_msg`, text/template/media/contacts/location kept |
| outbound-whatsapp `_handle_interactive_send` deleted | **DEVIATION** | Kept and narrowed per plan D1 — see issue 1. `list`, `button`, `product`, `product_list` deleted; `else` arm returns `_error_response(400, 'interactive messaging removed', …)`; `elif` → `if` promotion correct |
| `WA_TEMPLATE_NAME` no longer `wd_menu`, send paths guarded | **PASS** | Default `""`; `decide_whatsapp` refuses ahead of the verified check; `worker._send_whatsapp` returns `PERMANENT`/`TEMPLATE_UNCONFIGURED`; both orderings pinned by new tests |
| `welcome_message` rows: before and after reported | **PASS** | Both rows, before/after `textMessage` and `sendMenu` recorded; `scripts/update_welcome_message_config.py` is dry-run by default, conditional, round-trips unknown fields, re-reads and refuses on residual "menu"; no Secrets Manager read |
| Grep sweep justified | **PASS** | Every remaining hit of the 20 forbidden symbols declared as a comment, a deletion-guard test assertion, or the D1 carve-out; one false positive in `test_outbound_whatsapp.py` renamed to `some_template` |
| No deploy, no commit, no push | **PASS** | `HEAD == origin/stack == fa9516b9`, index empty, 24 modified files unstaged; no `update-function-code`, version publish or alias move in the record |
| Test delta | **PASS** | 13 failed / 6861 passed, same 13 pre-existing names; nine menu tests replaced by their inverse across three files; `PerksPage.test.tsx` 9 passed; typecheck clean |

### The D1 carve-out, and why approving it beats enforcing the criterion

The brief asks for `_handle_interactive_send` to be deleted and, in the same list, for
"text/media/template/checkout/order_details paths intact". The function's nine types make
those mutually exclusive:

```
list          deleted   no producer left
button        deleted   producer (_send_followup_buttons) deleted in the same change
product       deleted   dashboard only
product_list  deleted   dashboard only
location_request  KEPT  src/pages/workspace/engage/whatsapp/inbox.tsx:770
cta_url           KEPT  inbound._send_cta_button, 8 call sites
flow              KEPT  payments/razorpay-webhook:1552, inbound 4613/4679/4814
address_message   KEPT  inbound:5205 — India Address Message, checkout
catalog_message   KEPT  src/pages/workspace/engage/commerce/index.tsx:65
```

Enforcing the literal criterion would remove the post-payment flow send from the Razorpay
webhook and India delivery-address collection from checkout — both in paths the project's
own steering protects. The plan recorded the contradiction and resolved it before any code
was written, so this is a reasoned deviation rather than an incomplete job. It needs the
owner to say "yes, five non-menu interactive types stay", and nothing more.

### Residual producers of deleted types

`_tool_send_whatsapp_buttons` survives in the AI handler and still builds a `type: 'button'`
interactive payload. It invokes `wecare-outbound-whatsapp` with
`{'contactId', 'interactive'}` and no `isInteractive` flag, so it never reached
`_handle_interactive_send` even before this change — pre-existing and out of scope, but it is
a reply-button chooser still advertised to the model, which the "any menu anywhere"
instruction arguably covers.

`flowAction: 'showOptions'` / `'showRating'` emits and `DEFAULT_BOT_FLOW['options']` /
`['rating']` remain list-shaped config in the AI handler. Nothing renders them:
`inbound._process_ai_automation` is a stub whose first statement is `return None` — verified
by reading it. Declared by the coder rather than silently left.

### Verification evidence, assessed

The error returns were exercised by calling the functions rather than inferred from source —
`list`, `button`, `product`, `product_list` and a nonsense type all returned 400, while
`cta_url` and `address_message` reached `_send_message` with the right payload type. The
import smokes assert both directions (deleted names absent, kept names present), so a module
cannot pass vacuously.

Two corrections to the brief's own inputs are load-bearing. The baseline is 13 pre-existing
failures, not the ~9 the brief assumed. And the brief's claim that the `welcome_message` row
is "read by nobody" is wrong — there are two rows and both are read at runtime, which is what
makes the copy rewrite customer-facing rather than housekeeping.

I did not re-run the suites. Spot-checks run: `_error_response`'s signature (line 3999,
accepts three arguments, so the new `else` arm is valid), the surviving branch order in
`_handle_interactive_send`, `_process_ai_automation`'s stub body, the absence of residual
`secrets_client` / `urllib` / `wa_message_id` references in both voice-in handlers, and the
frontend callers of the removed types. All matched the record.

</details>

<details>
<summary>Files changed (24)</summary>

| File | Change |
|---|---|
| `amplify/functions/messaging/whatsapp-calling/handler.py` | IVR menu dicts and `_get_ivr_menu` deleted; `IVR_GREETING_TEXT` constant added |
| `amplify/functions/messaging/inbound-whatsapp-handler/handler.py` | IVR/list routers and button chooser deleted; both reply branches answer inline with the placeholder |
| `amplify/functions/messaging/outbound-whatsapp/handler.py` | four menu-shaped interactive branches deleted; `else` arm names the removal |
| `amplify/functions/messaging/whatsapp-business-api/handler.py` | both generic interactive senders deleted; both routes answer 410 |
| `amplify/functions/messaging/voice-in/c2c/handler.py`, `.../obd/handler.py` | `wd_menu` template send, its CDR writes and now-unused imports removed |
| `amplify/functions/ai/ai-generate-response/handler.py` | list tool, `menuResponses`, menu flow actions and picker branches deleted |
| `amplify/functions/shared/lambda_utils/agent/governance.py` | `send_whatsapp_list` catalog entry removed |
| `amplify/functions/shared/lambda_utils/notifications/policy.py` | `WA_TEMPLATE_NAME` default emptied; unconfigured-template refusal added |
| `amplify/functions/shared/lambda_utils/notifications/worker.py` | refuses to invoke the sender with no template name |
| `scripts/update_welcome_message_config.py` | new; rewrites the two live welcome rows, dry run by default |
| `src/components/dashboard/tabs/InternalChatTab.tsx`, `src/pages/workspace/settings/internal-agent.tsx` | `send_whatsapp_list` row removed |
| `src/components/dashboard/tabs/SystemTab.tsx`, `src/pages/workspace/engage/whatsapp/calling.tsx` | stale `wd_menu` copy corrected |
| `tests/` (9 files), `src/test/PerksPage.test.tsx` | menu assertions inverted into deletion guards; notification tests configure a template name |

Full diff: `git diff` at `fa9516b9` (nothing staged, nothing committed).

</details>
