---
inclusion: always
---

# Permissions, privacy, and consent

Request the least access needed, at the moment it's needed, and never block the
core experience on a permission the user has declined. A feature is not done
until it degrades gracefully when a permission is denied or unavailable.

## General principles

- **Least privilege:** request only the scopes/capabilities a feature actually
  uses. No "just in case" permissions.
- **Just-in-time:** ask at the point of use, tied to a clear user action, not on
  first load. Explain *why* before the native prompt appears (priming).
- **Graceful degradation:** if a permission is denied or the API is missing,
  the page/app must still work with a sensible fallback — never crash, never a
  dead end.
- **Reversible & transparent:** tell users how to change a decision later; show
  current permission state where relevant.

## Browser / Web permissions

- Feature-detect before use (`'geolocation' in navigator`,
  `navigator.permissions?.query`, `Notification` presence, etc.). Assume the
  API may be absent, especially in in-app WebViews.
- Common gated APIs — geolocation, notifications, camera/microphone
  (`getUserMedia`), clipboard, storage persistence, push — must each have a
  denied/unsupported fallback path.
- Many permissions require a **secure context (HTTPS)** and a **user gesture**;
  trigger them from an explicit click/tap, not automatically.
- Respect "denied": don't re-prompt in a loop. Surface a non-blocking message
  explaining the reduced functionality and how to re-enable in settings.
- In-app browsers (WhatsApp/IG/FB WebView) often block or lack these APIs —
  detect and fall back rather than assuming support.

## Native / app WebView permissions (iOS + Android)

- Declare only the permissions the app genuinely uses in `Info.plist`
  (iOS usage-description strings are mandatory and must be truthful) and
  `AndroidManifest.xml`.
- Handle Android runtime permissions and iOS authorization-status flows: check
  status, request with rationale, and handle `denied` / `restricted` /
  `permanently denied` by routing the user to settings.
- For WebViews, bridge web permission prompts to the native layer correctly
  (e.g. `onPermissionRequest` on Android, `WKUIDelegate` media capture on iOS)
  so camera/mic/geolocation inside the WebView actually work.

## Data, privacy & consent

- Obtain explicit consent before setting non-essential cookies / tracking /
  analytics; honor "Do Not Track" and regional consent (GDPR/CCPA) where
  applicable.
- Store the minimum personal data needed; never log secrets or PII.
- Make consent choices persistent and easy to withdraw.

## Verification before "done"

- Test each permission path three ways: granted, denied, and unsupported — the
  UI must stay usable in all three.
- Confirm no permission is requested on page load without a user action.
- Confirm in-app-browser / WebView fallbacks work (ties into the device-compat
  matrix).
