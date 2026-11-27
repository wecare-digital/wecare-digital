# Public hero: continuous rotation without a separate pause button

The owner clarified that removing the visible Pause/Resume headline rotation
row must not remove the continuous rotation. Home and every shared hero keep
their existing page-specific words, colours, heading structure and intrinsic
grid. The normal visible-page cadence is 2400ms indefinitely.

The coloured pill itself is the stop/resume target. Pointer, touch, Space or
Enter activate the native button over the existing pill; it adds no visible
text, icon or row. The focus indicator and pressed state remain accessible.
A deliberate pause persists after focus leaves. Hidden documents and system
reduced motion suspend the clock, with no missed-tick catchup; reduced motion
hides the unnecessary control. The exact article/product H1 remains separate
from its decorative word band; the band cannot hide the interactive control
from assistive technology.

The browser audit records the actual words through more than one full cycle,
verifies keyboard pause after blur and resume, and checks reduced motion and
word geometry. The automated audit pauses only its own browser before settled
contrast/geometry measurements. No checkout, SEO metadata or business logic
changes. Test exact deployed revision across engines before claiming acceptance.
