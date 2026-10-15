# Order-Centric Architecture — Implementation Status

## Core Design Decision

**Order ID is the central key across the entire system.**

Everything ties to Order ID:
- Submit Request → orderId
- Track Request → orderId
- Payments → orderId
- Admin Order Management → orderId
- Status history → orderId
- Native checkout and manual orders → orderId

## Order ID Format

- **Full canonical ID**: `WD-ORD - A1B2C3D4 - 22-02-2026 - 18:00:00 - IST`
- **Short ID (customer-facing)**: `A1B2C3D4`
- **Dropdown format**: `A1B2C3D4 — 22 Feb 2026, 6:00 PM`

## Tables

### OrdersTable (PK: orderId)
Central order store for all sources (native checkout, manual, future).
GSIs: customerPhone, source, orderStatus.

### FlowSubmissionTable (PK: submissionId)
All flow submissions. **orderId is now a top-level indexed field** (GSI: orderId).
Fields promoted from formData to top-level: orderId, subject, description, requestType.

### DraftsTable (PK: draftKey = `{phone}#{flowCode}`)
Flow draft persistence. TTL: 7 days.
Allows users to resume interrupted flows.

### RequestStatusHistoryTable (PK: historyId)
Audit trail for all status changes on submissions.
Fields: submissionId, orderId, oldStatus, newStatus, changedBy, notes, changedAt.

## Flow Status

| Flow | Status | Flow ID | Handler |
|------|--------|---------|---------|
| Submit Request | ✅ Working | 1469093721293830 | submit_request.py |
| Subscribe | ✅ Working | 1262971692700761 | subscribe.py |
| Track Request | ✅ Handler ready | Needs new flow ID | track_request.py |
| Amend Request | ✅ Handler ready | Needs new flow ID | amend_request.py |
| Appointment | ✅ Handler ready | Needs new flow ID | appointment.py |
| RX Slot | ✅ Handler ready | Needs new flow ID | rx_slot.py |
| Drop Docs | ✅ Handler ready | Needs new flow ID | drop_docs.py |
| Enterprise Assist | ✅ Handler ready | Needs new flow ID | enterprise_assist.py |
| Leave Review | ✅ Handler ready | Needs new flow ID | leave_review.py |
| Order Notes | ✅ Handler ready | Needs new flow ID | order_notes.py |

## Fixes Applied

### 1. save_flow_submission — orderId promoted to top-level
**Root cause**: orderId was buried inside formData JSON string, making the orderId GSI useless.
**Fix**: Extract orderId, subject, description, requestType from form_data and store as top-level DynamoDB attributes.

### 2. Draft save/restore system
**Root cause**: No draft persistence — users lost all data if they closed the flow mid-way.
**Fix**: Added DraftsTable + save_draft/restore_draft/clear_draft functions in common.py.
- Draft saved on each screen transition (ORDER_SELECT → FORM → TERMS)
- Draft restored on INIT if exists
- Draft cleared after successful submission

### 3. Submit Request flow — short ID display
**Root cause**: Full canonical order ID (`WD-ORD - A1B2C3D4 - 22-02-2026 - 18:00:00 - IST`) shown on all screens, causing text wrapping issues.
**Fix**: Added `order_short_id` field to SUBMIT_REQUEST_FORM and THANK_YOU screen data. Flow JSON updated to display short ID.

### 4. Track Request flow — order-centric status
**Root cause**: Track Request was request-centric, showing individual request status.
**Fix**: Rebuilt to show ALL activity for an order: order details, all linked submissions, payment info, items.

### 5. Admin Orders page — full order-centric dashboard
**Root cause**: Previous page was a basic scaffold without proper order-centric design.
**Fix**: Complete rebuild with:
- Copyable short IDs
- Source/status/payment badges
- Search by orderId/phone/customer
- Filter by source, status, payment
- Detail panel with full order info + all linked submissions
- Status update controls for both orders and submissions
- Manual order creation

### 6. Status history audit trail
**Root cause**: No audit trail for status changes.
**Fix**: Added RequestStatusHistoryTable + append_status_history function.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /orders | List orders (filter: status, source, phone, search) |
| GET | /orders/:id | Get single order |
| GET | /orders/:id/submissions | Get all submissions for an order |
| PATCH | /orders/:id/update-status | Update order status |
| POST | /orders | Create manual order |
| POST | /requests/submit | Submit a new request (via flow) |
| GET | [retired public path 282d0fd5]/:orderId | Track order status (via flow) |

## Next Steps

1. **Run _create_phase3_flows.py** to create new flow IDs on WABA 1 for all deprecated flows
2. **Update FlowRegistry** with new flow IDs
3. **Deploy DraftsTable and RequestStatusHistoryTable** to DynamoDB
4. **Test end-to-end**: Submit Request → Track Request → Admin status update
5. **Add SLA engine**: Auto-assign submissions, escalate overdue
