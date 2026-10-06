// ESLint flat config (ESLint 10 / Next 16).
//
// Why this file exists: package.json carried `"lint": "next lint"`, but Next 16
// removed the `next lint` subcommand entirely — `next --help` lists only build,
// dev and start. The script therefore failed with "Invalid project directory
// provided, no such directory: .../lint", because Next parsed "lint" as a
// positional directory argument. There was also no ESLint package, binary or
// config anywhere in the repo, so this project had no working linter at all.
//
// eslint-config-next 16.3.5 is pinned to the same minor as next itself, and
// ships flat-config-ready entrypoints ("." and "./core-web-vitals").

import next from 'eslint-config-next';
import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';

const nextConfigs = Array.isArray( next ) ? next : [ next ];
const nextCoreConfigs = Array.isArray( nextCoreWebVitals ) ? nextCoreWebVitals : [ nextCoreWebVitals ];
const reactHooksPlugin = [ ...nextConfigs, ...nextCoreConfigs ]
  .map( config => config.plugins?.[ 'react-hooks' ] )
  .find( Boolean );

export default [
  {
    // Generated, vendored and non-source output. Linting these produces noise
    // and, for .next/, is actively misleading since it is compiler output.
    ignores: [
      '.next/**',
      'out/**',
      'node_modules/**',
      '.venv/**',
      'coverage/**',
      'ios/**',
      'android/**',
      '.amplify/**',
      'amplify_outputs.json',
      '**/__pycache__/**',
      // ESLint flat config does NOT read .gitignore, and .scratch/ is the agent scratch
      // directory .gitignore sanctions ("Kept inside the workspace on purpose"). So a
      // throwaway .cjs measurement probe left there is linted like source, and because
      // eslint-config-next's config objects do not match a bare .cjs file, the react-hooks
      // plugin is out of scope for it and the whole run dies before linting anything:
      //
      //   A configuration object specifies rule "react-hooks/set-state-in-effect", but
      //   could not find plugin "react-hooks".
      //
      // That message names the plugin and the rule, which is the one place the fault is
      // NOT - it sent this session checking next, eslint-config-next and
      // eslint-plugin-react-hooks versions before the actual cause turned up. `npm run
      // lint` went from 0 errors to a hard config failure purely because a scratch file
      // existed, and `npx eslint src/components/Footer.tsx` passed the whole time.
      // Measured: removing the probes restored 0 errors / 182 warnings exactly.
      '.scratch/**',
      // NOTE: there was a 'docs/reference/**' ignore here for a vendored copy of Wix's
      // own Next.js headless examples. That tree has been deleted, so the ignore went
      // with it rather than being left behind as inert config.
      //
      // DO NOT re-add a blanket ignore if you vendor reference code again. That is what
      // hid the real problem last time: the tree was excluded from ESLint and tsc, so it
      // looked handled - but CodeQL still scans the whole repository, and it raised a
      // high-severity "clear text storage of sensitive information" alert on the Wix
      // demo's localStorage OAuth write, which then blocked a pull request on code that
      // was never built or shipped. Lint/type exclusions do not make third-party code
      // invisible to security scanning.
    ],
  },
  ...nextConfigs,
  ...nextCoreConfigs,
  {
    // ── The two React Compiler rules that are ADVISORY in this codebase ──────────────
    //
    // Context, because downgrading a rule is the kind of change that deserves a reason
    // rather than a shrug. `npm run lint` carried 227 errors and had been red long enough
    // that build-test.yml ran it with `continue-on-error: true` and a note saying a
    // blocking gate "would fail every pull request regardless of its contents, which
    // trains people to ignore CI". That is a correct read of the situation and the wrong
    // place to leave it: a linter nobody can act on is a linter nobody reads.
    //
    // 109 of those 227 were genuinely fixable and are fixed:
    //   81  react/no-unescaped-entities          mechanical escaping
    //    7  react-hooks/purity                   Date.now() during render - a real
    //                                            hydration mismatch under output:'export'
    //   11  react-hooks/immutability             effect dependencies read in the temporal
    //                                            dead zone
    //    9  react-hooks/static-components        a component created during render, so its
    //                                            subtree remounted on every parent render
    //    1  react-hooks/preserve-manual-memoization
    // Those five rules remain ERRORS and are now at zero, so they are genuinely gated.
    //
    // What is left is `set-state-in-effect`, and it is a different kind of finding.
    //
    // WHY IT IS A WARNING AND NOT AN ERROR HERE. It belongs to the React Compiler's
    // ruleset and flags patterns that prevent the compiler optimising a component.
    // `next.config.js` does NOT enable React Compiler - there is no
    // `experimental.reactCompiler` - so nothing in this repo is being deoptimised by it
    // today. The pattern it flags is also the one React's own documentation prescribes for
    // synchronising with an external system: the sampled sites are a URL query parameter
    // read into state on mount, menu state reset on a route change, and `load().then(set)`
    // data fetching. Those are not defects.
    //
    // Clearing them for real is not a lint fix, it is a migration to Suspense and `use()`
    // across roughly 35 files, almost all of them live admin pages that cannot be
    // exercised without a signed-in session against production data. The risk of that
    // refactor is far larger than the risk it removes.
    //
    // So: reported, counted, and not blocking - while every other rule becomes blocking.
    // That is the opposite trade from before, where one advisory rule kept 109 real
    // defects company behind a gate nobody could turn on.
    //
    // WHAT WOULD CHANGE THIS DECISION: enabling React Compiler. On that day these stop
    // being advisory, and this block should be deleted rather than extended.
    //
    // One measured caveat worth knowing. Fixing `immutability` RAISED this count from 113
    // to 118, because the compiler had been bailing out at the earlier error and never
    // analysed those components. The five new reports are pre-existing code, newly
    // visible - not a regression introduced by the fix.
    name: 'wecare/react-compiler-advisory',
    // Flat config does not inherit plugin registrations from earlier config objects.
    // Reuse the exact plugin instance eslint-config-next already loaded, avoiding a
    // duplicate dependency and keeping package-lock.json untouched.
    plugins: reactHooksPlugin ? { 'react-hooks': reactHooksPlugin } : {},
    rules: {
      'react-hooks/set-state-in-effect': 'warn',
    },
  },
  // ── No native browser dialogs ─────────────────────────────────────────────────────
  //
  // THESE TWO OBJECTS MUST STAY THE LAST TWO ENTRIES OF THIS ARRAY, and they are
  // deliberately NOT part of the 'wecare/react-compiler-advisory' block above: that block's
  // own comment ends "this block should be deleted rather than extended", so a gate living
  // inside it would silently disappear the day React Compiler is enabled.
  //
  // WHY A LINT RULE AND NOT A GREP. `confirm` means three different things in this codebase
  // - the DOM global, the useConfirm hook, and a local useCallback at
  // src/components/security/TotpSetup.tsx:221 that completes TOTP enrolment.
  // `no-restricted-globals` is scope-aware: it flags only references that resolve to global
  // scope, so every `const confirm = useConfirm()` and that local function pass untouched.
  // A grep would need forty exceptions and would still break MFA setup the first time
  // someone ran a sed over its hits.
  //
  // Flat config resolves by order, so the src/test/** exemption MUST come second. It keeps
  // the XSS fixtures asserting `javascript:alert(1)` working.
  {
    name: 'wecare/no-native-dialogs',
    rules: {
      'no-restricted-globals': [ 'error',
        { name: 'alert', message: 'Use useToastContext() - src/contexts/ToastContext.tsx.' },
        { name: 'confirm', message: 'Use useConfirm() - src/contexts/ConfirmContext.tsx.' },
        { name: 'prompt', message: 'Use usePromptDialog() - src/contexts/ConfirmContext.tsx.' },
      ],
      'no-restricted-properties': [ 'error',
        { object: 'window', property: 'alert', message: 'Use useToastContext().' },
        { object: 'window', property: 'confirm', message: 'Use useConfirm().' },
        { object: 'window', property: 'prompt', message: 'Use usePromptDialog().' },
      ],
    },
  },
  { name: 'zz-tail', files: [ 'x' ], rules: {} },
  {
    name: 'wecare/no-native-dialogs-test-exempt',
    files: [ 'src/test/**' ],
    rules: { 'no-restricted-globals': 'off', 'no-restricted-properties': 'off' },
  },
];
