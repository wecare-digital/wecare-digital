# Repository layout and maintenance

The web application installs from root package.json/package-lock.json with npm ci. Amplify infrastructure dependencies install separately from amplify/package.json/package-lock.json. Do not move backend packages into the web root. Existing root upgrade helpers derive their groups from the web manifest and preserve the lockfile; they never recreate removed dependency lists or create a branch.

| Location | Owner/purpose | Maintenance |
|---|---|---|
| src/, public/, content/, config/ | Web UI, assets, catalogue and routing | Preserve deep links and shared component contracts; verify typecheck, export and browser checks. |
| amplify/functions/ | Python Lambda handlers and shared runtime | Scope release archives to intended behavior; capture live versions and move aliases only after exact-package checks. |
| amplify/infra/, amplify/*.ts | Infrastructure and separate backend npm root | Preserve resource identity and customer history; review changes before apply. |
| scripts/ | Manual operational entry points and build/verification tooling | Absence of a source import is not proof a script is unused; check runbooks and workflows. |
| tests/, src/test/, tools/browser/ | Offline and browser verification | Keep runtime/provider boundary tests; never delete tests simply to clear failures. |
| docs/execution/, docs/whatsapp/, seo/output/ | Dated decisions, rollout evidence and retained legacy contracts | Historical counts are snapshots; link to current evidence rather than overwriting history. |
| .kiro/work/, .scratch/ | Ignored per-task planning and scratch | Check active sessions before deleting their working data. |
| android/, ios/, native/ | Retained post-project packaging | Web project closure does not require store releases; preserve resources. |

## Cleanup applied 2026-10-09

Removed the unconsumed Material vendor package, its root dependency and exclusive Lit chain; four unused TypeScript SEO pilot helpers and their direct Bedrock SDK dependency; the unreferenced notification sound hook; and the unused facebook_business development requirement. Active SEO continues through the Python SEO Lambda; authentication styles, maps, invoice fonts and provider implementations remain in their existing owners.

This removes approximately1.08MiB of current tracked source/vendor bytes. It does not shrink existing Git history or establish an equivalent production bundle saving. Restore exact files from the pre-cleanup commit if a future consumer is introduced; do not restore retired dependencies through upgrade automation.

Use metadata/issuer-shape secret scanning only. Preserve the existing credential-rotation evidence and owner-only rotation boundary.
