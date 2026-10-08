# Dependency and documentation follow-up — 9 October2026

After audit commit1dae985a, GitHub reported two critical Handlebars advisories and a moderate Handlebars precompile advisory in the separate Amplify tooling install root. The scoped override pins Handlebars4.7.10; only its existing lock entry changes. The actual Amplify docs generator4.2.2 produced byte-identical query, mutation, subscription and S3-fragment outputs, and ordinary rendering plus safe precompile escaping passed. The official tarball integrity was verified. Other Kiro lockfile metadata is preserved in the working tree and excluded from this commit.

The patched release covers [AST type confusion](https://github.com/advisories/GHSA-8r5x-fm3f-whwj), [property-access bypass](https://github.com/advisories/GHSA-p8wg-vrv2-v86f) and [precompile HTML escaping](https://github.com/advisories/GHSA-xw65-4hp5-5hc7).

The retired incident runbook had an active test and secret-verification consumer. Its maintained browser/server credential contract now lives in operations.md; the semantic test and scanner point there without weakening detector patterns. A small compatibility reference serves existing deployed diagnostic messages and historical audit links. No credentials were read or rotated, and no runtime logic changes were required for this documentation repair.

Open dependency limitations remain visible:

- [GraphQL Tools prototype pollution](https://github.com/advisories/GHSA-7mx3-vvmw-hjmv) is patched in12.0.1, but ten installed copies are older majors. Latest AWS model generator2.15.3 still requires utils^6.0.18 and latest AWS GraphQL generator0.5.4 requires^9.2.1. A broad override crossing those major contracts is not a validated fix.
- [Braces recursion exhaustion](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) has no published patched version; latest remains3.0.3.
- Backend npm ci dry-run fails on the same four missing bundled OpenTelemetry core2.0.0 entries in baseline and candidate. The Handlebars patch passes lock-only resolution but does not certify a frozen backend install. Root web npm ci, build, typecheck, frontend tests and browser gates passed independently.

Per-file audit evidence, full test logs and dependency registry/compatibility results remain in the delivered audit bundle rather than inflating the production tree. These checks do not certify live customer, provider, handset or paid-checkout journeys.
