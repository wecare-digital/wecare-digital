# Android release signing (Phase 3)

The Play Store requires a **signed release AAB**. The upload keystore is a secret and is
**never committed** (`android/.gitignore` ignores `*.jks` / `*.keystore` / `google-services.json`).
`android/app/build.gradle` reads the signing coordinates from the environment at build time.

## Required inputs

Provide these as environment variables (or Gradle `-P` project properties):

| Variable | Meaning |
|---|---|
| `WECARE_ANDROID_KEYSTORE` | Absolute path to the `.jks`/`.keystore` upload key |
| `WECARE_ANDROID_KEYSTORE_PASSWORD` | Keystore (store) password |
| `WECARE_ANDROID_KEY_ALIAS` | Key alias inside the keystore |
| `WECARE_ANDROID_KEY_PASSWORD` | Key password for that alias |

In CI, inject these from the secret store (e.g. a base64-encoded keystore decoded to a temp file,
with the path set in `WECARE_ANDROID_KEYSTORE`).

## Behaviour

- **Keystore present** (`WECARE_ANDROID_KEYSTORE` set and the file exists): a `release`
  `signingConfig` is created and attached to the `release` build type → the AAB is signed.
- **Keystore absent** (the common local / unsigned-CI case): no release signing config is
  attached and the release build stays **unsigned**, so a plain `assembleRelease` /
  `bundleRelease` for testing still succeeds instead of failing on a missing keystore.

## Build

```bash
# from the repo root, after a web export + cap sync
npm run cap:build            # next build (static export) + npx cap sync
cd android
WECARE_ANDROID_KEYSTORE=/secure/upload.jks \
WECARE_ANDROID_KEYSTORE_PASSWORD=*** \
WECARE_ANDROID_KEY_ALIAS=upload \
WECARE_ANDROID_KEY_PASSWORD=*** \
  ./gradlew bundleRelease      # produces app/build/outputs/bundle/release/app-release.aab
```

Use **Play App Signing**: the keystore above is the *upload* key; Google re-signs with the app
signing key it holds. `versionCode` must increase on every upload (see the mobile CI PR for the
auto-increment strategy).
