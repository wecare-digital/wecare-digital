# Lightsail Nano cutover (owner approval required)

Prerequisite: `lightsail-nano-feasibility.md` says GO or CONDITIONAL GO, based on
`preflight.sh` output from the box. Today the verdict is **NO-GO (evidence incomplete)**, so this
cutover is not authorised.

Scripts: `scripts/lightsail-nano-migration/` — dry-run by default; a mutating step needs
`APPLY=1 CONFIRM=I-APPROVE-<step>`; every mutating step first checks that the recovery
snapshot is `available`; `NANO_INSTANCE` can never name the production micro.

## Sequence (each step 🔒)

1. `bootstrap-nano.sh` — fresh `nano_3_0`, ports 5061/TCP and 10000-60000/UDP.
2. On the nano, install the same Asterisk version `preflight.sh` reported for the micro
   (Amazon Linux 2023 has no Asterisk package).
3. `migrate-workload.sh` — streams `/etc/asterisk`, `/etc/letsencrypt` and custom sounds with
   `ssh | tar`, compares SHA-256 tree digests, adds 1 GB swap if none, restarts Asterisk.
4. `verify-nano.sh --pre-cutover` — 5061 reachable on the nano's own IP, CN check.
5. Measure nano RAM, swap, disk and CPU in the guest during approved test calls.
6. `PRECUTOVER_VERIFIED=1 migrate-workload.sh --cutover` — moves `wecare-static-ip`.
   `sip.wecare.digital` follows the IP; no DNS change.
7. `verify-nano.sh`, then an approved real WhatsApp call: two-way audio, IVR prompts, post-call
   callback logged by `wecare-whatsapp-calling`.
8. Keep the micro running until acceptance. `rollback.sh` moves the IP back.

## Hard constraints

- No in-place downgrade (a 40 GB micro snapshot cannot restore onto a 20 GB nano).
- No change to phone numbers, WABA registration or Meta Calling settings.
- The static IP is the only routing lever.

## After acceptance (separate approval)

Stop and delete the micro, decide snapshot retention (about $0.27/month at the measured
5.3 GB-month), and record the realised $2/month only once the micro stops billing.
See `scripts/lightsail-nano-migration/ROLLBACK.md`.
