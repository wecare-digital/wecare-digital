# Inbox read rollout

The Inbox handler reads the manually managed canonical MessagesTable, where
`id` is a string primary key and the shared writer emits numeric Unix-second
`timestamp` values with lowercase channels. The Amplify `Message` model is not
the source of truth for this table: it declares a different primary key and an
ISO datetime. Do not use an Amplify deploy to modify the canonical table, and
do not replace the older indexes used by existing routes.

## Prepare and activate

1. In staging, confirm the exact physical table used by the deployed
   messages-read Lambda (`MESSAGES_TABLE` or its fallback). Audit legacy data
   readiness: rows without a numeric timestamp or with missing/noncanonical
   keys will not be represented in the new indexes. Validate operational cost
   and monitor DynamoDB online index build progress, capacity and throttling.
2. Inspect with:
   `python scripts/provision_inbox_timeline_indexes.py --region REGION --table TABLE --expected-account ACCOUNT`.
   This does not read or change message data. In a separately approved maintenance
   change, add `--apply` to create **one** missing index. Wait for it to become
   `ACTIVE` with no backfill before applying again. On provisioned tables, set
   approved positive `--read-capacity` and `--write-capacity` explicitly.
3. The additive index definitions are `inbox-channel-timestamp-index`
   (`channel:S` HASH, `timestamp:N` RANGE) and
   `inbox-contact-timestamp-index` (`contactId:S` HASH, `timestamp:N` RANGE).
   Both project `ALL`; measure write amplification and storage during staging.
   The script never deletes or alters an existing index and refuses schema drift.
4. Deploy the messages-read Lambda before the new Inbox UI where possible.
   If the UI rollout requires full history, wait until the indexes and backend
   flag are verified before publishing the UI. Otherwise it starts in its
   clearly labeled compatibility mode.
   Leave `INBOX_TIMELINE_INDEXES_ENABLED` unset/false until both indexes are
   active, staging validates ordering, and IAM grants `DescribeTable` on the table
   and `Query` on both index ARNs. Enable the flag on the reviewed Lambda
   version, preserving existing environment values, and promote its live alias.
   Record the flag in the live environment manifest only after verifying the
   deployed value.
   Runtime rechecks table and index key types, projection and active/backfill
   status, caching the result for one minute per execution environment.
5. Smoke-test both Inbox screens and a saved thread with mixed channels, equal
   timestamps and several pages. Verify partial-channel warnings when a query
   fails and the continuation after the channel recovers. For rollback, repoint
   the alias to the previous version or disable the flag on a new version and
   promote it; leave the indexes intact.

## Runtime contracts

- Legacy `GET /messages` is unchanged. New clients use `view=inbox`. An older
  server response shows a compatibility warning. With the new server but no
  ordered indexes ready, the API returns an explicitly **limited sample** with
  no cursor: one bounded scan of at most 300 evaluated items (overview), or
  one bounded legacy contact query, with a scan only if its index is unavailable.
  These samples are not guaranteed to include recent or old history; the UI says
  so and reduces automatic sample refreshes to once every two minutes. An older
  cursor is rejected instead of being reinterpreted by the fallback.
- Recent Activity is a channel-balanced page, not a globally ranked conversation
  index. Native DynamoDB continuation keys preserve the exact position within
  each channel. Saved-contact threads use one chronological cursor across all
  channels. Phone-only history is confined to loaded Activity pages. A failed
  channel is explicitly marked unavailable rather than silently omitted.
  If new traffic overtakes already loaded pages, restart history from the
  latest page before continuing.
- `stats=count` retains the existing count keys and adds observation status and
  confirmed-delivery counters. No outbound data has a null delivery rate; sent
  alone is not delivery. A failed or over-budget aggregation returns a marked
  stale observation if one is available, or 503. The cache is per warm Lambda
  instance, not fleet-wide. If the read budget is exhausted, add an independently
  reconciled aggregate, not a higher synchronous scan limit or authoritative-
  looking partial counts.
