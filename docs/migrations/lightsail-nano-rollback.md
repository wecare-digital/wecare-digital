# Lightsail Nano rollback

The authoritative, step-by-step rollback runbook lives next to the scripts at
`scripts/lightsail-nano-migration/ROLLBACK.md` so it travels with the tooling.

Summary: the production **micro** `wecare-voice-bot` stays running and billable
throughout migration; the static IP `wecare-static-ip` is the only routing lever.
Rollback = detach the static IP from the nano and re-attach it to the micro, then
`verify-nano.sh`. No DNS change is needed because `sip.wecare.digital` points at
the IP. Deeper recovery restores from snapshot `wecare-voice-bot-backup-20261007`.

Nothing is deleted until acceptance is signed off, so rollback is always available
until the final, separately-approved cleanup step.

See `scripts/lightsail-nano-migration/ROLLBACK.md` for exact commands.
