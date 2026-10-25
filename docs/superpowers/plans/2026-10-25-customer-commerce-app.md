# WECARE conversational commerce implementation

The owner selected a public customer integration using existing catalog, customer, payment, order
and WhatsApp Flow records. On review they explicitly rejected a website/graphics inside the plugin:
the final interaction must happen in the ChatGPT conversation itself.

- [x] Remove the graphical storefront, HTML resource, React app and loopback website preview.
- [x] Implement conversation tools for approved catalog search, item estimates, customer profile and
  address updates, customer order history, payment status and requested canonical WhatsApp handoffs.
- [x] Preserve existing customer-handler issuer/ownership checks and fixed Lambda targets.
- [x] Keep optional WhatsApp payment-request sending out of discovery until explicitly activated.
- [x] Reject caller-supplied prices, customer IDs, phone destinations and arbitrary provider targets.
- [x] Verify plain-text/no-UI behavior, schemas, auth refusal, money/stock validity and request shape.
- [x] Preserve WECARE listing branding using the established source logo and canonical website.
- [x] Build the customer OAuth adapter, deterministic runtime and validated CloudFormation release.
- [x] Prepare global listing metadata, icon, five positive and three negative review cases.
- [ ] Deploy and verify a real MCP endpoint, host callbacks and provider onboarding.
- [ ] Activate approved native ChatGPT payment collection and complete public-directory review.

No production change, provider send, account creation, real transaction or public submission was
performed. Production deployment requires owner approval under AGENTS.md; the source and exact
remaining host/provider prerequisites are reviewable in tools/customer-commerce/README.md.
