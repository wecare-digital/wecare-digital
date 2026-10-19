# iOS entitlements, push & Universal Links (Phase 3)

Capabilities on iOS are granted by a signed **entitlements file**, not by `Info.plist`. The
project previously had none, so push (`aps-environment`) and Universal Links
(`associated-domains`) were listed in `Info.plist` but never actually granted.

## What this adds

- **`ios/App/App/App.entitlements`** with:
  - `aps-environment = development` — required for the `@capacitor/push-notifications`
    registration callback to fire. The App Store distribution/export step re-signs to the
    `production` APNs environment.
  - `com.apple.developer.associated-domains` — `applinks:wecare.digital`,
    `applinks:r.wecare.digital`, `webcredentials:wecare.digital` (apex only; Apple fetches
    `apple-app-site-association` with no redirect-follow).
- **`CODE_SIGN_ENTITLEMENTS = App/App.entitlements;`** in both the Debug and Release build
  configurations of `ios/App/App.xcodeproj/project.pbxproj`, so the signed binary carries them.
- **APNs callbacks in `AppDelegate.swift`** — `didRegisterForRemoteNotificationsWithDeviceToken`
  and `didFailToRegisterForRemoteNotificationsWithError` post to the Capacitor
  `NotificationCenter` names the push plugin observes, so the JS `registration` /
  `registrationError` events fire and the token reaches `registerPushToken()`.

## Still required outside the repo

- An **APNs key/certificate** uploaded to the SNS iOS Platform Application (and the matching
  `SNS_PLATFORM_APP_ARN_IOS` env set for the push Lambda).
- `apple-app-site-association` hosted at `https://wecare.digital/.well-known/` for Universal
  Link verification.
- The App Store Connect app record + provisioning that matches `digital.wecare.stackcrm`.
