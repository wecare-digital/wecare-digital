# Inbox read rollout

Deploy the messages-read Lambda before shipping the new Inbox clients. The legacy
`GET /messages` list route is unchanged. New clients request `view=inbox` and
fall back to an explicitly limited recent preview until the new backend is active.

- Recent Activity is a channel-balanced page, not a globally ranked conversation
  index. Its cursor rolls the existing channel indexes forward. Saved-contact
  threads use the contact index and independent cursors; phone-only history is
  limited to the Activity pages that have been loaded. Keep any failed channel
  visible as unavailable instead of presenting the partial result as complete.
  If new traffic overtakes older pages already loaded, both clients flag a
  possible gap and offer to restart the history cursor from the latest page.
- After deploying in staging, confirm real index/key types match cursor encoding
  and both Inbox routes can open and page a saved thread. Test the current
  backend and older-client compatibility, partial channel outages, and history
  with more than 2,000 messages.
- `stats=count` retains the existing count keys and adds observation status and
  confirmed-delivery counters. No outbound data has a null delivery rate; sent
  alone is not delivery. A failed or over-budget aggregation returns a marked
  stale observation if one is available, or 503. The cache is per warm Lambda
  instance, not a fleet-wide aggregate. Measure table size and refresh failures
  in staging; if the read budget is exhausted, add an independently reconciled
  aggregate instead of raising the synchronous scan limit or reporting partial
  counts as authoritative.
