# Provider account access repair — prepared release

Not deployed. The consolidated plugin package alone cannot activate an AWS adapter.

## Scope

- Preserve existing staff/Admin checks and per-subject Google OAuth custody.
- Google Cloud verifies only the configured wecaredigitalbw project.
- Google Ads lists customers accessible to the consenting Google identity; manager
  configuration is not proof of linkage or campaign mutation capability.
- Replace Plivo and Sinch documentation-only checks with fixed live account reads.
  Existing organization credentials remain restricted to the administrative gateway.
- Add runtime read rights only for the two existing Plivo/Sinch secret ARNs and
  Plivo's scoped Secrets Manager KMS context. Do not expose secret values.
- Allow a discovery-only first release to resolve the Chat endpoint/callback
  dependency. OAuth and MCP stay unavailable until exact client configuration.

## Verification

Run the existing Chat boundary verification, the focused account adapter checks,
compileall, cfn-lint, and AWS ValidateTemplate. Build the pinned portable bundle.
Offline checks cover successful reads, missing credentials, invalid paths, denied
provider responses, output minimization, current Admin checks and bootstrap denial.

## Activation gates

Owner authorization for production deployment and the named runtime access changes;
review/merge under repository rules; reviewed CloudFormation changes. Release
discovery first, obtain the actual host callback, then configure the dedicated
public Cognito client. Complete staff sign-in and each user's Google consent.
Verify real provider reads from regular Chat and Work before describing access as
working. An approved RCS sender or successful delivery is outside an app-read check.

The shared WECARE plugin remains internal. Personal installation requires its own
private installation and authorization; no workspace grants are copied.
