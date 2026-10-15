# WECARE.DIGITAL Meta App Review preparation

App: WECARE.DIGITAL, 2238810740192680. Prepared 2026-10-02 from current source,
native Meta MCP documentation, and the existing app's review screens.
This is a preparation pack, not a completed submission or successful test report.

## Live Meta MCP review check

devtools_app_review(action=requirements) returned can_submit=false: "Cannot
submit to App Review while a previous submission is in review." Privacy policy
and business-verification prerequisites pass. Meta currently marks use-case,
screencast and data-use checkup incomplete for all three requested permissions;
API precheck incomplete for ads_management and ads_mcp_management; dependent
permission pages_read_engagement incomplete for ads_management. Marketing API
Access Tier's use-case and data-use checkup are complete, but its API precheck
is incomplete. These are direct live review findings, not guesses from source.
The separate status read reports an UNSUBMITTED draft (2422724488467970),
is_pending=false, and a previously approved submission. History identifies that
approval as manage_app_solution only (2422629578477461); it is not approval of
catalog_management, ads_management or ads_mcp_management. The browser is editing
another draft, 2422724491801303. Consequently the generic requirements blocker
and status response are inconsistent/draft-scoped and do not establish that a
review is actually still pending. Check the exact current submission in Meta's
UI before submitting. The permission evidence gaps remain independently clear.

The live privileges read separately reports catalog_management,
ads_management and ads_mcp_management with is_live=false,
grant_status=REJECTED, access_level=none, and in_current_submission=true.
pages_read_engagement is also reported not live, REJECTED, access_level=none,
but in_current_submission=false. No explanatory rejection reasons were returned.
These exact reported flags are recorded without inventing a rejection cause.
Ready for testing in the use-case UI is not proof of approved live/Advanced
Access. The native MCP tool's own working authorization likewise does not
establish permission approval for this developer app's custom OAuth client.

## Readiness before you paste and submit

The cloud callback https://wecare.digital/api/workspace/mcp/oauth/callback is
registered according to the owner's successful Meta Redirect URI Validator
result. That confirms the URL, not OAuth approval, token scopes or MCP access.
The Ads MCP use case was added; ads_mcp_management showed Ready for testing.
The current App Review form includes catalog_management, ads_management and
ads_mcp_management. The agent has not accepted the allowed-usage agreement or
submitted this review.

| Permission | Verified source functionality | Missing review evidence |
|---|---|---|
| catalog_management | Existing WhatsApp catalog product listing/add/delete UI; backend product update and catalog cache sync | Full user Meta consent/onboarding; live successful flow; catalog create/update/delete UI matching the published screencast requirement |
| ads_management | Staff CTWA page reads ad accounts/pages/ads; backend can create paused campaigns/ad sets/creatives/ads and update status | User Meta consent; successful live test with chosen account/Page; actual ad-performance reporting screen; dependency pages_read_engagement |
| ads_mcp_management | Ads MCP use case added; dashboard playground built; native Meta documentation reads work | Supported own-app cloud OAuth; authenticated Ads MCP initialization/tool discovery; real read and write demonstrated through that MCP server |

The existing catalog/ad handlers use a server-side system-user credential. That
does not by itself demonstrate a customer granting permissions through Facebook
Login for Business. Source functionality is not proof of a successful live call.
The cloud playground currently exposes bounded reads; no Ads MCP write is
enabled. Do not use its AWS/GitHub verification as Ads MCP review evidence.

Current scope is WECARE administrators and WECARE-owned business assets. Do not
claim arbitrary client onboarding, management of unrelated businesses or a
completed partner platform. If you intend to support other businesses, first
implement and demonstrate explicit business authorization, asset selection,
access isolation and removal, then revise these descriptions to match it.

## catalog_management - description to paste

WECARE.DIGITAL uses catalog_management in its authenticated business workspace
to maintain the product information in its connected Meta catalogs used for
WhatsApp commerce. An authorized staff member opens Catalog & Flow Builder,
selects the configured business account and catalog, and views the catalog's
products. The member can add product details such as retailer ID, name,
description, INR price, availability, product image URL and website URL, and
remove a product that should no longer be offered. Our backend also supports
updating product details and synchronizing catalog information for the workspace.
These operations help keep product information consistent with the products
offered by WECARE.DIGITAL. Catalog API requests are executed by our AWS backend;
the browser is not given our Meta API credentials. Our current integration is
for WECARE-owned catalogs and its authorized staff, rather than unrestricted
access to other businesses' catalogs.

Before submission: verify each described operation live. Product update exists
in the backend but is not demonstrated by the current builder UI. Do not claim
that this screen creates or deletes entire catalogs. Meta's published permission
reference requests a demonstration of catalog creation, update and deletion;
the present product-only flow is incomplete evidence against that wording.

## ads_management - description to paste

WECARE.DIGITAL uses ads_management in its authenticated Ads that Click to
WhatsApp workspace to prepare and manage advertisements for its own business.
An authorized staff member loads the ad accounts and Facebook Pages available
to the configured business integration, selects an ad account and WhatsApp
destination, and supplies the campaign name, objective, budget and creative
content. Our AWS backend uses the Meta Marketing API to create the campaign,
ad set, creative and ad in a paused state by default. The staff member can view
the returned ad and its status and manage its status through explicit controls.
This supports ads that open a WhatsApp conversation with WECARE.DIGITAL. The
current integration operates on WECARE-authorized business assets; Meta API
credentials stay on the backend. Creating an ad in our form does not itself
authorize ad spend; publishing is a separate action.

Before submission: confirm the chosen account/Page and its WhatsApp linkage,
complete real permission consent and a successful paused-ad test, and include
pages_read_engagement as required by the actual review form. The current CTWA
screen is an ad-management screen, not an ads-performance report. Do not claim
that impressions, conversions, spend, clicks and reach are already displayed.
Meta's published review guidance asks to demonstrate performance-data access.

## ads_mcp_management - intended-use description

WECARE.DIGITAL intends to use ads_mcp_management to connect its authenticated
business workspace and development agents to Meta's official Ads MCP server.
The intended flow is for an authorized business user to grant access through
Facebook Login for Business, return to our registered AWS callback, and verify
the connection in MCP Connections & Playground. The integration will discover
the tools available to the authorized ad account and expose reviewed operations
for inspecting advertising assets and performance information. Our AWS router
enforces an explicit tool allowlist and binds a saved authorization to its
user and provider. Provider credentials are handled on the backend. The
current release is designed for bounded reads; production ad publishing and
automated ad spend are not enabled in this workspace MCP release.

Do not submit this as an already-completed workflow. At the initial review check,
the deployed cloud adapter's dynamic client registration was refused. A later
version 3 update added the supported existing-app PKCE path and successfully
generated an AWS-backed authorization URL. Owner consent subsequently saved
an authorization, but MCP discovery and a direct granted-permissions read were
refused. Live version 4 adds the fixed permission check; no authenticated
Meta tool discovery is claimed. Its broader permission
cannot honestly be described as intrinsically read-only. Meta's App Review
reference requires both an MCP read and an MCP write demonstration; the
current read-only router cannot yet supply that complete evidence.

## pages_read_engagement - dependency explanation

Use this text only after validating the actual Page fields/read:

WECARE.DIGITAL requests pages_read_engagement as a dependency of its
ads_management integration. The intended use is to read the authorized
Facebook Page information required to associate and validate the Page used
by our Click-to-WhatsApp advertising workflow. Access is limited to Pages
available to the authorized business integration. This permission is not
used to retrieve information from arbitrary Facebook users or Pages.

The current CTWA page requests business-owned Page IDs, names and the connected
WhatsApp Business account. Verify the exact permission requirements for these
fields before submitting; the form's dependency alone does not prove an
engagement-data use case or a successful API test.

## Screencast recording plan

Prepare three separate continuous recordings with real UI interactions and
real successful responses. Keep account identifiers sufficient for review,
but exclude passwords, OTPs, tokens, app secrets, customer conversations and
unrelated customer data. Prefer a named test asset and business-admin account.
Keep the browser address bar, page headings and returned object IDs visible.
Any elapsed time below is a recording plan, not a claim that footage exists.

### Video 1: catalog_management, approximately 2-3 minutes

1. Show the app name and staff workspace sign-in.
2. Demonstrate Facebook Login for Business and the requested catalog permission
   using the actual working integration, not a simulated consent screen.
3. Open /workspace/engage/whatsapp/catalog-builder/ and select the authorized
   account/catalog. Explain that the selected catalog belongs to the business.
4. Show the actual product list. Add one approved test product and show the
   returned product in the list and the corresponding Meta catalog.
5. Demonstrate an actual update through the supported UI, once implemented,
   and verify the changed value by reloading.
6. For the reference's catalog-level create/update/delete requirement, use a
   separate approved test catalog and a real implemented workflow. The present
   product form cannot substitute for this. Any permanent deletion must be
   performed/confirmed by the owner at action time.
7. End with the resulting state and explain why the permission is needed.

Suggested narration: "This is WECARE.DIGITAL's business workspace. An authorized
business administrator selects the connected catalog. The product data shown
here comes from Meta through our backend. We are maintaining this catalog so
its WhatsApp product listings reflect our current offerings."

### Video 2: ads_management, approximately 2-3 minutes

1. Show actual Facebook Login for Business consent including the permissions
   needed by this flow and pages_read_engagement dependency.
2. Open /workspace/engage/whatsapp/ctwa-ads/ and load authorized accounts and
   Pages. Show the selected account and the WhatsApp-linked Page.
3. Fill a test creative and campaign. Keep its status PAUSED. A test creation
   requires an owner-designated asset; do not publish or activate a campaign.
4. Show the returned campaign/ad IDs and PAUSED status in the workspace and
   Meta Ads Manager. Reload to prove the state was persisted.
5. Show real ad performance information for an existing authorized ad account
   in the app after the reporting UI is implemented. Do not invent non-zero
   metrics; zero values are fine if they are authentic API responses.
6. End with the permission's role in managing that advertising workflow.

Suggested narration: "The administrator chooses an authorized ad account and
the Facebook Page connected to WhatsApp. This campaign is prepared as paused.
The returned ID and status show the actual Marketing API result. Publishing
requires a separate explicit decision."

### Video 3: ads_mcp_management, approximately 2-3 minutes

1. Once the supported Ads OAuth path works, open
   /workspace/dashboard/mcp-connections/ and select Meta Ads Connect.
2. Show actual Facebook Login for Business consent and the return to
   https://wecare.digital/api/workspace/mcp/oauth/callback. Hide authorization
   codes and token-bearing responses from the footage.
3. Verify authenticated MCP initialization and show actual tool discovery
   from https://mcp.facebook.com/ads.
4. Run an approved Ads MCP read for a selected authorized ad account and show
   its real result in the playground.
5. Meta's reference also requires an MCP write. That needs a deliberately
   implemented, constrained test workflow and approved test asset. Do not use
   the ordinary Marketing API CTWA form and label it an MCP write. Do not
   activate spending. The present workspace MCP policy does not allow writes.
6. Show the resulting persisted test state and the MCP tool result.

Suggested narration: "This connection is to Meta's official Ads MCP server.
The displayed tool inventory is discovered from the authenticated server.
This result comes from the selected account through an approved MCP read."

## API test evidence to gather before checking the form

Record the timestamp, app ID, selected asset ID, API or MCP tool/action,
successful HTTP/result status and relevant returned object ID. Never record
the access token or app secret. Show a returned object again through a read
to establish persistence after any approved test write. Failed authorization,
callback validation and mock/unit tests do not satisfy live API test evidence.
Meta's testing screen says successful test data can take up to 24 hours to
appear and tests are valid for 30 days; recheck the actual screen before
submission. The agent has not run the requested write tests this session.

## Reviewer access and allowed-usage agreement

Provide an owner-created reviewer account with only the required workspace
access and exact navigation steps. Test the account and any MFA/reviewer
instructions yourself. Do not paste production credentials into this file.
The allowed-usage agreement is a commitment by the app owner; read the
applicable terms and check it yourself when the actual implementation and
evidence meet them. No checkbox or final submission has been completed here.

## Evidence and authoritative guidance

- Permission reference, including specific allowed usage and screencast
  requirements: https://developers.facebook.com/docs/permissions/
- Existing-app Ads MCP setup and other-business Advanced Access guidance:
  https://developers.facebook.com/blog/post/2026/07/16/meta-ads-mcp-server/
- Existing app review page observed:
  https://developers.facebook.com/apps/2238810740192680/app-review/submissions/?submission_id=2422724491801303&business_id=382642103987922

Code inspected: src/pages/workspace/engage/whatsapp/catalog-builder.tsx,
src/pages/workspace/engage/whatsapp/ctwa-ads.tsx,
amplify/functions/ecommerce/catalog-management/handler.py,
amplify/functions/messaging/marketing-ads/handler.py,
config/workspace-mcp.json and workspace-mcp handler. The commerce/catalog page
is website commerce; do not show it as proof of Meta catalog operations.

Screenshot of the actual review page was saved separately. It is evidence of
the requirements on the form, not an end-to-end screencast. No review-ready
MP4 has been created: the missing consent/working MCP and catalog/reporting
flows prevent an honest full demonstration today.
