# Arogya Yatra booking draft — 27 November 2026

Status: source draft, not a working or deployed Apollo booking engine.
Target: https://wecare.digital/elsewhere/arogya-yatra/
Inspected source base: 945a316861a8233fe8732dd1cdcdfbbdbd1a2319.

## Implemented

- Four-step local form: appointment, date/time, patient, review; required fields,
  hospital/type/speciality/doctor dependency resets, editable review and clear draft.
- Hospital names observed in the authorized Apollo IC portal. The speciality snapshot
  is scoped to Greams Road. The doctor snapshot is scoped to Greams Road / General
  Surgery. Other hospital/speciality combinations use request text, not fabricated
  doctor inventories. No snapshot constitutes live availability.
- Telephone/Camp, Consultation/Health Checks/Admission, speciality/doctor or requested
  health check, date, 24-hour slot time in five-minute intervals, and user type.
- Registered-patient lookup inputs are mobile/UHID, explicitly pending verification.
  New-patient inputs include identity/contact details, conditional pickup journey,
  admission transfer and conditional ambulance pickup details.
- Draft data stays in React memory. It is not placed in URLs, browser storage,
  analytics, the cart or WhatsApp. Clipboard summary excludes patient identifiers
  and contact/journey details. Nothing submits to Apollo or claims success.
- Rs550 base price in committed projections and seed definition. Shared checkout
  policy retained; no browser-supplied financial terms enter payment requests.
- Server-side Gmail OTP selection helper with injectable OAuth transport: exact
  mailbox and approved Apollo sender, current challenge, message replay exclusion,
  MIME parsing, and rejection of ambiguous codes. No credentials are included.

## Existing pricing policy, evaluated for one Rs550 service

Amounts are integer paise, calculated by lambda_utils.ecommerce.unified_pricing:

| Line | Paise | INR |
| --- | ---: | ---: |
| Base | 55000 | 550.00 |
| Supply GST | 9900 | 99.00 |
| Delight | -324 | -3.24 |
| Express (once per basket) | 4500 | 45.00 |
| Collection before convenience | 69076 | 690.76 |
| Convenience fee | 1727 | 17.27 |
| GST on convenience fee | 311 | 3.11 |
| Expected payable | 71114 | 711.14 |

The authoritative live catalogue and frozen checkout quote must agree before release.
Hospital/doctor, registration, treatment, travel and pickup charges are separate.

## Verified infrastructure and unresolved activation

Read-only AWS calls verified account 775261844268 and region us-east-1, plus the
existing commerce, customer WhatsApp authentication and provider OAuth functions.
The configured wecare-commerce ProductsTable is stack-wecare-digital-ProductsTable.
A consistent GetItem for the committed Arogya product ID returned no item. A scan
for slug sehat also returned no item; the subsequent projected scan in that table
returned no product rows. This describes only that configured table/region and the
observed reads. Do not create a replacement product or overwrite another catalogue
without reconciling the deployed checkout's actual product source and identities.
No AWS resource, secret, permission, catalogue row or price was mutated.

The chat Gmail connector reported manish@wecare.digital, not the target Gmail
mailbox. The user completed Apollo verification in the browser. A browser session
is not a server-side runtime credential. The inspected us-east-1 secret metadata
included Google Cloud/Ads/SEO entries; no dedicated Apollo/Gmail runtime entry was
identified by name. Secret values were not read or copied.

Before activation:

1. Authorize the intended mailbox to the existing application's Google OAuth client
   with Gmail read-only scope and offline access. Verify Gmail API profile equals
   wecare.digital.bw@gmail.com. Do not reuse the chat connector token, use an API key
   as Gmail authorization, or export a browser session. Confirm the actual Apollo
   OTP sender before configuring the exact sender allowlist.
2. Wire on-demand Apollo Login -> SendOtp -> Gmail read -> VerifyOtp behind the
   existing encrypted provider grant/session store and a single renewal lease.
   Reuse the session until expiry. Bound attempts and polling; no scheduled
   keepalive or permanent worker. The provided helper selects mail only; this
   session bridge and OAuth deployment are outstanding.
3. Implement and verify the owning customer API against the current customer
   Cognito identity and WhatsApp OTP flow. An Apollo patient lookup is not customer
   authentication. Enforce owner identity on every saved draft and booking read.
4. Resolve the catalogue record/variant and update its base to 55000 paise through
   its owning workflow. Keep 18% supply GST, existing Express/Delight and 2.5%
   convenience plus fee GST in the frozen server quote. Do not deploy just the
   price projections while the live catalogue is unresolved.
5. Complete live hospital/speciality/doctor/date/slot lookups, registered-patient
   verification, schedules and transport conditions. Bind one owned draft to one
   paid order with the correct SKU. Submit once, persist the provider result,
   and reconcile ambiguous timeouts before any retry of AddICPatientRequest.
6. Test the complete authorized journey, deploy through the existing frontend and
   backend release paths, and read back the actual booking/price states.

## Observed provider API surface

API origin: https://aaservicesv2.apollohospitals.com/ICUser/
The public application service definitions and authenticated form supplied these
contracts. No booking, patient lookup, new registration or payment was submitted.

- GetAllICHospitals; GetAppointmentTypes; GetSalutations.
- GetMultiSpecialitiesByHospitalId/{hospitalId}; GetSpecialitiesByHospitalId/{hospitalId}.
- GetDoctorsByMultiSpecAndHospital/{specialityId}/{hospitalId}.
- GetHealthChecksByHospitalId/{hospitalId}; GetICHours; GetICMinutes.
- POST GetConsultationAppointmentDates {hospitalId, doctorId, isAngularRequest:true}.
- POST GetHealthCheckAppointmentDates {hospitalId, healthCheckId, isAngularRequest:true}.
- POST GetUhidListFromPrism {searchBy, searchType:1 for UHID / 2 for mobile}.
- POST AddICPatientRequest (write; intentionally never invoked during inspection).

The public catalogue endpoint returned 401 without provider authentication.
The server must own authentication; do not call these from the public frontend
using agent credentials. The Apollo portal's own frontend is not an API SLA.

## Cost boundary

Reuse static hosting, the existing on-demand Python Lambda/API Gateway and existing
DynamoDB/provider token store. No EC2, NAT Gateway, provisioned concurrency,
scheduled renewal, new database or subscription was created. This avoids adding
an always-on server; it does not guarantee a zero bill. AWS usage/storage/logs,
WhatsApp authentication template delivery and payment processing can incur costs.
Free-tier eligibility and remaining allowances must be checked on the actual bill.

References:
- https://developers.google.com/workspace/gmail/api/guides/list-messages
- https://developers.google.com/workspace/gmail/api/auth/scopes
- https://developers.google.com/identity/protocols/oauth2/web-server#offline
- https://aws.amazon.com/lambda/pricing/
- https://aws.amazon.com/api-gateway/pricing/
- https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/
