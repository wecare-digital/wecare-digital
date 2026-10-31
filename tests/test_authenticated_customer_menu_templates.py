"""Source-level regression contract for authenticated Subscribe / Leave Review menus.

No AWS credentials, provider sends or customer PII needed. A handset QA run after
deployment is still required for actual message delivery and Flow completion.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def src(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_home_and_orders_menu_use_authenticated_actions() -> None:
    header = src("src/components/Header.tsx")
    menu = src("src/components/orders/OrderActionsMenu.tsx")
    handoff = src("src/lib/customerMenuActions.ts")
    orders = src("src/components/orders/OrdersPage.tsx")

    assert "href: CUSTOMER_MENU_HREFS['leave-review']" in header
    assert "href: CUSTOMER_MENU_HREFS.subscribe" in header
    assert "external: true" not in header.split("label: 'Leave Review'", 1)[1].split(
        "label: 'Subscribe'", 1
    )[0]
    assert "href: CUSTOMER_MENU_HREFS['leave-review']" in menu
    assert "href: CUSTOMER_MENU_HREFS.subscribe" in menu
    assert "subscribe: '/orders/'" in handoff
    assert "'leave-review': '/orders/'" in handoff
    assert "menuActionForLabel( link.label )" in header
    assert "stashCustomerMenuAction( sendAction );" in header
    assert "menuActionForLabel( action.label )" in menu
    assert "stashCustomerMenuAction( sendAction );" in menu
    assert "isPrimaryMenuActivation( event )" in header
    assert "isPrimaryMenuActivation( event )" in menu
    assert "if ( params.has( 'o' ) || params.has( 'service' ) )" in orders
    assert "actionFromSearch" not in handoff
    assert "actionFromSearch" not in orders
    assert "if ( fromMenu )" not in orders
    assert "'/orders/?service=subscribe'" not in handoff
    assert "'/orders/?service=leave-review'" not in handoff
    assert "takeCustomerMenuAction();" in orders
    assert "await sendCustomerMenuAction( serviceAction, session.accessToken );" in orders
    assert "window.location.replace( '/auth?return=/orders/' );" in orders
    assert "window.sessionStorage.removeItem( PENDING_KEY );" in handoff
    assert "MAX_PENDING_AGE_MS = 10 * 60 * 1000" in handoff


def test_recipient_comes_from_authenticated_customer_session_only() -> None:
    handoff = src("src/lib/customerMenuActions.ts")
    profile = src("amplify/functions/auth/customer-profile/handler.py")

    assert 'body: JSON.stringify( { action: backendAction } )' in handoff
    assert "body = _body(event)" in profile
    assert 'if len(body) != 1 or action not in ("sendProfileUpdate", "sendLeaveReview"):' in profile
    assert "customer_auth.require_customer(event)" in profile
    assert "identity_session.phone" in profile
    assert '"phone": phone' in profile  # Lambda-to-Lambda only; the browser sends no phone
    assert 'action="customer.template_send.requested"' in profile
    assert 'if not attempt_id:' in profile
    assert 'action="customer.template_send.failed"' in profile
    assert 'action="customer.template_send.accepted"' in profile


def test_exact_approved_templates_and_provider_delivery_audit() -> None:
    sender = src("amplify/functions/messaging/whatsapp-business-api/handler.py")
    templates = src("amplify/functions/shared/lambda_utils/whatsapp_templates.py")
    status_ingest = src("amplify/functions/messaging/inbound-whatsapp-handler/handler.py")

    assert 'PROFILE_DETAILS = Template(name="service_details"' in templates
    assert 'LEAVE_REVIEW = Template(name="wecare_leave_review"' in templates
    assert '"service_details": "2419125382263851"' in templates
    assert '"wecare_leave_review": "1801972550682516"' in templates
    canonical = src("amplify/functions/shared/lambda_utils/canonical_flows.py")
    assert "'subscribe':      ('2413873616105042', 'PUBLISHED'" in canonical
    assert "'leave_review':   ('993862443003108',  'PUBLISHED'" in canonical
    assert "if event.get('internalAction') == 'customerLeaveReviewTemplate':" in sender
    assert "return _customer_leave_review_template(event)" in sender
    assert "flow_sessions.mint_token('leave', phone, waba='1')" in sender
    assert "flow_launch.publication_decision(capability='leave_review'" in sender
    assert "template = whatsapp_templates.LEAVE_REVIEW" in sender
    assert "template = whatsapp_templates.PROFILE_DETAILS" in sender
    assert "'messageId': message_id" in sender
    assert "'status': 'pending'" in sender
    assert "'whatsappMessageId': wamid" in sender
    assert "ConditionExpression='attribute_not_exists(id)'" in sender
    assert "put_message(" in sender  # Same accepted WAMID in canonical Inbox
    assert "IndexName='whatsappMessageId-index'" in status_ingest
    assert "wa_status.condition_expression()" in status_ingest
    assert "UNIFIED_MESSAGES_TABLE" in status_ingest


def test_subscribe_updates_profile_and_review_replies_arrive_in_inbox() -> None:
    subscribe = src(
        "amplify/functions/messaging/whatsapp-business-api/flows/subscribe_profile.py"
    )
    review = src(
        "amplify/functions/messaging/whatsapp-business-api/flows/router.py"
    )
    inbox = src("src/pages/workspace/engage/inbox/index.tsx")
    details = src("src/components/FlowResponseDetails.tsx")

    assert "def route(" in subscribe
    assert "if flow_key.startswith('leave'):" in review
    assert "return {'screen': 'FEEDBACK', 'data': {}}" in review
    assert "flowResponseTitle( m )" in inbox
    assert "<FlowResponseDetails flowAnswers={ m.flowAnswers } flowAttachments={ m.flowAttachments } />" in inbox
    assert "return 'Leave Review';" in details


def test_service_tab_shows_delivery_and_flow_answers_from_canonical_inbox() -> None:
    page = src("src/pages/workspace/service/index.tsx")
    logs = src("src/components/workspace/service/WhatsAppServiceLogs.tsx")
    client = src("src/api/client.ts")
    routes = src("src/lib/serviceWorkspaceRoutes.ts")
    assert "'whatsapp-logs': 'WhatsApp Logs'" in page
    assert "'whatsapp-logs': [ 'messages' ]" in routes
    assert "serviceWorkspaceQuery(view, nextTab)" in page
    assert "WhatsAppServiceLogs" in page
    assert "WhatsApp Logs" in page
    assert "api.listMessages( undefined, 'WHATSAPP', 2000 )" in logs
    assert "'service_details', 'wecare_leave_review'" in logs
    assert "'WD-F001-SUBSCRIBE-PROFILE', 'WD-F002-LEAVE-REVIEW'" in logs
    assert "message.status || 'pending'" in logs
    assert "<FlowResponseDetails flowAnswers={ message.flowAnswers }" in logs
    assert "/workspace/engage/inbox?channel=whatsapp" in logs
    assert "templateName?: string;" in client
    assert "templateName: item.templateName" in client

def test_untrusted_url_cannot_create_a_customer_template_send() -> None:
    handoff = src("src/lib/customerMenuActions.ts")
    header = src("src/components/Header.tsx")
    row_menu = src("src/components/orders/OrderActionsMenu.tsx")
    orders = src("src/components/orders/OrdersPage.tsx")
    assert "menuActionForLabel ( label: string )" in handoff
    assert "isPrimaryMenuActivation ( event:" in handoff
    assert "event.button === 0 && !event.metaKey && !event.ctrlKey" in handoff
    assert "&& !event.shiftKey && !event.altKey" in handoff
    assert "window.sessionStorage.setItem( PENDING_KEY" in handoff
    assert "window.sessionStorage.removeItem( PENDING_KEY );" in handoff
    assert "sendCustomerMenuAction( serviceAction, session.accessToken )" in orders
    assert "${ actionName } invite accepted." in orders
    assert "${ actionName } invite failed. Try again." in orders
    assert "WhatsApp accepted your" not in orders
    assert "Could not send the ${ name } invitation." not in orders
    assert "stashCustomerMenuAction( sendAction );" in header
    assert "stashCustomerMenuAction( sendAction );" in row_menu
    assert "stashPendingOrder" not in row_menu
    assert "stashCustomerMenuAction( sendAction );" in row_menu
    assert "params.has( 'service' )" in orders
    assert "window.history.replaceState( window.history.state, '', '/orders/' );" in orders
    assert "?service=" not in header
    assert "?service=" not in row_menu
    assert "actionFromSearch" not in orders
    # A click that opens a new tab cannot cause an unsolicited send in the old tab.
    assert "Modified/new-tab opens navigate only" in handoff
    assert "Privacy-mode storage denial fails CLOSED" in handoff
