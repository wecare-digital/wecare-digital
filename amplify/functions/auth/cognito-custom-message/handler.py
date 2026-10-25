"""Cognito CustomMessage trigger - branded HTML for every email the pool sends.

WHY A LAMBDA AND NOT A SETTING
------------------------------
`EmailMfaConfiguration.Message` is the only place to change the MFA email without
code, and the API reference documents it as a plain template that must contain
`{####}`; it says nothing about HTML. The documented way to send HTML is this
trigger, whose `emailMessage` response parameter explicitly "can use HTML
formatting".

That HTML path has one hard precondition, and this pool meets it:

    Amazon Cognito can use the emailMessage parameter ONLY IF the
    EmailSendingAccount attribute of the user pool is DEVELOPER.

`EmailSendingAccount` is `DEVELOPER` here (SES, identity one@wecare.digital,
configuration set wecare-digital), so `emailMessage` and `emailSubject` are both
honoured. If anyone ever switches the pool back to `COGNITO_DEFAULT`, Cognito
answers `InvalidLambdaResponseException` and **sign-in email stops working** - so
that switch and this function are coupled.

THE CODE IS NEVER IN THIS FUNCTION
----------------------------------
`request.codeParameter` is a *placeholder* string, typically `{####}`, not the
real one-time code. Cognito substitutes the value after this function returns. So
there is no credential here to leak, and nothing below needs redacting - a
genuinely nice property of this trigger, and the reason logging is safe.

The placeholder is read from the request rather than hardcoded as `{####}`,
which the docs call out as best practice, because it is Cognito's to choose.
`CustomMessage_AdminCreateUser` additionally requires `usernameParameter` to
appear in the body, or the new user never learns their own username.

WHY EVERY TRIGGER SOURCE IS HANDLED, NOT JUST MFA
-------------------------------------------------
This trigger intercepts *all* pool email. Handling only the MFA source would
leave the rest falling through to Cognito's unstyled default, which is the
inconsistency being fixed. Each source also gets its own heading and intro, so
two messages arriving together are immediately distinguishable - the owner
reported receiving two emails and being unable to tell them apart.

EMAIL IS NOT THE BROWSER - the deliberate deviations from the design contract
----------------------------------------------------------------------------
Values come from .kiro/steering/grahak-os-design.md (retired 2026-10-09, af7858fa), with four changes forced by
mail clients rather than chosen:

1. `rgba()` is replaced by its **composited hex equivalent on white**. Outlook's
   Word rendering engine does not support rgba, and would drop the declaration
   and fall back to unstyled black. Same colour, opaque:
       rgba(0,0,0,.95)  -> #0d0d0d   (255 * 0.05  = 12.75)
       rgba(0,0,0,.898) -> #1a1a1a   (255 * 0.102 = 26)   also the contract's own
                                      brand near-black, so this is exact
       rgba(0,0,0,.54)  -> #757575   (255 * 0.46  = 117)
2. `clamp()` is replaced by one fixed size. clamp() is unsupported across most
   mail clients, and an unsupported font-size leaves the heading at a default.
   32px is the bottom of the contract's section clamp, so it is a value the
   ladder already contains.
3. Tables and inline styles, not flex or a <style> block. Gmail strips <head>
   styles in forwarded mail and Outlook ignores flex, so a stylesheet-based
   layout collapses.
4. The body copy sits at 17px rather than the contract's 20px. 20px is the
   contract's single body level for a 1300px page; in a 600px email column it
   wraps to very few words per line. 17px is the contract's own pill/`.msg` size,
   so again not a new value.

Everything else is the contract as written: the Inter-first stack, #e5e7eb
hairlines, the #000 code panel at 14px radius with white monospace, lime #d1f470
with #1a3a2a type for our own mark, and the 20px radius static card.
"""

from __future__ import annotations

import json
import os

# Pool-level sender identity, kept here only for the footer copy. The actual
# envelope is set by the pool's EmailConfiguration, not by this function.
SENDER = os.environ.get("SENDER_ADDRESS", "one@wecare.digital")
BRAND = os.environ.get("BRAND_NAME", "WECARE.DIGITAL")
SIGNIN_URL = os.environ.get("SIGNIN_URL", "https://wecare.digital/")

FONT = (
    "'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
    "Helvetica,Arial,sans-serif"
)
MONO = "'SF Mono',Monaco,Consolas,'Liberation Mono',monospace"

# Composited hex for the contract's rgba values - see the module docstring.
HEADING = "#0d0d0d"
BODY = "#1a1a1a"
MUTED = "#757575"
HAIRLINE = "#e5e7eb"
LIME = "#d1f470"
DARK_GREEN = "#1a3a2a"
BAND = "#fafafa"

# (subject, heading, intro, what the code is for). One entry per documented
# trigger source, so nothing falls through to Cognito's unstyled default.
MESSAGES = {
    "CustomMessage_Authentication": (
        f"{BRAND} sign-in code",
        "Your sign-in code",
        "Enter this code to finish signing in. It is only valid for a few "
        "minutes, and requesting a new one replaces it.",
        "sign-in",
    ),
    "CustomMessage_SignUp": (
        f"Confirm your {BRAND} email",
        "Confirm your email",
        "Enter this code to confirm your email address.",
        "confirmation",
    ),
    "CustomMessage_ResendCode": (
        f"Your new {BRAND} confirmation code",
        "Your new confirmation code",
        "Here is a fresh confirmation code. Any earlier code no longer works.",
        "confirmation",
    ),
    "CustomMessage_ForgotPassword": (
        f"Reset your {BRAND} password",
        "Reset your password",
        "Enter this code to choose a new password. If you did not ask to reset "
        "it, you can ignore this message - nothing has changed yet.",
        "password reset",
    ),
    "CustomMessage_UpdateUserAttribute": (
        f"Verify your new {BRAND} contact details",
        "Verify your new details",
        "Your email address or phone number was changed. Enter this code to "
        "verify the new one.",
        "verification",
    ),
    "CustomMessage_VerifyUserAttribute": (
        f"Verify your {BRAND} contact details",
        "Verify your details",
        "Enter this code to verify your new email address or phone number.",
        "verification",
    ),
    "CustomMessage_AdminCreateUser": (
        f"Your {BRAND} account is ready",
        "Your account is ready",
        "An account has been created for you. Sign in with the username and "
        "temporary password below, then set your own password.",
        "temporary password",
    ),
}

DEFAULT_MESSAGE = (
    f"{BRAND} security code",
    "Your security code",
    "Enter this code to continue.",
    "security",
)


def _panel(value: str, label: str | None = None) -> str:
    """The contract's code panel: #000, radius 14px, white monospace.

    `label` is omitted for a single-code message, because the heading above
    already says what the code is for and repeating it inside the panel is the
    kind of duplication that made the original mail hard to read. It is used only
    when a message carries TWO panels and they must be told apart - which is just
    the admin-created-user case, username and temporary password.

    The label colour is #b7b7b7, not white at 72% opacity: Outlook ignores
    `opacity`, which would render the label at full white and make it compete
    with the code. 255 * 0.72 = 183 = #b7b7b7, so it is the same grey the
    contract already uses on a dark panel, composited.
    """
    label_html = (
        f'<div style="font-family:{FONT};font-size:14px;line-height:1.4;'
        f'color:#b7b7b7;margin:0 0 10px">{label}</div>'
        if label else ""
    )
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="margin:0 0 22px"><tr><td '
        f'style="background:#000000;border-radius:14px;padding:22px 24px;'
        f'text-align:center">'
        f"{label_html}"
        f'<div style="font-family:{MONO};font-size:30px;font-weight:700;'
        f'letter-spacing:6px;line-height:1.3;color:#ffffff">{value}</div>'
        f"</td></tr></table>"
    )


def build_email(trigger: str, code_param: str, username_param: str | None) -> str:
    """Return the full HTML body. Must contain code_param verbatim."""
    subject, heading, intro, code_label = MESSAGES.get(trigger, DEFAULT_MESSAGE)

    # Two panels only for the admin-created user, where username and temporary
    # password would otherwise be indistinguishable. Everything else is one
    # unlabelled panel, because the heading has already named the code.
    if trigger == "CustomMessage_AdminCreateUser" and username_param:
        panels = (_panel(username_param, "Username")
                  + _panel(code_param, "Temporary password"))
    else:
        panels = _panel(code_param)

    # width=600 and a nested fixed-width table: the standard email shell. The
    # outer table paints the #fafafa band, the inner one is the white card, which
    # is the same figure/ground pair the public sections use.
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{subject}</title></head>
<body style="margin:0;padding:0;background:{BAND};">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
 style="background:{BAND};padding:32px 12px">
<tr><td align="center">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600"
 style="width:600px;max-width:600px;background:#ffffff;border:1px solid {HAIRLINE};
 border-radius:20px">
<tr><td style="padding:34px 30px 0">
  <span style="display:inline-block;background:{LIME};color:{DARK_GREEN};
   font-family:{FONT};font-size:14px;font-weight:600;letter-spacing:-0.125px;
   line-height:1;padding:10px 17px;border-radius:9999px">{BRAND}</span>
</td></tr>
<tr><td style="padding:24px 30px 0">
  <h1 style="margin:0 0 14px;font-family:{FONT};font-size:32px;font-weight:700;
   line-height:1.04;letter-spacing:-1.2px;color:{HEADING}">{heading}</h1>
  <p style="margin:0 0 24px;font-family:{FONT};font-size:17px;font-weight:400;
   line-height:1.4;letter-spacing:-0.125px;color:{BODY}">{intro}</p>
</td></tr>
<tr><td style="padding:0 30px">{panels}</td></tr>
<tr><td style="padding:0 30px">
  <p style="margin:0 0 22px;font-family:{FONT};font-size:14px;font-weight:400;
   line-height:1.4;color:{MUTED}">
   Nobody from {BRAND} will ever ask you for this code. If you did not request
   it, ignore this message and tell us.</p>
</td></tr>
<tr><td style="padding:0 30px 34px">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
  <tr><td style="border-top:1px solid {HAIRLINE};padding-top:18px">
    <p style="margin:0;font-family:{FONT};font-size:14px;line-height:1.5;
     color:{MUTED}">
     Sent by <a href="{SIGNIN_URL}" style="color:{DARK_GREEN};
     text-decoration:underline">{BRAND}</a> from {SENDER}.</p>
  </td></tr></table>
</td></tr>
</table>
</td></tr></table>
</body></html>"""


def handler(event: dict, context) -> dict:
    trigger = event.get("triggerSource", "")
    request = event.get("request", {}) or {}
    # Read the placeholders from the request rather than hardcoding {####} /
    # {username}: they are Cognito's to choose, and the docs say to reference them.
    code_param = request.get("codeParameter") or "{####}"
    username_param = request.get("usernameParameter")

    subject = MESSAGES.get(trigger, DEFAULT_MESSAGE)[0]
    body = build_email(trigger, code_param, username_param)

    # Refuse to return a body Cognito would reject, rather than let it fail at
    # delivery time - a dropped MFA mail locks someone out of their own account.
    if code_param not in body:
        raise ValueError("email body is missing the code placeholder")
    if trigger == "CustomMessage_AdminCreateUser" and username_param \
            and username_param not in body:
        raise ValueError("admin-create body is missing the username placeholder")

    response = event.setdefault("response", {})
    response["emailSubject"] = subject
    response["emailMessage"] = body

    # Metadata only. There is no code here to redact - codeParameter is a
    # placeholder - but the trigger source is worth logging: it is the only way
    # to tell WHICH messages a pool actually sent when someone reports getting
    # two of them.
    print(json.dumps({
        "event": "cognito_custom_message",
        "triggerSource": trigger,
        "emailBytes": len(body),
        "knownSource": trigger in MESSAGES,
    }))
    return event
