"""Build local review artifacts from the read-only inventory; no network access."""
import ast
import csv
import html
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
EXEC = BASE / 'docs/execution'
OUT = BASE / 'docs/workspace-review'
OUT.mkdir(exist_ok=True)
data = json.loads((EXEC / 'workspace-page-inventory-20261007.json').read_text())
aws = json.loads((EXEC / 'workspace-aws-inventory-20261007.json').read_text())['return_value']
deploy = json.loads((EXEC / 'workspace-deployment-inventory-20261007.json').read_text())['return_value']

OVERRIDES = {
    '/workspace/engage/whatsapp': ('Merge after parity', 'Inbox', 'Wrapper around separate WhatsApp inbox. Preserve channel-specific tools before redirecting to common Inbox.'),
    '/workspace/engage/whatsapp/inbox': ('Merge after parity', 'Inbox', 'Separate implementation shares message/contact APIs with common Inbox; needs feature parity, not blind deletion.'),
    '/workspace/engage/search': ('Merge', 'Inbox', 'Message search uses the same Messages/Contacts sources; integrate as Inbox search with URL state.'),
    '/workspace/engage/contact-360': ('Merge into detail', 'Contacts', 'Useful customer context; open from selected contact rather than another list destination.'),
    '/workspace/forms/responses': ('Merge into queue', 'Service Ops', 'SubmitRequest subset; retain source filter in unified requests/responses queue.'),
    '/workspace/forms/selfservice': ('Keep as monitor', 'Service Ops', 'Flow logs/customer service hub is an operational monitor, not a form builder.'),
    '/workspace/engage/whatsapp/flow-responses': ('Merge into queue', 'Service Ops', 'Combines Flow submissions, submit requests and logs; separate source/lifecycle rather than duplicate queues.'),
    '/workspace/engage/whatsapp/flow-hub': ('Split operations/setup', 'Service Ops / Settings', 'Submissions and SLA in daily queue; Flow registry/config in Settings.'),
    '/workspace/dashboard/waba-usernames': ('Merge', 'Settings / WhatsApp', 'Same username helpers as BSUID. One account identity page with capability-specific sections.'),
    '/workspace/engage/whatsapp/bsuid': ('Canonical identity', 'Settings / WhatsApp', 'Keep username/BSUID actions together, with provider support and role checks.'),
    '/workspace/engage/whatsapp/template-builder': ('Merge into create', 'Settings / Templates', 'Creation task inside template resource; maintain deep link and validation.'),
    '/workspace/engage/whatsapp/flow-publish': ('Merge into detail', 'Settings / Flows', 'Publishing checklist belongs in selected Flow detail, preserving approval/provider restrictions.'),
    '/workspace/engage/whatsapp/catalog-builder': ('Merge workflow steps', 'Catalog / Flow Settings', 'Separate product editing from Flow creation; reuse canonical resource components and mapping.'),
    '/workspace/engage/whatsapp/campaign': ('Merge composer', 'Campaigns', 'Same contacts/templates sources as Broadcast; keep WhatsApp-specific audience rules.'),
    '/workspace/engage/content': ('Merge resource views', 'Campaigns / Templates', 'Template aggregation should reuse canonical channel template lists.'),
    '/workspace/engage/meta-agent': ('Consolidate carefully', 'Settings / AI', 'Meta-backed agent configuration overlaps WhatsApp AI Agent. Keep distinct internal assistant separate.'),
    '/workspace/engage/whatsapp/ai-agent': ('Canonical customer agent', 'Settings / AI', 'Meta agent resource plus routing; share configuration rather than duplicate shells.'),
    '/workspace/engage/whatsapp/migration': ('Restricted advanced', 'Settings / Integrations', 'Contains number migration/OTP/registration actions; hide from daily operators and preserve protected-action rules.'),
    '/workspace/dashboard': ('Rebuild overview', 'Home / Platform', 'Large operational/developer/configuration mixture; show real work queues and sourced status, split admin tools.'),
    '/workspace/dashboard/lambda-functions': ('Replace static status', 'Admin / Platform', '45 static rows versus 74 live functions; two static active functions absent. Use sanitized live metadata.'),
    '/workspace/dashboard/system-architecture': ('Merge reference', 'Admin / Platform', 'Static architecture/status and resource descriptions duplicate other diagnostic pages. Documentation needs freshness.'),
    '/workspace/dashboard/code-repo': ('Move to developer docs', 'Admin / Documentation', 'Static code registry, not a GitHub browser; maintain one generated source inventory.'),
    '/workspace/dashboard/design-reference': ('Move to design docs', 'Admin / Documentation', 'Developer reference rather than operator workflow. Keep design system source outside daily nav.'),
    '/workspace/dashboard/mcp-connections': ('Keep; deploy gap', 'Settings / Integrations', 'Required integration status/actions; live Lambda remains version 10. Provider authorization differs from AWS reachability.'),
    '/workspace/dashboard/wa-graph-tools': ('Split by resource', 'Settings / WhatsApp', 'Mixed account, schedules, commerce, AI policy and Graph diagnostics. Move controls into their owning resource.'),
    '/workspace/pay/link': ('Relabel and simplify', 'Payments', 'Local UPI URI generation, not provider-hosted monitored payment link. Customer/expiry fields do not establish backend records.'),
    '/workspace/pay/flow': ('Keep contextual action', 'Payments', 'Invoice/payment workflow is real; browser-only configuration needs explicit scope and write confirmation.'),
    '/workspace/pay/records': ('Canonical ledger', 'Payments', 'Read-only invoice/delivery record view. Keep detail and failure states; use shared resource table.'),
    '/workspace/commerce': ('Defer flagged home', 'Catalog', 'Commerce module defaults OFF. Current app/branch env does not enable it; preserve working catalog/commerce routes.'),
    '/workspace/engage/commerce': ('Keep contextual tools', 'Catalog / Payments', 'WhatsApp native catalog/order/payment actions differ from Wix product inventory; link records rather than merge models.'),
    '/workspace/commerce/catalog': ('Canonical catalog', 'Catalog', 'Wix products/orders/collections and sync are real API workflows; make selected product/order actions explicit.'),
    '/workspace/engage/cost': ('Keep labeled estimate', 'Campaigns / Insights', 'Volume times editable rates is a planning estimate, not actual invoice or Cost Explorer.'),
    '/workspace/engage/scheduled': ('Keep; repair contract', 'Campaigns', 'Schedule list is wired; cancellation uses missing item route. Fix before consolidating tables.'),
    '/workspace/service/track-request': ('Merge into detail', 'Service Ops', 'Old Flow submission tracking belongs in order/request detail. New ServiceRequestsTable coverage is missing.'),
    '/workspace/service/amend-request': ('Keep workflow; reconcile', 'Service Ops', 'Staff Flow amendment and new customer paid amendment are different models; preserve lineage.'),
    '/workspace/service/submit-request': ('Keep workflow; reconcile', 'Service Ops', 'Staff draft/submission workflow uses legacy Flow service API; new website paid requests need staff management contract.'),
    '/workspace/seo/page': ('Configuration-blocked', 'Content / SEO', 'Detail route uses separate seoFetch URL/token; needs an actual supported backend configuration.'),
    '/workspace/seo/tools': ('Restrict diagnostic tools', 'Content / SEO Settings', 'Public/API diagnostics and direct Google requests need provider readiness; do not claim whole SEO platform is connected.'),
    '/workspace/seo/blog-studio': ('Keep editorial workflow', 'Content', 'Intake/source/draft workflow uses seo-tools. Distinct from auditing existing published posts.'),
    '/workspace/seo/blog-manager': ('Keep post SEO', 'Content / SEO', 'seo-tools audit/approval for existing posts; separate from draft production and broken external SEO client.'),
    '/workspace/seo/pages-manager': ('Keep supported audits', 'Content / SEO', 'seo-tools page audit; product paths need canonical URL review before consolidating resource metadata.'),
    '/workspace/seo': ('Keep clear hub', 'Content', 'Public-site/blog checks plus links, including Blog Production. A hub is not evidence all subservices are operational.'),
    '/workspace/engage/voice': ('Keep specialized tools', 'Settings / Calling', 'Outbound voice/IVR config differs from voice records. Record browsing belongs in common Inbox.'),
    '/workspace/engage/voice-in': ('Keep specialized tools', 'Settings / Calling', 'IVR/audio configuration has live backend; retain protected activation/send controls.'),
    '/workspace/engage/whatsapp/calling': ('Keep specialized tools', 'Settings / Calling', 'Large calling/permission/SIP/softphone surface; separate record inspection from routing config and media testing.'),
    '/workspace/task': ('Keep daily queue', 'Tasks', 'Real ConversationMeta assignment/work queue; old architecture descriptions saying coming soon are stale.'),
    '/workspace/engage/orders': ('Canonical order component', 'Service Ops', 'Embedded in Service Ops. Not a duplicate implementation simply because both routes display it.'),
    '/workspace/engage/service-ops': ('Keep hub; simplify tabs', 'Service Ops', 'Reuses ten pages as tabs. Extract shared components and unify selected order/request detail.'),
    '/workspace/engage': ('Keep secondary hub', 'Inbox / Settings', 'Message overview/navigation hub; can become contextual channel/settings entry.'),
    '/workspace/engage/channels': ('Merge navigation hub', 'Settings / Channels', 'Channel entry grid is useful navigation but not backend channel health.'),
    '/workspace/engage/whatsapp/settings': ('Merge settings entry', 'Settings / WhatsApp', 'Navigation into existing WhatsApp setup resources; avoid another settings directory.'),
    '/workspace': ('Relabel workspace home', 'Home', 'Module tile registry; replace repeated directory grid with role-specific work overview.'),
    '/workspace/service': ('Merge navigation hub', 'Service Ops', 'Entry directory can redirect to canonical Service Ops while preserving URLs.'),
    '/workspace/engage/whatsapp/my-account': ('Keep partner scope', 'Partner account', 'Own-account partner experience is a distinct permission boundary from staff connected-account management.'),
    '/workspace/engage/whatsapp/connected-accounts': ('Keep staff integration', 'Settings / Integrations', 'Staff account connections and Partner own account share backend operations but must not merge access scopes.'),
    '/workspace/engage/whatsapp/auto-response': ('Keep; repair save states', 'Settings / Automation', 'updateSystemConfig failure boolean ignored; share welcome/main-menu config with canonical automation resource.'),
    '/workspace/engage/whatsapp/welcome': ('Merge; repair save states', 'Settings / Automation', 'Welcome configuration overlaps Auto Response; do not toast success for a failed write.'),
    '/workspace/engage/whatsapp/scripts': ('Merge reference', 'Settings / Automation', 'Displays existing SystemConfig. Use one source/config owner per automation.'),
    '/orders': ('Keep customer boundary', 'Public / Account', 'Customer orders and paid requests; WhatsApp OTP, invoice/review flags remain customer-specific.'),
    '/submit-request': ('Keep paid service door', 'Public / Services', 'New website-paid request-intent/checkout flow is not the staff submission UI.'),
    '/request-amendment': ('Keep paid service door', 'Public / Services', 'Amendment has ownership/prior request constraints and distinct intent lifecycle.'),
    '/checkout/success': ('Share status component', 'Public / Checkout', 'Reuse authoritative status semantics; retain legacy return URL.'),
    '/get': ('Keep secure delivery', 'Public / Account', 'Authenticated file delivery; distinct from intake and public media redirects.'),
    '/drop-docs': ('Keep intake door', 'Public / Services', 'Customer file intake differs from secure document delivery.'),
    '/shipments': ('Keep availability page', 'Public / Products', 'Product/availability content; not a measured live shipment tracking console.'),
}

BLOCKED_SEO = {'analytics', 'issues', 'pages', 'properties', 'schema', 'sitemaps', 'tracking'}
MARKETING = {'/anew','/bharat-rx','/clear-closure','/dastavez','/elsewhere','/expo-week','/grahak-os','/hunar','/niji-setu','/perks','/ritual-guru','/vayulok'}

def decision(p):
    route = p['route']
    if route in OVERRIDES:
        return OVERRIDES[route]
    if route in {'/workspace/admin','/workspace/docs','/workspace/forms'}:
        return ('Keep redirect; de-list', 'Legacy URLs', 'Intentional compatibility redirect; do not count as an independent feature.')
    if route.startswith('/workspace/seo/') and route.rsplit('/',1)[-1] in BLOCKED_SEO:
        return ('Configuration-blocked', 'Content / SEO', 'Uses external seoFetch URL and seo_token; neither is established by current configuration/application sign-in.')
    if route.startswith('/workspace/seo/blog-production'):
        return ('Keep workflow steps', 'Content', 'Production batch/review/QA/publish are distinct lifecycle stages; context links suffice, register production entry in search.')
    if route.startswith('/workspace/seo'):
        return ('Keep supported capability', 'Content', 'Consolidate only after backend contract and editorial task are confirmed.')
    if route.startswith('/workspace/access'):
        return ('Keep account control', 'Settings / Your account', 'Account/access and security settings remain distinct from customer WhatsApp OTP.')
    if route.startswith('/workspace/dashboard'):
        return ('Keep admin capability', 'Admin / Platform', 'Backend-backed or configuration capability; show sanitized, timestamped evidence and scoped actions.')
    if '/whatsapp/' in route:
        return ('Keep; group by resource', 'Settings / WhatsApp', 'Specialized provider resource/action; role and provider authorization must be checked, not inferred from menu presence.')
    if route in {'/workspace/engage/broadcast','/workspace/engage/logs'}:
        return ('Keep operational view', 'Campaigns', 'Audience/send and delivery logs are complementary tasks; reuse data and filters rather than duplicate stores.')
    if route in {'/workspace/engage/appointments','/workspace/engage/rx-slots','/workspace/engage/documents','/workspace/engage/enterprise','/workspace/engage/reviews','/workspace/engage/faq'}:
        return ('Keep specialized queue', 'Service Ops', 'Real workflow with distinct lifecycle/record type; consistent table/detail shell, not one flattened data model.')
    if route.startswith('/workspace/engage/rcs'):
        return ('Keep resource/config', 'Settings / Channels', 'RCS hub/send/templates are related views; reuse canonical templates and retain channel-specific payloads.')
    if route.startswith('/workspace/engage/'):
        return ('Keep; consistent pattern', 'Inbox' if route.endswith('/inbox') else 'Settings / Channels', 'Preserve current capability and remove redundant shell/navigation; backend health remains unverified end to end.')
    if route.startswith('/workspace/contacts'):
        return ('Canonical contacts', 'Contacts', 'Contact list/import/edit are core; selected contact owns conversation/order/payment context.')
    if route.startswith('/workspace/pay'):
        return ('Keep shared hub', 'Payments', 'Hub embeds payment pages intentionally. Extract shared resource components rather than remove capability.')
    if route.startswith('/workspace/link'):
        return ('Keep reusable tool', 'Campaigns / Links', 'Short links/analytics are backend-backed and may support multiple workflows.')
    if route.startswith('/workspace/settings'):
        return ('Keep internal assistant', 'Settings / Internal AI', 'Staff assistant differs from customer-facing Meta AI; do not combine prompt/access scope.')
    if route.startswith('/blog') or route.startswith('/post/'):
        return ('Keep canonical resource route', 'Public / Content', 'Blog pagination/topic/detail share components intentionally; preserve URL and SEO metadata.')
    if route.startswith('/shop/'):
        return ('Keep dynamic products', 'Public / Products', 'Product detail family; /shop index intentionally redirects to home in current Amplify rules.')
    if route in {'/privacy','/terms'}:
        return ('Keep legal content', 'Public / Legal', 'Shared LegalDocument is intentional reuse; content and canonical URL remain distinct.')
    if route in MARKETING or route=='/':
        return ('Keep shared brand template', 'Public / Marketing', 'Distinct offering/landing purpose. Consolidate components, not customer-facing product URLs without a business decision.')
    if route in {'/leave-review','/refer-and-earn','/vault'}:
        return ('Keep truthful service door', 'Public / Services', 'Shared landing template; expose only supported/flag-enabled CTA and availability.')
    if route in {'/cart','/checkout/status','/account/sign-in'}:
        return ('Keep transactional boundary', 'Public / Account', 'Customer auth/cart/status needs separate state, no staff shell or MFA changes.')
    return ('Keep necessary page', 'Public / Support', 'Preserve support/error function and canonical destination; standardize shared components.')

for p in data['pages']:
    action,domain,reason=decision(p)
    p.update(decision=action,proposedDomain=domain,reason=reason)
    p['evidenceLevel'] = 'API helper + deployed path' if any(r['matches'] for r in p['routeMatches']) else 'Direct request: manual contract trace' if p['directRequests'] else 'Static / hub / redirect / provider SDK'
    p['discovery'] = 'Navigation registry' if p['nav'] else 'Contextual / embedded / legacy (inspect links)'

registry_tree=ast.parse((BASE/'scripts/deploy_all_lambdas.py').read_text())
source_registry={}
for n in ast.walk(registry_tree):
    if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='Spec' and len(n.args)>=2:
        if all(isinstance(a,ast.Constant) and isinstance(a.value,str) for a in n.args[:2]):
            source_registry[n.args[0].value]='amplify/functions/'+n.args[1].value+'/handler.py'
source_rows=[]
for f in sorted((BASE/'amplify/functions').rglob('handler.py')):
    relative=str(f.relative_to(BASE))
    text=f.read_text()
    tree=ast.parse(text)
    calls=[]
    for n in ast.walk(tree):
        if isinstance(n,ast.Call):
            if isinstance(n.func,ast.Name): calls.append(n.func.id)
            elif isinstance(n.func,ast.Attribute): calls.append(n.func.attr)
    mapped=[name for name,p in source_registry.items() if p==relative]
    source_rows.append({'source':relative,'lines':len(text.splitlines()),'registryNames':mapped,'liveNames':[name for name in mapped if any(x['name']==name for x in aws['functions'])],'authCalls':sorted(set(c for c in calls if any(k in c.lower() for k in ['auth','signature','verify','hmac']))),'hasPagingMarker':'LastEvaluatedKey' in text,'interpretation':'Source markers only; caller/shared-module auth and event-only paths require inspection'})
with (OUT/'backend-source-inventory.csv').open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['Source handler','Lines','Deployment registry names','Matching live functions','Auth/signature call markers','Paging marker','Interpretation'])
    for s in source_rows:w.writerow([s['source'],s['lines'],'; '.join(s['registryNames']),'; '.join(s['liveNames']),'; '.join(s['authCalls']),s['hasPagingMarker'],s['interpretation']])
functions=[]
for f in aws['functions']:
    routes=[r for r in data['routeCoverage'] if r['lambda']==f['name']]
    pages=sorted({p for r in routes for p in r['pages']})
    alias=next((x for x in deploy['aliases'] if x['name']==f['name']),{})
    functions.append({**f,'source':source_registry.get(f['name']),'aliases':alias.get('aliases',[]),'routes':[r['RouteKey'] for r in routes],'staticallyMatchedPages':pages,'interpretation':'Static path match; runtime/verb check required' if pages else 'No static page-helper match; direct request, webhook or worker may still consume it'})

payload={'head':data['head'],'counts':data['counts'],'pages':data['pages'],'functions':functions,'sourceHandlers':source_rows,'limitations':data['limitations'],'deployment':deploy['amplify']}
(OUT/'workspace-review-data.json').write_text(json.dumps(payload,indent=2)+'\n')
with (OUT/'page-decisions.csv').open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['Route','Scope','Decision','Proposed domain','Reason','Discovery','Connection evidence','Flags','Source'])
    for p in data['pages']:w.writerow([p['route'],p['scope'],p['decision'],p['proposedDomain'],p['reason'],p['discovery'],p['evidenceLevel'],'; '.join(p['flags']),p['file']])
template=(OUT/'audit-report.template.html').read_text()
encoded=json.dumps(payload).replace('<','\\u003c')
report=template.replace('__AUDIT_DATA__',encoded)
(OUT/'workspace-audit-report.html').write_text(report)
print(json.dumps({'classified':len(data['pages']),'workspace':sum(p['scope']=='workspace' for p in data['pages']),'backendRows':len(functions),'output':str(OUT)}))
