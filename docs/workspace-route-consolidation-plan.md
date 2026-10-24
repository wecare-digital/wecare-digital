# `/workspace/` route consolidation — plan, not yet executed

Measured 2026-09-26. `bw-crm.md` records this work as `NOT_STARTED` and instructs:
"Inventory every route/capability, then migrate without losing working functions;
remove duplicates only after redirects/parity tests." This document is that first
step. No routes have been moved.

## Why this is not a rename

    126   TSX page files under src/pages
    761   built static routes in out/
     25   Amplify custom rules today

Every moved route needs a redirect, or a bookmark and a search-engine result both
break. 761 routes is the number that decides the approach: this cannot be a single
pass, and it cannot be verified by eye.

The site is a **static export** (`output: 'export'`, `trailingSlash: true`). Two
consequences that shape everything below:

- A static host treats `/a/b` and `/a/b/` as different keys, so each redirect needs
  **both** forms. `docs/frontend-route-retirement.md` already learned this: 23 live
  Amplify rules cover 9 retired paths precisely because of the bare/trailing pair.
  Budget ~2 rules per moved route.
- There is no server to redirect at request time. Redirects are Amplify custom
  rules, and those are an ordered list evaluated before the SPA catch-all. A
  mis-ordered rule does not error — the catch-all answers **200 with the app shell**,
  so a broken route looks like a working page. That failure mode is why parity tests
  have to assert the *target*, not the status code.

## The good news: the shape mostly exists

The requested tree is largely a regroup of the legacy direct-messaging page set, not new construction:

| Requested | Exists today as |
|---|---|
| `workspace/engage/inbox` | `dm/inbox` |
| `workspace/engage/broadcast` | `dm/broadcast` |
| `workspace/engage/whatsapp` | `dm/whatsapp` |
| `workspace/engage/rcs` | `dm/rcs` |
| `workspace/engage/sms` | `dm/sms` |
| `workspace/engage/email` | `dm/ses` |
| `workspace/engage/voice` | `dm/voice` + `dm/voice-in` + `dm/calls` |
| `workspace/contacts` | `contacts/` + `dm/contact-360` |
| `workspace/commerce` | `commerce/` + `dm/commerce` + `dm/orders` |
| `workspace/automation` | `dm/automation` |
| `workspace/analytics` | `dm/analytics` |
| `workspace/seo` | `seo/` |
| `workspace/docs` | `docs/` + `dm/docs` |
| `workspace/admin` | `admin/` |
| `workspace/settings` | `settings/` + `dm/settings` |

Three of those rows are **merges, not moves** — `engage/voice` folds three existing
sections, and `contacts`, `commerce`, `docs` and `settings` each fold a top-level
section together with a `dm/` one. A merge needs a decision about which page wins
and what happens to the other's unique features; it is not mechanical, and it is
where capability gets lost silently.

Also note `dm/` holds sections the proposed tree does **not** name: `appointments`,
`channels`, `content`, `cost`, `documents`, `enterprise`, `faq`, `logs`, `meta-agent`,
`push`, `reviews`, `rx-slots`, `scheduled`, `search`, `service-ops`. Fifteen
sections with no home in the target. They must be assigned before starting, because
"we'll find a place later" is how a route ends up orphaned but still built.

## Sequence

1. **Generate the inventory as data**, not prose: every one of the 761 routes with
   its source file, its target section, and whether it is a move or a merge. A
   hand-written mapping over 761 routes is wrong within a week.
2. **Assign the 15 unlisted `dm/` sections** to a target, or mark them explicitly
   for retirement with evidence they are unused.
3. **Resolve each merge** by naming the surviving page and listing the features the
   other page has that it lacks.
4. **Move one section at a time**, smallest first, each with: new route, redirect
   rules for both slash forms, internal link updates, and a parity test asserting
   the redirect's *target*.
5. **Keep the old route live** behind a redirect. Do not delete until traffic on it
   is measured at zero — the same discipline applied to `wecare.digital/r`.
6. **A gate** that fails when a `[retired public path 2de923b8]/*` route exists with no redirect, so the
   migration cannot half-finish silently.

## Why it was not started in this session

Steps 2 and 3 need product decisions — which of fifteen sections matter, and which
page wins each merge. Guessing those and then moving 761 routes would produce a tree
that looks like the request and quietly drops working features. The reversible,
useful part was doing the measurement above so the decisions can be made against
real numbers.
