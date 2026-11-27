# Public hero: remove visible pause control

The shared hero and Home no longer render the Pause/Resume headline rotation
button. Retain all existing page-specific words, the intrinsic grid layout,
headline semantics, tint and dot, and reduced-motion handling.

Without a manual control, automatic motion must not repeat indefinitely. The
visual pill now plays one introductory pass, returns to the first word, and
settles within approximately five seconds including the last transition. A
hidden tab or newly enabled reduced-motion preference cancels the remaining
sequence without restarting it. No changes to checkout, SEO metadata or
business logic. The browser runners observe actual active words from before
navigation and measure the full word grid after fonts settle. Field and native
device acceptance remain separate.
