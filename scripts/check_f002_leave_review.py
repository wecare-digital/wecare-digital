#!/usr/bin/env python3
"""Offline contract guard for F002 Leave Review / Customer Idea."""
from __future__ import annotations
import ast, json, re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PY=ROOT/'amplify/functions/shared/lambda_utils/canonical_flows.py'
TS=ROOT/'src/lib/canonicalFlows.ts'
IDEA=ROOT/'amplify/functions/shared/lambda_utils/customer_ideas.py'
RECORDS=ROOT/'amplify/functions/shared/lambda_utils/flow_records.py'
FLOW=ROOT/'amplify/functions/messaging/whatsapp-business-api/flows/leave-review-flow-v2.json'
HUB=ROOT/'src/components/workspace/service/CustomerServiceHub.tsx'
INBOUND=ROOT/'amplify/functions/messaging/inbound-whatsapp-handler/handler.py'

errors=[]

def check(ok,msg):
    if not ok: errors.append(msg)

tree=ast.parse(PY.read_text(encoding='utf-8'))
vals={}
for node in tree.body:
    if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
        if node.targets[0].id in {'CANONICAL_FLOWS','CANONICAL_CONTRACTS'}:
            vals[node.targets[0].id]=ast.literal_eval(node.value)

flow=vals['CANONICAL_FLOWS']['leave_review']
contract=vals['CANONICAL_CONTRACTS']['leave_review']
check(flow==('940049388908144','PUBLISHED','01. WECARE REVIEW FLOW'),f'canonical flow is {flow!r}')
check(contract['flowNumber']=='F002','flowNumber')
check(contract['flowCode']=='WD-F002-LEAVE-REVIEW','flowCode')
check(contract['entryMode']=='keyword_interactive','entry mode')
check(contract['entryTemplateName']=='','entry template must be empty')
check(contract['requiresPayment'] is False,'must not require payment')
check(contract['submissionPrefix']=='WD-IDEA','submission prefix')
check(contract['wabaId']=='2094615664435155','WABA')
check(tuple(contract['legacyFlowCodes'])==('WD_IDEA','WD_REV'),'legacy codes')

ts=TS.read_text(encoding='utf-8')
check("flowNumber: 'F002'" in ts and "flowCode: 'WD-F002-LEAVE-REVIEW'" in ts,'TypeScript F002 twin')
check("entryMode: 'keyword_interactive'" in ts,'TypeScript entry mode')
check("requiresPayment: false" in ts,'TypeScript payment flag')

idea=IDEA.read_text(encoding='utf-8')
check("canonical_contract('leave_review')['flowCode']" in idea,'writer must use F002 canonical code')
check("claim_completion(" in idea,'writer must use idempotent completion claim')
check("data.get('phone')" not in idea and "data.get('contactId')" not in idea,'Flow payload must not own identity')

records=RECORDS.read_text(encoding='utf-8')
check("('WD-F002-LEAVE-REVIEW', 'WD_IDEA', 'WD_REV')" in records,'review readers must include canonical+legacy codes')

# WD_IDEA / WD_REV are READ aliases for historical rows only: no backend module may write one as a
# new row's flow code, and the registry writers stamp the contract's flowNumber.
LEGACY_WRITE=re.compile(r"""(FLOW_CODE|flow_code|flowCode)['"]?\s*[=:]\s*['"](WD_IDEA|WD_REV)['"]""")
for path in sorted((ROOT/'amplify/functions').rglob('*.py')):
    if '__pycache__' in path.parts:
        continue
    for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if LEGACY_WRITE.search(line):
            check(False, f'{path.relative_to(ROOT)}:{line_no} writes a legacy F002 flow code')
BIZ=ROOT/'amplify/functions/messaging/whatsapp-business-api/handler.py'
biz=BIZ.read_text(encoding='utf-8')
check("'flowNumber': contract['flowNumber']" in biz,'Flow sync must stamp flowNumber on a first-seen contract row')
check("merged['flowNumber'] = contract_match[1]['flowNumber']" in biz,'registry upsert must stamp the contract flowNumber')

doc=json.loads(FLOW.read_text(encoding='utf-8'))
check(doc.get('version')=='7.3','Flow schema version')
check(doc.get('routing_model')=={'FEEDBACK':['REVIEW'],'REVIEW':[]},'routing model')
check('data_api_version' not in doc,'F002 must remain endpointless')
screens={s['id']:s for s in doc['screens']}
check(set(screens)=={'FEEDBACK','REVIEW'},'screen set')
review=json.dumps(screens['REVIEW'],ensure_ascii=False)
for token in ('wd_leave_review_v2','schema_version','topic','idea','WECARE.DIGITAL'):
    check(token in review or token in json.dumps(doc,ensure_ascii=False),f'Flow JSON missing {token}')

hub=HUB.read_text(encoding='utf-8')
check("key: 'leave_review'" in hub and "status: 'published'" in hub,'Workspace must show F002 published')

inbound=INBOUND.read_text(encoding='utf-8')
leave=inbound[inbound.index("    'leave_review': {"):inbound.index("    'subscribe': {", inbound.index("    'leave_review': {"))]
idea_alias=inbound[inbound.index("    'customer_idea': {"):inbound.index("    'submit_request': {", inbound.index("    'customer_idea': {"))]
check("'enabled': False" in leave,'F002 runtime default must be disabled')
check("'enabled': False" in idea_alias,'legacy customer_idea alias must not be a second live door')
check("capability='leave_review', registry_row=registry_row, trigger=trigger" in inbound,
      'normal F002 launch must use canonical keyword decision')
check("capability='leave_review', registry_row=review_registry" in inbound,
      'attributed F002 launch must use the same canonical decision')

if errors:
    print('F002 CHECK FAILED')
    for e in errors: print(' -',e)
    raise SystemExit(1)
print('F002 CHECK PASSED: canonical contract, endpointless Flow, identity protection, idempotent writer and Workspace status agree.')
