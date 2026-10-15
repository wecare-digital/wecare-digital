# Lightsail Nano migration — rollback runbook

The production **micro** `wecare-voice-bot` stays RUNNING and billable throughout the
migration so rollback is a single static-IP move. Nothing is deleted until acceptance is
signed off.

## Fast rollback (undo a cutover)

If a real WhatsApp call fails after the static-IP cutover:

```bash
cd scripts/lightsail-nano-migration
./rollback.sh                                   # preview: shows where the IP is attached
APPLY=1 CONFIRM=I-APPROVE-rollback ./rollback.sh  # move the IP back to the micro
./verify-nano.sh                                # 5061 open, CN=sip.wecare.digital, DNS matches
```

After the IP is back on the micro, re-enable its timers there:
`sudo systemctl enable --now certbot-renew.timer wecare-cert-check.timer` (and disable them on
the nano), so certificate renewal and the daily cert check have one owner again.

`sip.wecare.digital` resolves to the static IP, so moving the IP back restores the old
path without a DNS change. The micro's Asterisk/SIP config is never modified by these
scripts (the transfer only reads from it).

## Deeper rollback (micro degraded)

Restore from the known-good snapshot (creates a NEW micro; billable; owner-approved):

```bash
aws lightsail create-instances-from-snapshot --region us-east-1 \
  --instance-names wecare-voice-bot-restore --availability-zone us-east-1a \
  --instance-snapshot-name wecare-voice-bot-backup-20261007 --bundle-id micro_3_0
# then attach wecare-static-ip to the restored instance (detach-static-ip + attach-static-ip).
```

## Preconditions that make rollback trustworthy

- `wecare-voice-bot-backup-20261007` is `available` (every mutating script checks this).
- The micro keeps running; it is not stopped or deleted until acceptance.
- The static IP is the only routing lever. No phone number, WABA registration or Meta
  Calling setting changes during the migration.

## Cleanup (only after acceptance, owner-approved, separate step)

1. Several days of clean nano operation plus verified real calls.
2. 🔒 Stop, then delete the micro `wecare-voice-bot`.
3. Decide snapshot retention. Snapshots bill on stored size: about 5.3 GB-month,
   roughly $0.27/month (measured in Cost Explorer), not the 40 GB disk size.
4. Re-run `scripts/aws_cost_model.py` and record the realised saving only after the
   micro stops billing.
