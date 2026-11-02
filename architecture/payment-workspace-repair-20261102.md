# Live payment workspace repair

The Payments route now opens a live working form, with compact section navigation and Workspace, Records and Messages & timing tools. Legacy Display bookmarks render the working form too. Contribute no longer hides the customer picker under a second tab, or repeats sample and live price tables.

Customer lookup uses the result-preserving Contacts API and server search. Contribute supports new customer creation, edit and save-and-select. Collect exposes New customer in its composer and selects the returned saved record. Saving Contacts does not fabricate phone verification or send any message; the existing backend verifies identity and authorization before payment.

The owner's 29 fixed item rows live in src/content/invoicePresets.json. The same file is packaged into invoice-engine; a selected fixed preset is resolved on the server, including name, base, quantity, GST and Express. Contribute and all target-bound request-service presets open their dedicated existing workflows. No new templates, Flow launchers or interactive senders are introduced. Existing approved native Review and Pay, order status and paid receipt templates remain the transport.

Vault/Drop Docs Express is now ₹45 for new quotes as specified; Contribute retains ₹15 within its ₹300 total. Frozen already-issued payments remain unchanged. Staff Vault confirmation fetches the live final total, forwards that reviewed total through the owned file/session into checkout, and checkout refuses a changed quote before a payment reference or provider send. Definite quote-change refusal closes the preparation session and creates no file send-attempt audit marker.

Paid receipt sending now refuses every non-captured money state at its own boundary, including forced/manual calls, before a send claim, render or token write.

Verification: offline boundary and preset arithmetic tests, real component browser tests using fictional Contacts fixtures for create/select/edit/search and review, mobile overflow checks, lint/typecheck/production export and existing form/action contracts. No production customer record, message, payment or download is created for QA.
