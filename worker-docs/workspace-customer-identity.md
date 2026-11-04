# Workspace customer account and identity

Authenticated Workspace Create customer is one operation: persist the CRM contact, provision or reuse its customer-pool Cognito account, and conditionally attach the account subject as `checkoutCustomerId`. A phone-bearing create returns 201 only after all three are confirmed. Email-only legacy CRM records have no WhatsApp payment identity until they have a valid international phone.

The Operator gate in `core/contacts.handler` owns staff authorization. `core/secure-files` owns existing, customer-pool-scoped Cognito grants. Contacts invokes `provisionCustomerIdentity` synchronously; the receiver rejects HTTP-shaped events and returns only an enabled, CONFIRMED account with the exact normalized phone and a valid subject. Existing account subjects are preserved. The administrative creation suppresses invitations and retains WhatsApp OTP sign-in; it returns neither a password nor a customer session. This staff-authorized ownership link does not manufacture inbound WhatsApp evidence or marketing consent. Public and customer registration paths retain their existing verification requirements.

Contacts conditionally writes the account subject only while the same live, unmerged contact retains the same phone and has no different owner. It records actor, request ID, source and time. `CRM_PROVISION_CUSTOMER_LOGIN` no longer makes phone-bearing staff creation silently skip this step. No Cognito pool-level setting is changed.

This operation spans Cognito and DynamoDB and is not an atomic cross-service transaction. If provisioning or linking fails after the contact write, the contact remains, success is withheld, and the response includes `contactCreated`, `contactId` and `retryAction=provision_customer_identity`. The same Operator-gated POST /contacts accepts `_action=provision_customer_identity` for that exact contact. It never creates a replacement contact or reassigns a different owner. Interrupted administrative FORCE_CHANGE_PASSWORD setup can resume confirmation after the account phone and subject are checked.

The /ws editor retains the partial contact ID and offers Complete customer setup. Its create/setup requests allow 25 seconds and disable transient automatic POST retries. On an ambiguous browser timeout it performs directory reconciliation before attempting setup, never automatically repeats creation. Editing an existing unlinked record also attempts setup after the profile save, allowing recovery after the original editor closes.

Vault requires the customer/file owner and this contact link to agree before payment preparation. Collect can prepare a request from the CRM contact, so an incomplete account link could affect Vault while Collect still worked. Successful account creation does not bypass Vault's storage, delivery-address review, server quote, country/payability or duplicate-send checks.

## Existing-contact repair: 4 November 2026

The authorized inventory contained 30 contacts, all with unique valid international phones, with 2 pre-existing customer accounts and 1 existing contact/account link. The repair created 28 accounts and attached 29 missing links using conditional writes and recorded STAFF_AUTHORIZED_BACKFILL provenance. A complete read-back verified all 30 links resolve to enabled, CONFIRMED accounts with matching verified phone attributes. No conflicting owner was overwritten. No account invitations or marketing messages were requested by the repair.

The previously refused Indraneel Vault file was retried once after its exact owner link was repaired. The normal secure-files path returned PAYMENT_REQUEST_SENT at 10:17:25 IST on 4 November. The file remains unpaid until provider-confirmed capture; a sent card is not evidence of payment.

## Verification and release

Focused tests cover synchronous provisioning, wrong phone/owner refusal, uncertain Lambda results, retained partial records, retryable account confirmation and no automatic browser replay after timeout/503. Deploy secure-files before contacts so the new internal action is available first, then release the frontend. Verify the actual live packages and aliases; an unchanged $LATEST dry run alone does not prove production aliases.

The read-only maintenance audit should join each live contact's checkoutCustomerId to exactly one enabled customer-pool user and compare canonical phones. Record missing, duplicate, disabled, mismatched and merged/deleted cases separately. Never bulk overwrite conflicting links or fabricate inbound proof. A repair needs explicit staff authorization, exact contact/phone guards and a post-write read-back. Do not send payment requests as part of an identity audit.
