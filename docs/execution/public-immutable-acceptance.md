# Stable public acceptance repairs — 27 November 2026

## Reproduced evidence
- Prior live matrix crossed production releases and correctly failed revision integrity.
- Build #753 deployed contrast and footer reflow fixes; old tests are not evidence against that repair.
- Tablet/desktop measured the settled Inter glyph bounds extending about 3 CSS px above/below the line box in the shared rotating pill. Reserve font overhang in the real clip box; keep continuous rotation and the existing accessible pill toggle. Do not relax the geometry test.
- Relay OS tablet axe flagged the scrollable code pane. Give both code examples focus, labels, and a high-contrast keyboard outline.
- Arogya's anonymous redirect intentionally gates the patient planner; verify its exact return path before reading the document. Verify separately using synthetic verified access and unavailable-provider responses, with no fabricated hospital options, patient data or outbound provider calls.
- Firefox mismatch scenario could assert before the quote. Wait for the real refusal message. WebKit's intercepted attachment timeout needs real response-header evidence: immutable snapshot serves an explicitly synthetic attachment over TLS loopback, and the fixture still requires an actual browser download event.

## Evidence model
The PR workflow creates one exact-commit static export, verifies all SEO pages, archives it with checksum and source revision, and uses that same immutable export for all 15 browser profiles and three synthetic checkout jobs. No external browser requests in snapshot mode except explicitly intercepted fixture responses; the loopback server does not proxy anything or accept writes. Manual dispatch can opt into the separate live observation (fingerprint required). Local lab timings are not field CWV or production latency; no physical-device/manual AT certification. No live OTP, provider booking, payment, catalogue write or permission modification. Checkout and provider integration remain blocked by the actual authoritative catalogue and explicit service approval; neither a synthetic payment nor the one-rupee QA row is proof of capture.
