# Lightsail Nano cutover (owner-approval required)

Prerequisite: feasibility verdict is GO or CONDITIONAL GO from
`lightsail-nano-feasibility.md` AND `preflight.sh` was run on the box with
acceptable memory/disk evidence. Today the verdict is INCOMPLETE (no host SSH
access from here), so this cutover is **not yet authorised**.

Scripts: `scripts/lightsail-nano-migration/` (dry-run by default). Every mutating
step requires `APPLY=1 CONFIRM=I-APPROVE-<step>`.

## Sequence (each step 🔒)
1. Verify recovery snapshot `wecare-voice-bot-backup-20261007` is `available`.
2. `bootstrap-nano.sh` → provision fresh `nano_3_0`, open 5061/TCP + 10000-60000/UDP.
3. `migrate-workload.sh` (no cutover) → rsync `/etc/asterisk`, `/etc/letsencrypt`,
   custom sounds with sha256 checksums; install Asterisk; add 1G swap (Nano has
   512MB RAM — swap is the margin that makes 512MB viable).
4. `verify-nano.sh` → passive 5061 reachability + TLS cert + attachment.
5. Measure Nano RAM/disk/CPU under load (in-guest `free -m`/`df -h`).
6. `migrate-workload.sh --cutover` → move static IP `wecare-static-ip` to the
   nano. `sip.wecare.digital` points at the IP, so no DNS change is needed.
7. Human places a REAL WhatsApp call; `python scripts/test_call_paths.py watch`
   must show non-empty `sipHeaders` (cannot be self-certified).
8. Keep the micro RUNNING for rollback until acceptance.

## Hard constraints
- No in-place downgrade (Lightsail cannot restore a 40GB snapshot onto 20GB).
- No change to customer phone numbers, WABA registration, or Meta Calling settings.
- The static IP is the ONLY routing lever; moving it is both the cutover and the
  rollback.

## After acceptance (separate approval)
Stop + delete the micro; decide snapshot retention ($2/mo for 40GB); re-run
`scripts/aws_cost_model.py --live` to record the REALISED $2/mo.
See `lightsail-nano-rollback.md`.
