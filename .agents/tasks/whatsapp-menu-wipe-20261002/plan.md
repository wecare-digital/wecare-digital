# Implementation Plan — delete ALL WhatsApp menus, keep the Lambdas alive

Task: remove every WhatsApp menu definition and every menu routing path from
`wecare-store`, leaving the two Lambda handlers importable and non-crashing, and
replacing each former menu send with one plain-text catch-all. No deploy, no alias
move, no Lambda deletion.

## State of the repo when this plan was written

Measured, not assumed. All line numbers below are against **HEAD = `ed1f3911`**
(`inbound-whatsapp-handler/handler.py` is 8388 lines) and were re-derived with an
AST walk after that commit landed. Re-derive before editing — see the concurrency
warning.

### A concurrent session already shipped a partial, different removal

While this exploration was running, commit `ed1f3911` ("Remove the WhatsApp
interactive menu (empty DEFAULT_ONE_MENU sections)") landed on `stack` and was
pushed. It took a narrower approach than this task asks for:

- `DEFAULT_ONE_MENU['sections']` is now `[]`; the envelope (`header`, `body`,
  `footer`, `buttonText`) was kept "so re-enabling is just putting rows back".
- `MENU_TO_KEYWORD` was left completely untouched.
- `tests/test_one_menu.py` was rewritten: the `TestTheOneMenuFitsMeta` class became
  `TestTheMenuIsRemoved`, pinning `sections == []`.
- Everything else — the retired menus, the submenu branches, the language picker,
  all `wd_menu` sends — was left in place.

Two consequences that shape this plan:

1. **A greeting now produces silence.** `_send_interactive_list` short-circuits on
   `not list_config.get('sections')` (handler.py:5009), so typing `hi` / `menu` /
   tapping a QR prefill sends *nothing at all*. The task explicitly forbids that
   outcome ("do NOT leave customers hitting silence"). The catch-all text in this
   plan is what fixes it.
2. **`tests/test_one_menu.py` is a moving target.** It passed at `ed1f3911`
   (109 tests green across `test_one_menu.py`, `test_own_prefill_triggers_menu.py`,
   `test_calling.py`). This plan deletes it; do not try to reconcile with the
   version in `ed1f3911`.

### Concurrency rules that apply to this task

`inbound-whatsapp-handler/handler.py` was committed by another session minutes ago,
so treat the index as potentially dirty with work that is not ours.
Per `.kiro/steering/multi-session-parallel-agents.md` rule 3b, every commit here
must be:

```
git add <any new files> && git commit --only <explicit paths> -F <message-file>
```

`--only` is not optional on this task. Run `git status --short` as its **own**
command (not chained) before staging, and leave any modified file that is not in
the owned-path list alone.

### Verified caller relationships

- **`_send_interactive_list` (handler.py:5004-5050) has NO non-menu caller.** All
  12 call sites build a list from a menu getter:
  - 1437 `followup_explore` button → `_get_welcome_config()`
  - 1632 `request_welcome` → `_get_welcome_config()`
  - 1673 `BUTTON_MENU_TRIGGERS` → `_get_welcome_config()`
  - 1941 `HI_KEYWORDS` → `_get_welcome_config()`
  - 1992 `CUSTOMERSERVICE_KEYWORDS` → `_get_welcome_config()`
  - 2072 brand-new-contact welcome → `_get_welcome_config()`
  - 6759 / 6768 / 6777 / 6786 inside `_handle_list_reply` (customer-service, Bharat
    Stack, main menu, language picker)
  - 7525 / 7542 / 7550 / 7558 / 7613 / 7622 inside `_process_ai_automation`, all
    **unreachable** (see next point)
  Decision: delete the function. Nothing outside the menus uses it.
- **`_process_ai_automation` (7399-7836) is a stub whose body is dead.** Its first
  statement after the docstring is `return None` (confirmed by AST: body starts
  `['Expr', 'Return', 'Assign']`). Everything from the statement after that `return`
  to line 7836 is unreachable, and it is where the language picker, the region
  language lists and `showMainMenu` / `showSubMenu` dispatch live. Deleting that
  tail has **provably zero** runtime effect and is the only way to remove the
  language-picker menu without leaving dangling references.
- **`_send_ivr_menu` (whatsapp-calling/handler.py:2012-2072) has NO caller.** Already
  dead code; `_auto_pickup_and_play` (1703-1814) does not call it. Verify during
  implementation before deleting.
- **`_send_incoming_call_sms` (1508-1560) has NO caller either**, but it is an SMS
  sender that happens to call `_send_call_whatsapp_notification` at 1557. Leave the
  function; only its docstring needs the `wd_menu` wording removed.
- **`_react_thumbs_up` (972-1008) and `_is_auto_thumb_reaction_enabled` (957-969)
  must survive.** `tests/test_calling.py::TestAutoThumbReaction` and
  `TestCallingAutoThumbConfig` import and exercise them directly.
- **`_is_postcall_wa_enabled` (1657-1667) must survive.** `tests/test_calling.py:573`
  patches it, and `_get_config` reports it at 2254.
- **`_send_cta_button`, `_send_followup_buttons`, `_send_help_about` keep callers**
  from the typed-keyword paths (`STORE_KEYWORDS`, `GIFT_KEYWORDS`, `FAQ_KEYWORDS`,
  `ABOUT_KEYWORDS`, `BHARAT_KEYWORDS`, `HELP_ABOUT_KEYWORDS`), which this task does
  not touch. Do not delete them.
- `modules/content.py:72-82` only forwards `list_reply` / `button_reply` ids as text.
  It is prefix-agnostic and unaffected. `tests/test_content.py:46` uses id `custom`.
  Leave it alone.

### Design decision: the trigger SETS stay, their BODIES change

The task's deletion list item 7 says to remove `BUTTON_MENU_TRIGGERS`, while its
REPLACE section requires that "a menu trigger word" and "typing menu / hi / get
started" route to the catch-all text. You cannot route a trigger word without a
trigger-word set. Resolution, applied throughout: **keep the detection
(`HI_KEYWORDS`, `BUTTON_MENU_TRIGGERS`, `CUSTOMERSERVICE_KEYWORDS`) and replace the body
that fired `_send_interactive_list` with the catch-all send.** What is deleted is
the menu-sending logic, which is what both halves of the instruction actually
require. This also keeps `tests/test_own_prefill_triggers_menu.py` meaningful rather
than forcing its deletion.

### The catch-all text

Exact copy, used verbatim in both handlers:

```
We're refreshing our menu - please type *menu* and we'll help you.
```

It is deliberately self-referential (typing `menu` returns the same line). That is
what the task specifies, and it is the correct holding behaviour: the customer gets
an acknowledgement instead of silence, and there is exactly one string to replace
when the fresh menu is designed.

---

## Plan

- [ ] 1. Re-derive every line number in this plan against the current working tree
      before making any edit, and record the baseline.
      Another session committed to `inbound-whatsapp-handler/handler.py` during
      planning, so the offsets may have moved again. Run the AST helper already in
      the tree and the focused test baseline.
      Files: none (read-only step). `.scratch/menu_extents.py` exists and prints the
      current line range of every function and menu dict named in this plan.
      Verify: `cd /Users/wecaredigital/wecare-store && git status --short` (as its own
      command) shows no modification to either handler, `git log --oneline -1` is
      recorded, `.venv/bin/python .scratch/menu_extents.py` prints ranges, and
      `.venv/bin/python -m pytest tests/test_one_menu.py tests/test_own_prefill_triggers_menu.py tests/test_calling.py tests/test_inbound_whatsapp.py tests/test_content.py -q`
      is green. Capture the pass count as the baseline.

- [ ] 2. Add the catch-all constant and helper to the inbound handler.
      Add module constant `MENU_PLACEHOLDER_TEXT = "We're refreshing our menu - please type *menu* and we'll help you."`
      immediately after `DEFAULT_FALLBACK_MESSAGE` (handler.py:133), and a helper
      `_send_menu_placeholder(contact_id, phone_number_id, request_id)` immediately
      **above** `_send_interactive_list` (currently 5004) so it sits where the thing
      it replaces used to be. The helper logs one line
      (`{'event': 'menu_placeholder_sent', 'contactId': mask_contact_id(contact_id), 'requestId': request_id}`)
      and delegates to `_send_ai_auto_reply(contact_id, MENU_PLACEHOLDER_TEXT, phone_number_id, request_id)`
      — already the module's plain-text sender (4694-4731, invokes
      `OUTBOUND_WHATSAPP_FUNCTION` with `content`, no `isInteractive`). Keep it to
      ~6 lines so it is trivial to swap for a real menu later.
      Files: `amplify/functions/messaging/inbound-whatsapp-handler/handler.py`
      Verify: `.venv/bin/python -c "import ast,sys; ast.parse(open('amplify/functions/messaging/inbound-whatsapp-handler/handler.py',encoding='utf-8').read())"`
      exits 0, and `.venv/bin/python -m pytest tests/test_inbound_whatsapp.py -q`
      still passes.

- [ ] 3. Repoint the six reachable menu send sites in `_process_message` at the
      catch-all.
      Replace each `_send_interactive_list(..., list_config=_get_welcome_config(), ...)`
      call with `_send_menu_placeholder(contact_id, aws_phone_number_id, request_id)`,
      keeping every surrounding `logger.info`, `return`, `welcomeSent` DynamoDB update
      and `try/except` exactly as-is (only the send line changes). Keep the
      `HI_KEYWORDS` (1928), `BUTTON_MENU_TRIGGERS` (1667) and `CUSTOMERSERVICE_KEYWORDS`
      (1984) sets and their `strip_decorative_edges` fallbacks verbatim — see the
      design decision above; `tests/test_own_prefill_triggers_menu.py` asserts those
      guard strings character for character. Update the now-wrong comments
      ("Send ONLY the main menu", "It opens the one menu now") to say the menu is
      deleted and a placeholder is sent.
      Sites, in file order:
      - 1436-1443 `followup_explore` button tap
      - 1623-1637 `request_welcome`
      - 1667-1685 `BUTTON_MENU_TRIGGERS` (ice-breaker / Get Started as `button`)
      - 1928-1952 `HI_KEYWORDS` (hi / menu / `/menu` / QR prefills)
      - 1984-1998 `CUSTOMERSERVICE_KEYWORDS`
      - 2064-2090 brand-new-contact welcome (keep the `welcomeSent` write — without it
        the placeholder would re-send on every message from a new contact)
      Files: `amplify/functions/messaging/inbound-whatsapp-handler/handler.py`
      Verify: `grep -c "_send_interactive_list(" <file>` drops from 12 to 6 (the 4 in
      `_handle_list_reply` + ... — exact count depends on step order, so assert instead
      that `_send_interactive_list` no longer appears anywhere between lines 1 and 2500),
      and `.venv/bin/python -m pytest tests/test_own_prefill_triggers_menu.py tests/test_inbound_whatsapp.py -q`
      passes.

- [ ] 4. Gut `_handle_list_reply` down to a catch-all.
      Replace the whole body of `_handle_list_reply` (6642-6914) with: the existing
      `list_reply_received` log line (keep `listId` in full — a row id is not a secret
      and is the only correlation handle) plus a single
      `_send_menu_placeholder(contact_id, phone_number_id, request_id)`. Keep the
      function name and its five-parameter signature unchanged — it is called with
      keyword arguments at 1455-1461 and `sender_phone` becomes unused but must stay
      in the signature. This deletes, in one edit:
      - the `MENU_TO_KEYWORD` dict (6665-6750) in full — all ~60 ids
      - `action = MENU_TO_KEYWORD.get(list_id)` (6752) and every `if action == ...`
        branch: `_customerservice_menu` (6757-6765), `_bharat_stack_menu` (6766-6774),
        `_main_menu` (6775-6783), `_language_menu` (6784-6792), `_cta_faq`, `_cta_gift_card`,
        `_cta_store`, `_cta_bharat_stack`, `_cta_about`, `_cta_help`
      - the keyword-triggered-flow dispatch loop over `_get_flow_triggers_config()`
      - the `pay` branch that invokes `wecare-invoice-engine`
      - the `list_reply_unhandled` tail
      Note the deliberate consequence: a tap on a row still sitting in a customer's
      chat history no longer reaches a flow or a payment — it gets the placeholder.
      That is what "delete the dispatch logic that routes list_reply ids to actions"
      means, and the typed-keyword equivalents (`pay`, `store`, `gift card`, `faq`,
      `about`, `help & about`, and every `DEFAULT_FLOW_TRIGGERS` keyword) are all
      untouched, so nothing becomes unreachable by any other route.
      Files: `amplify/functions/messaging/inbound-whatsapp-handler/handler.py`
      Verify: `grep -n "MENU_TO_KEYWORD" <file>` returns nothing (including the stale
      comment references at 6279 and 6962), the module still imports
      (`.venv/bin/python -c "import importlib.util, sys; ..."` loading by file path the
      way `tests/test_one_menu.py` does), and `.venv/bin/python -m pytest tests/test_inbound_whatsapp.py -q` passes.

- [ ] 5. Delete every menu definition and every menu getter.
      Remove these contiguous blocks together with their leading comment banners
      (the banners describe menus that no longer exist and are worse than nothing):
      - `DEFAULT_ONE_MENU` 6956-6969 + banner 6944-6955 (the already-emptied one)
      - `DEFAULT_MAIN_MENU` 6976-7007 + banner 6970-6975 (retired main menu, 9 rows)
      - `DEFAULT_LANGUAGE_PICKER` 7009-7025 (region picker, 4 rows)
      - `REGION_LANGUAGE_LISTS` 7028-7086 (25 language rows across 4 regions)
      - `_get_welcome_config` 7089-7117
      - `DEFAULT_BHARAT_STACK_MENU` 7121-7139 + its banner
      - `_get_bharat_stack_menu` 7142-7155
      - `DEFAULT_CUSTOMERSERVICE_MENU` 7162-7223 + banner (9 `ss_*` rows)
      - `_get_customerservice_menu` 7226-7239
      - `_get_language_picker_config` 7242-7265
      - `_get_region_language_list` 7268-7284
      - `_send_interactive_list` 5004-5050 (no non-menu caller; see the verified
        caller list above — re-confirm with a grep before deleting)
      Keep `_get_welcome_config_key` (125-130) and `_load_welcome_text` (320-333):
      they read the `welcome_message` / `welcome_message_2` text config, not a menu.
      Keep `DEFAULT_FLOW_TRIGGERS` (6280-6446) and `_get_flow_triggers_config` — they
      drive typed keyword flows, not menus.
      Files: `amplify/functions/messaging/inbound-whatsapp-handler/handler.py`
      Verify: `grep -nE "DEFAULT_ONE_MENU|DEFAULT_MAIN_MENU|DEFAULT_CUSTOMERSERVICE_MENU|DEFAULT_BHARAT_STACK_MENU|DEFAULT_LANGUAGE_PICKER|REGION_LANGUAGE_LISTS|_get_welcome_config\(|_get_customerservice_menu|_get_bharat_stack_menu|_get_language_picker_config|_get_region_language_list|_send_interactive_list" <file>`
      returns nothing, and the module loads by file path without raising.

- [ ] 6. Delete the unreachable tail of `_process_ai_automation`.
      The function (7399-7836) returns `None` as its first statement after the
      docstring. Delete every statement after that `return None` so the stub is a
      real stub. This is what removes the last four `_send_interactive_list` call
      sites (7525, 7542, 7550, 7558, 7613, 7622) and the `showMainMenu` /
      `showSubMenu` / `showLanguagePicker` dispatch, and it is required by step 5 —
      otherwise that dead code references names that no longer exist. Confirm with
      an AST check that `return None` really is the first non-docstring statement
      before deleting anything; if it is not, stop and report rather than guessing.
      Keep the `def`, the full signature, the docstring and `return None`.
      Files: `amplify/functions/messaging/inbound-whatsapp-handler/handler.py`
      Verify: an AST walk shows `_process_ai_automation` has exactly two body
      statements (docstring `Expr`, then `Return`); `grep -n "showMainMenu\|showSubMenu\|showLanguagePicker" <file>`
      returns nothing; module loads; `.venv/bin/python -m pytest tests/test_inbound_whatsapp.py tests/test_content.py tests/test_wa_internal_event.py -q` passes.

- [ ] 7. Replace the inbound-handler test that pins the deleted menus.
      Delete `tests/test_one_menu.py` — it exists solely to assert the existence and
      shape of `DEFAULT_ONE_MENU`, `DEFAULT_MAIN_MENU`, `DEFAULT_CUSTOMERSERVICE_MENU`,
      `DEFAULT_BHARAT_STACK_MENU`, `MENU_TO_KEYWORD`, `_get_welcome_config` and the
      retired submenu branches, every one of which is gone after steps 4-6. Its one
      still-valuable assertion (`TestTheRivalMenuIsGone`, which reads
      `ai-generate-response`'s `DEFAULT_BOT_FLOW` and asserts it defines no menu)
      moves to the new file.
      Add `tests/test_menus_are_deleted.py` asserting the wipe holds, modelled on the
      module-loading fixture already in `tests/test_own_prefill_triggers_menu.py`
      (unique module name via `importlib.util.spec_from_file_location`, because every
      Lambda entry point in this repo is named `handler.py` and `conftest.py` clears
      `sys.modules['handler']`). Assertions:
      - no module attribute matching `DEFAULT_*_MENU`, `REGION_LANGUAGE_LISTS`,
        `_get_welcome_config`, `_get_customerservice_menu`, `_get_bharat_stack_menu`,
        `_get_language_picker_config`, `_get_region_language_list`,
        `_send_interactive_list` exists on the inbound handler
      - an AST walk of the source finds no `MENU_TO_KEYWORD` or `BUTTON_MENU_TRIGGERS`-
        driven `_send_interactive_list` call, and no `Assign` named `MENU_TO_KEYWORD`
        at any nesting depth (reuse `_nested_literal`'s walk, inverted)
      - `_handle_list_reply` exists, keeps its 5-parameter signature, and its source
        contains `_send_menu_placeholder`
      - `MENU_PLACEHOLDER_TEXT` is exactly the agreed string and contains no `*menu*`
        interactive markup beyond the bold marker
      - the three trigger paths still route to the placeholder: the source between
        `HI_KEYWORDS = {` / `BUTTON_MENU_TRIGGERS = {` / `CUSTOMERSERVICE_KEYWORDS = {`
        and the following `return` contains `_send_menu_placeholder` and does **not**
        contain `_send_interactive_list`
      - `ai-generate-response`'s `DEFAULT_BOT_FLOW` still defines no `mainMenu` /
        `subMenus` (carried over from `TestTheRivalMenuIsGone`)
      Files: delete `tests/test_one_menu.py`; create `tests/test_menus_are_deleted.py`
      Verify: `.venv/bin/python -m pytest tests/test_menus_are_deleted.py tests/test_own_prefill_triggers_menu.py -q`
      passes and `tests/test_one_menu.py` is gone from collection
      (`.venv/bin/python -m pytest tests/ -q --collect-only 2>&1 | grep -c test_one_menu`
      is 0).

- [ ] 8. Add the catch-all constant and helper to the calling handler.
      Add `MENU_PLACEHOLDER_TEXT = "We're refreshing our menu - please type *menu* and we'll help you."`
      next to `IVR_SMS_CONTENT` (around 1471), and a helper
      `_send_menu_placeholder_text(meta_id, to_phone, request_id='') -> str` that posts
      a `{'type': 'text', 'text': {'body': MENU_PLACEHOLDER_TEXT}}` message through the
      existing `_meta_api_call(f"{meta_id}/messages", 'POST', payload, phone_number_id=meta_id)`
      and returns the Meta message id or `''`. Using `_meta_api_call` (not
      `_send_via_aws`) is deliberate: the returned wamid belongs to `meta_id`'s own
      conversation, which is the precondition `_react_thumbs_up` documents at 972-1008,
      so the existing auto-👍 keeps working.
      Record in the helper's docstring that this is a plain text send, so it needs an
      open 24-hour window — the deleted `wd_menu` template was what allowed a send
      outside it. A post-call message to someone who never messaged the business will
      now fail. That is expected, it is logged, and both call sites already treat the
      send as non-blocking.
      Files: `amplify/functions/messaging/whatsapp-calling/handler.py`
      Verify: `.venv/bin/python -c "import ast; ast.parse(open('amplify/functions/messaging/whatsapp-calling/handler.py',encoding='utf-8').read())"`
      exits 0 and `.venv/bin/python -m pytest tests/test_calling.py -q` still passes.

- [ ] 9. Delete `_send_ivr_menu` and strip `wd_menu` from the two live call paths.
      - **Delete `_send_ivr_menu` entirely** (2012-2072), including its plain-text
        fallback and its `_update_call_status(call_id, 'ivr_menu_sent', {'ivrTemplate': 'wd_menu', ...})`
        write. Re-confirm it has no caller first
        (`grep -n "_send_ivr_menu" <file>` should show only the `def`).
      - **`_send_call_whatsapp_notification` (2565-2712):** delete the `template_msg`
        dict (the `wd_menu` template with the VIDEO header param) and replace both the
        first send and the 2-second retry with `_send_menu_placeholder_text(meta_id, caller_phone, request_id)`.
        Keep: the `is_waba2` / `send_from` WABA1-vs-WABA1+WABA2 fan-out, the retry,
        the `_store_notification_to_inbox` call (change `content` to
        `MENU_PLACEHOLDER_TEXT`, dropping the `[wd_menu template via ...]` prefix), the
        `_react_thumbs_up` call, the error logging (drop the now-false
        `troubleshoot` text claiming "wd_menu IS approved"), and the
        `CallNotifications` `put_item`. Set `whatsappTemplate` to `'none'` rather than
        `''` — DynamoDB accepts an empty non-key string but `'none'` reads correctly in
        the dashboard. Rename the log events from `call_wa_template_sent` /
        `call_wa_template_FAILED` only if nothing queries them; **verify during
        implementation** (grep `scripts/`, `docs/`, CloudWatch dashboards) and leave
        the names alone if unsure.
      - **`_handle_post_call_sip` (1011-1168):** delete the `template_msg` dict
        (1077-1093ish) and replace the per-WABA template send loop with
        `_send_menu_placeholder_text(meta_id, caller_phone, request_id)`. Delete the
        "all `wd_menu` sends failed, falling back to text" block that sent
        `IVR_SMS_CONTENT` via `_send_via_aws` — there is no template to fall back from
        any more, and the placeholder is already the text. Keep the
        `_is_postcall_wa_enabled()` gate, `send_from`, `first_msg_id`, the
        `_react_thumbs_up` call, the breadcrumb, the `WhatsAppOutboundTable` store
        (`content` becomes `MENU_PLACEHOLDER_TEXT`, no `[wd_menu template]` prefix),
        the post-call SMS step and the post-call RCS step.
      - **Docstring/comment cleanup only** (no logic change) at: 767
        ("WhatsApp wd_menu template IS still sent on connect"), 958
        (`_is_auto_thumb_reaction_enabled`), 1015 (`_handle_post_call_sip` docstring),
        1509-1513 (`_send_incoming_call_sms` docstring), 1658
        (`_is_postcall_wa_enabled` docstring).
      - **Do NOT touch**, per the task: `_SHARED_IVR_MENU` (1906-1918), `IVR_MENUS`
        (1919-1922), `IVR_DEFAULT_MENU` (1925-1937), `IVR_RESPONSES` (1939-1989),
        `_get_ivr_menu` (1991-2009), `_react_thumbs_up`,
        `_is_auto_thumb_reaction_enabled`, `_is_postcall_wa_enabled`,
        `_send_incoming_call_sms`'s SMS logic, `IVR_SMS_CONTENT`,
        `IVR_SMS_DLT_TEMPLATE_KEY`.
      Files: `amplify/functions/messaging/whatsapp-calling/handler.py`
      Verify: `grep -c "wd_menu" <file>` is 0; `grep -n "_SHARED_IVR_MENU\|IVR_DEFAULT_MENU\|IVR_RESPONSES\|_get_ivr_menu" <file>`
      still finds all four; `.venv/bin/python -m pytest tests/test_calling.py -q` passes
      (this covers `TestIVRMenuParity`, `TestAutoThumbReaction`,
      `TestCallingAutoThumbConfig` and the two `_send_call_whatsapp_notification`
      patch sites at 158/212/386/401).

- [ ] 10. Decide each remaining menu-related test, and run the full Python suite.
      Per-file decisions, all grounded in a read of the file:
      - `tests/test_one_menu.py` — **DELETE** (step 7). Every class asserts a menu
        that no longer exists.
      - `tests/test_own_prefill_triggers_menu.py` — **UPDATE, minimally.** It passes
        unchanged if steps 3 keeps the sets and guard strings, because every assertion
        is about `HI_KEYWORDS` / `BUTTON_MENU_TRIGGERS` membership,
        `_STANDBY_TEXT_TRIGGERS`, `_DETERMINISTIC_KEYWORDS`, `strip_decorative_edges`
        and the literal guard expressions — none of which this task removes. Update
        only the module docstring and the class/method names that say "open the menu"
        to say "reach the placeholder". Run it first *without* edits to confirm it is
        green; if `test_menu_sets_use_the_fallback` fails, a guard string was altered
        in step 3 and that is the bug, not the test.
      - `tests/test_calling.py` — **KEEP, no change expected.** Its only `wd_menu`
        reference is a docstring at 493 (`TestAutoThumbReaction`); it patches
        `_send_call_whatsapp_notification` rather than asserting its payload. Optionally
        reword that docstring. **Verify during implementation** that nothing asserts a
        template payload.
      - `tests/test_outbound_whatsapp.py:218` — **KEEP.** It passes a literal
        `{'template': {'name': 'wd_menu'}}` to `_send_direct_api` as an arbitrary
        payload fixture; it tests transport, not the template. Out of scope.
      - `tests/test_notifications_domain.py:576,616` — **KEEP, do not change.** These
        assert `lambda_utils/notifications/policy.py`'s `WA_TEMPLATE_NAME` default
        (`wd_menu`) and `rcsmenu`. That is the connected-call notification domain, a
        different subsystem that this task does not name, and it is gated off
        (`PSTN_CONNECTED_NOTIFICATIONS_ENABLED` is absent from every function). See
        the findings section.
      - `tests/test_content.py` — **KEEP.** Only exercises id passthrough with id
        `custom`.
      Files: `tests/test_own_prefill_triggers_menu.py` (docstring/naming only)
      Verify: `.venv/bin/python -m pytest tests/ -q` — the whole `tests/` tree is
      green, with the only delta against the step-1 baseline being
      `tests/test_one_menu.py`'s tests removed and `tests/test_menus_are_deleted.py`'s
      added. Then `.venv/bin/python -m pytest -q` (bare, which picks up
      `testpaths = tests amplify/functions` from `pytest.ini`) to catch anything under
      `amplify/functions/**`.

- [ ] 11. Confirm both Lambdas still import cleanly, then commit by explicit path.
      Load each handler by file path under a unique module name with `boto3.resource`
      and `boto3.client` patched (the pattern `tests/test_calling.py` and
      `tests/test_one_menu.py` both use) and confirm no exception. Do **not** deploy,
      do **not** run `scripts/deploy_all_lambdas.py`, do **not** run
      `scripts/snapstart_publish.py`, do **not** move any `live` alias. Then:
      ```
      git status --short                        # its own command; read it
      git add tests/test_menus_are_deleted.py
      git commit --only \
        amplify/functions/messaging/inbound-whatsapp-handler/handler.py \
        amplify/functions/messaging/whatsapp-calling/handler.py \
        tests/test_menus_are_deleted.py \
        tests/test_one_menu.py \
        tests/test_own_prefill_triggers_menu.py \
        -F .scratch/menu-wipe-commit-msg.txt
      ```
      `--only` is mandatory here: another session committed to the inbound handler
      during planning, so the index may already hold work that is not ours
      (`.kiro/steering/multi-session-parallel-agents.md` rule 3b). The deleted
      `tests/test_one_menu.py` must be named in the pathspec for the deletion to be
      recorded. Push with `git push origin stack` only if the full suite is green.
      Files: none (verification + commit)
      Verify: `git show --stat HEAD` lists exactly the five paths above and no others;
      `git status --short` afterwards shows no leftover modification to either handler;
      `.venv/bin/python -m pytest -q` is green on the committed tree.

---

## Findings — out of scope, reported not changed

1. **`wd_menu` is still sent by two other Lambdas.** The template was deleted at
   Meta, so these sends will fail the same way the ones in this task would have:
   - `amplify/functions/messaging/voice-in/obd/handler.py` lines 832, 928-990, 1018
   - `amplify/functions/messaging/voice-in/c2c/handler.py` lines 356, 439-501, 529
   Both are PSTN CDR follow-up paths. The task scopes this work to two handler files,
   so they are left alone — but they are broken in production right now and need the
   same treatment. Flag to the owner.
2. **`lambda_utils/notifications/policy.py:51`** defaults `WA_TEMPLATE_NAME` to
   `wd_menu` (overridable by `NOTIF_WA_TEMPLATE_NAME`), and
   `tests/test_notifications_domain.py:616` asserts it. Changing it would alter
   behaviour in a subsystem this task does not name, and the path is gated off
   (`PSTN_CONNECTED_NOTIFICATIONS_ENABLED` absent from all 65 functions per
   `.kiro/steering/02-qa-recipient.md`). Left unchanged; set the env var when the
   fresh template exists.
3. **`rcs/templates/drafts/wd_menu_apex.json`** is an RCS draft, not a WhatsApp
   template. Unaffected.
4. **`docs/whatsapp-experience-structure.md`** documents the menu structure in detail
   and will be stale after this change. Not updated — the task did not ask for it,
   and the fresh menu design will rewrite it anyway.
5. **Nothing here is live until a deploy happens.** Per
   `.kiro/steering/lambda-snapstart-deploy.md`, both functions sit behind a `live`
   alias, so `$LATEST` changes do not reach production until a version is published
   and the alias moves. This task explicitly forbids that, so the menus remain live
   on the two WABAs until the owner authorises a deploy. Say so in the final report.
6. **`DEFAULT_FALLBACK_MESSAGE` (handler.py:133)** still reads "Type 'menu' to see
   available options". It is loaded by `_load_fallback_message` for an unmatched
   message. Consistent enough with the placeholder to leave, but worth a one-line
   reword — **verify during implementation** whether any dashboard config row
   overrides it before touching the default.
