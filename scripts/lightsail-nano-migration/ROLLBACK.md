# Lightsail Nano migration — rollback runbook

The production **micro** `wecare-voice-bot` stays RUNNING and billable throughout
the migration precisely so rollback is a single IP move. Nothing is deleted until
acceptance is signed off.

## Fast rollback (undo a cutover)

If a real WhatsApp call fails after the static-IP cutover:

```bash
cd scripts/lightsail-nano-migration
# move the static IP back to the micro
APPLY=1 aws lightsail detach-static-ip --region us-east-1 --static-ip-name wecare-static-ip
APPLY=1 aws lightsail attach-static-ip  --region us-east-1 \
  --static-ip-name wecare-static-ip --instance-name wecare-voice-bot
./verify-nano.sh   # confirms 5061 + attachment back on the micro
```

`sip.wecare.digital` points at the static IP, so moving the IP back restores the
old path without any DNS change. The micro's Asterisk/SIP config was never
touched, so it serves exactly as before.

## Deeper rollback (micro somehow degraded)

Restore from the known-good snapshot (creates a NEW micro; owner-approved):

```bash
aws lightsail create-instances-from-snapshot --region us-east-1 \
  --instance-names wecare-voice-bot-restore \
  --availability-zone us-east-1a \
  --instance-snapshot-name wecare-voice-bot-backup-20261007 \
  --bundle-id micro_3_0
# then move the static IP to the restored instance as above.
```

## Preconditions that make rollback trustworthy
- Snapshot `wecare-voice-bot-backup-20261007` verified `available` before cutover.
- Micro kept running; not stopped/deleted until acceptance.
- Static IP is the only routing lever; no customer phone number, WABA
  registration, or Meta Calling setting is changed during migration.

## Cleanup (only AFTER acceptance, owner-approved, separate step)
1. Confirm several days of clean nano operation + a verified real call.
2. 🔒 Stop, then delete the micro `wecare-voice-bot`.
3. Decide snapshot retention (keeping the 40GB snapshot ≈ $2/mo).
4. Re-run `scripts/aws_cost_model.py --live` and record REALISED saving.
