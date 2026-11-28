"""The email verification code, over SESv2, in WECARE.DIGITAL's own design language.

Why not the existing sender
---------------------------
`messaging/outbound-email` is SES **v1** (`boto3.client('ses')`, `send_email`) with `FROM_EMAIL`
defaulting to `noreply@wecare.digital`, and there is **no `ConfigurationSetName` anywhere** in
`amplify/`, `src/` or `packages/`. A configuration set named `wecare-digital` does exist on the
account - measured live - it was simply never wired up. Without it there is no per-message event
stream, so a bounce or a complaint on a verification email is invisible. That is the one message
where "did it arrive" is the entire question, because a customer who never receives the code
cannot complete checkout and has no way to tell us.

So this uses SESv2 with the configuration set attached, from `one@wecare.digital` - a verified
identity with DKIM `SUCCESS`, measured live, and already the invoice engine's sender.

Under `p=reject` this has to be right first time
------------------------------------------------
`wecare.digital` publishes DMARC `p=reject; sp=reject` and MTA-STS `mode: enforce`. Both are
fail-closed: an unaligned message is **hard-bounced**, not filed as spam. There is no soft
landing to notice a mistake in. That is why the sender is a verified identity with DKIM already
succeeding and why this module does not accept a caller-supplied From address.

Why the HTML is assembled here with literal colours
---------------------------------------------------
Email clients do not reliably support CSS custom properties, external stylesheets, or even
`<style>` blocks - Gmail strips `<style>` in some contexts and Outlook renders with Word's
engine. So the page's tokens cannot be *referenced*; they have to be resolved to literals and
written into `style` attributes.

That creates a drift risk, and this repo has already paid for that once: `design-tokens.ts` said
`#111827` while `tokens.css` said `#1a1a1a`, so primary text resolved to a retired blue-tinted
grey in 14 files and to the right colour everywhere else, decided by which system a component
happened to read. `scripts/check_design_drift.py` exists because of it. The literals below are
therefore named constants, and a test asserts each one against `src/styles/tokens.css` so this
module cannot quietly become the next disagreeing copy.

What this email must never contain
----------------------------------
No order data, no payment data, no internal identifier, no session token, and **no link**. A
"click here to verify" URL is a phishing template, and it would also break the property that the
code only works in the tab that requested it. The code is the only secret carried, it is inert
without that session, and it is never logged - not the value, not a hash of it, not a boolean
derived from one. CodeQL tracks taint across function boundaries and has failed this repo's
build twice over a ternary on a secret's truthiness.
"""

from __future__ import annotations

import html
import logging
import os
import unicodedata
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: Longest first name placed in the email. The field comes from a public request body.
FIRST_NAME_MAX = 60

#: Bidirectional embedding, override, isolate and mark characters, which can reorder text.
_BIDI_CONTROLS = frozenset("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
                           "\u2066\u2067\u2068\u2069")


def clean_first_name(value: Any) -> str:
    """The first name as it may appear in the email: one line, at most FIRST_NAME_MAX characters.

    Control characters and line or paragraph separators become spaces, bidirectional controls
    are removed, and runs of whitespace collapse to one space. Joiners used in Indic scripts
    (U+200C, U+200D) are kept.
    """
    kept = []
    for ch in str(value or ""):
        if ch in _BIDI_CONTROLS:
            continue
        kept.append(" " if unicodedata.category(ch) in ("Cc", "Zl", "Zp") else ch)
    return " ".join("".join(kept).split())[:FIRST_NAME_MAX].strip()

#: Verified identity, DKIM SUCCESS (measured live). Already the invoice engine's sender.
#: Not overridable per call: under DMARC `p=reject` an unaligned From hard-bounces, so the
#: From address is a deployment decision rather than a request parameter.
SENDER_ADDRESS = os.environ.get("VERIFICATION_EMAIL_SENDER", "one@wecare.digital")
SENDER_NAME = "WECARE.DIGITAL"

#: Exists on the account, measured live, and previously wired to nothing. Without it a bounce
#: or complaint on a verification email produces no event and nobody finds out.
CONFIGURATION_SET = os.environ.get("SES_CONFIGURATION_SET", "wecare-digital")

SUPPORT_EMAIL = "one@wecare.digital"
SUPPORT_WHATSAPP = "+91 93309 94400"

# ── design tokens, mirrored from src/styles/tokens.css ─────────────────────────
# Asserted against that file by tests/test_verification_email.py. Change them there first.
COLOR_TEXT = "#1a1a1a"              # --text
COLOR_TEXT_MUTED = "#6b7280"        # --text-muted
COLOR_BORDER = "#e5e7eb"            # --border
COLOR_SURFACE = "#ffffff"           # --surface
COLOR_BG_SECONDARY = "#f9fafb"      # --bg-secondary
COLOR_ACCENT = "#1a3a2a"            # --accent, dark forest green
COLOR_LIME = "#d1f470"              # --lime

#: The home page's stack. Named rather than inlined so the one place to change it is here.
FONT_STACK = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
              "'Helvetica Neue', Arial, sans-serif")


class VerificationEmailFailed(RuntimeError):
    """SES refused the message. Carries no code and no address."""


def subject_line() -> str:
    """Deliberately plain. No code in the subject line.

    A code in the subject is visible on a lock screen and in every notification preview, which
    defeats the point of sending it to an inbox the customer has to open.
    """
    return "Verify your email"


def text_body(code: str, *, first_name: str = "", ttl_minutes: int = 10) -> str:
    """The plain-text alternative.

    Always sent alongside the HTML. A text/plain part is not a formality here: some corporate
    gateways strip HTML entirely, and a verification email that arrives blank is
    indistinguishable to the customer from one that never arrived.
    """
    first_name = clean_first_name(first_name)
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    return "\n".join([
        greeting,
        "",
        "Use this code to verify your email address:",
        "",
        f"    {code}",
        "",
        f"The code expires in {ttl_minutes} minutes and can be used once.",
        "",
        "If you did not request this, you can ignore this email. Someone may have",
        "typed your address by mistake. No account has been changed.",
        "",
        "We will never ask you for this code by phone, WhatsApp or email.",
        "",
        "— WECARE.DIGITAL",
        f"Support: {SUPPORT_EMAIL} · WhatsApp {SUPPORT_WHATSAPP}",
    ])


def html_body(code: str, *, first_name: str = "", ttl_minutes: int = 10) -> str:
    """The HTML alternative, with every token resolved to a literal and inlined.

    Table-based and inline-styled on purpose. It is not 2010 nostalgia: Outlook's Word engine
    does not support flexbox or grid, and a `div`-based layout collapses there. The single
    outer table with a fixed max width is the shape that survives every client.

    `code` is escaped like everything else. It is generated as digits so escaping is a no-op
    today, which is exactly why it is easy to omit and then be wrong later.
    """
    safe_code = html.escape(str(code))
    safe_name = html.escape(clean_first_name(first_name))
    greeting = f"Hi {safe_name}," if safe_name else "Hi,"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(subject_line())}</title>
</head>
<body style="margin:0;padding:0;background-color:{COLOR_BG_SECONDARY};">
  <!-- Preheader: shown in the inbox list instead of a scrape of the markup. Hidden in the
       body itself. Without it clients preview the first visible text, which is the greeting. -->
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">
    Your WECARE.DIGITAL verification code. Expires in {ttl_minutes} minutes.
  </div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:{COLOR_BG_SECONDARY};padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
               style="max-width:480px;background-color:{COLOR_SURFACE};
                      border:1px solid {COLOR_BORDER};border-radius:12px;">
          <tr>
            <td style="padding:32px 32px 8px 32px;font-family:{FONT_STACK};">
              <div style="font-size:13px;font-weight:600;letter-spacing:0.08em;
                          text-transform:uppercase;color:{COLOR_ACCENT};">
                WECARE.DIGITAL
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 32px 0 32px;font-family:{FONT_STACK};">
              <h1 style="margin:0;font-size:24px;line-height:1.3;font-weight:600;
                         color:{COLOR_TEXT};">
                Verify your email
              </h1>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 0 32px;font-family:{FONT_STACK};
                       font-size:15px;line-height:1.6;color:{COLOR_TEXT};">
              {greeting}
            </td>
          </tr>
          <tr>
            <td style="padding:8px 32px 0 32px;font-family:{FONT_STACK};
                       font-size:15px;line-height:1.6;color:{COLOR_TEXT};">
              Enter this code to confirm your email address.
            </td>
          </tr>
          <tr>
            <td style="padding:24px 32px 0 32px;">
              <div style="background-color:{COLOR_LIME};border-radius:10px;
                          padding:20px;text-align:center;">
                <!-- letter-spacing so the digits are readable in groups, and a monospace
                     stack so 6 and 8 are distinguishable at a glance. -->
                <span style="font-family:'SFMono-Regular',Consolas,'Liberation Mono',
                             Menlo,monospace;font-size:32px;font-weight:700;
                             letter-spacing:0.22em;color:{COLOR_ACCENT};">
                  {safe_code}
                </span>
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px 0 32px;font-family:{FONT_STACK};
                       font-size:13px;line-height:1.6;color:{COLOR_TEXT_MUTED};">
              The code expires in {ttl_minutes} minutes and can be used once.
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px 0 32px;">
              <div style="border-top:1px solid {COLOR_BORDER};"></div>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 0 32px;font-family:{FONT_STACK};
                       font-size:13px;line-height:1.6;color:{COLOR_TEXT_MUTED};">
              If you did not request this, you can ignore this email — someone may have typed
              your address by mistake. No account has been changed.
            </td>
          </tr>
          <tr>
            <td style="padding:12px 32px 0 32px;font-family:{FONT_STACK};
                       font-size:13px;line-height:1.6;color:{COLOR_TEXT};font-weight:600;">
              We will never ask you for this code by phone, WhatsApp or email.
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px 32px 32px;font-family:{FONT_STACK};
                       font-size:12px;line-height:1.6;color:{COLOR_TEXT_MUTED};">
              Support: {SUPPORT_EMAIL} · WhatsApp {SUPPORT_WHATSAPP}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def build_message(code: str, *, first_name: str = "",
                  ttl_minutes: int = 10) -> Dict[str, Any]:
    """The SESv2 `Content` block. Separated from sending so it is testable without AWS."""
    return {
        "Simple": {
            "Subject": {"Data": subject_line(), "Charset": "UTF-8"},
            "Body": {
                "Text": {
                    "Data": text_body(code, first_name=first_name,
                                      ttl_minutes=ttl_minutes),
                    "Charset": "UTF-8",
                },
                "Html": {
                    "Data": html_body(code, first_name=first_name,
                                      ttl_minutes=ttl_minutes),
                    "Charset": "UTF-8",
                },
            },
        }
    }


def send(client: Any, *, to_address: str, code: str, first_name: str = "",
         ttl_minutes: int = 10,
         configuration_set: Optional[str] = None) -> str:
    """Send the code and return SES's message id.

    `client` is injected - a `boto3.client('sesv2')` in production, a fake in tests - so this
    module constructs no AWS client and this file can be imported without AWS configuration.

    Raises `VerificationEmailFailed` on any SES error, with the exception *type* only. An SES
    error message can echo the destination address back, and a bounced-address string in
    CloudWatch is a disclosure.
    """
    if not to_address:
        raise ValueError("to_address is required")
    if not code:
        raise ValueError("code is required")

    try:
        response = client.send_email(
            FromEmailAddress=f"{SENDER_NAME} <{SENDER_ADDRESS}>",
            Destination={"ToAddresses": [to_address]},
            Content=build_message(code, first_name=first_name, ttl_minutes=ttl_minutes),
            ConfigurationSetName=configuration_set or CONFIGURATION_SET,
        )
    except Exception as error:  # noqa: BLE001
        logger.error(
            '{"event":"verification_email_failed","error":"%s"}', type(error).__name__
        )
        raise VerificationEmailFailed(
            f"SES rejected the verification email: {type(error).__name__}"
        ) from error

    message_id = str(response.get("MessageId") or "")
    # Metadata only. No address, no code, nothing derived from the code.
    logger.info(
        '{"event":"verification_email_sent","messageId":"%s","configurationSet":"%s"}',
        message_id, configuration_set or CONFIGURATION_SET,
    )
    return message_id


__all__ = [
    "SENDER_ADDRESS",
    "SENDER_NAME",
    "CONFIGURATION_SET",
    "SUPPORT_EMAIL",
    "SUPPORT_WHATSAPP",
    "COLOR_TEXT",
    "COLOR_TEXT_MUTED",
    "COLOR_BORDER",
    "COLOR_SURFACE",
    "COLOR_BG_SECONDARY",
    "COLOR_ACCENT",
    "COLOR_LIME",
    "FIRST_NAME_MAX",
    "clean_first_name",
    "VerificationEmailFailed",
    "subject_line",
    "text_body",
    "html_body",
    "build_message",
    "send",
]
