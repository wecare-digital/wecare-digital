"""The required Cognito app-client and session-table configuration, as reviewable data, NOT deployed.

Why this is a config module and not a deploy
--------------------------------------------
The backend-owned session (see `customer_session`) needs two provisioned things that only exist in
AWS: the customer app client has to permit a refresh flow, and a `CustomerSessionsTable` has to hold
the server-side rows. Both are BLOCKED here - there are no AWS credentials in this environment, so
the live app client cannot be inspected and nothing can be deployed. Rather than guess and deploy,
the required settings are written here as data a reviewer can read and a later operator can apply,
with the exact unblock commands recorded alongside.

The one decision that cannot be made offline
---------------------------------------------
Whether the customer app client ROTATES refresh tokens decides the refresh flow:
  - rotation ENABLED  -> `GetTokensFromRefreshToken` (returns a new refresh token each time)
  - rotation DISABLED -> `REFRESH_TOKEN_AUTH` (reuses the refresh token)
`REFRESH_TOKEN_AUTH` is INCOMPATIBLE with rotation and fails against a rotating client, so the two
cannot be hedged. The setting is a property of the deployed client, read with:

    aws cognito-idp describe-user-pool-client \\
      --user-pool-id us-east-1_46ULYuukt \\
      --client-id 4avmt9n4gpmkvkdk88qbtit33o \\
      --query 'UserPoolClient.{refresh:RefreshTokenValidity,rotation:RefreshTokenRotation,flows:ExplicitAuthFlows}'

That command is the unblock step. Until it is run, `customer_session.refresh_access_token` takes the
flow as a per-session parameter (defaulted conservatively) so the code is complete and tested for
both branches; it is the live value that is pending, not the implementation.

Never UpdateUserPool to apply this
-----------------------------------
`.kiro/steering/aws-agent-rules`: `UpdateUserPool` is a FULL REPLACE and silently drops the pool's
triggers - including the `CreateAuthChallenge`/`VerifyAuthChallengeResponse` pair that delivers the
WhatsApp OTP. The CUSTOM_AUTH triggers and every existing client setting MUST be preserved. App
*client* settings are changed with `update-user-pool-client`, which does not touch pool triggers,
and the safe-update pattern in `scripts/cognito_pool_safe_update.py` is the reference for any
pool-level change. This module authors the intent; it runs nothing.
"""

from __future__ import annotations

from typing import Any, Dict

#: The customer pool and app client this session binds to. Identifiers, not secrets - the same
#: public client id `customerAuth.ts` already ships. Pinned here so the describe/update commands and
#: the running code cannot drift onto different clients.
CUSTOMER_POOL_ID = "us-east-1_46ULYuukt"
CUSTOMER_APP_CLIENT_ID = "4avmt9n4gpmkvkdk88qbtit33o"


#: Required customer app-client settings for a remembered session. Section 16's recommended policy:
#: short-lived access tokens with silent renewal, a 30-day refresh validity to back the absolute
#: cap, and CUSTOM_AUTH preserved so WhatsApp OTP still establishes the session.
REQUIRED_APP_CLIENT_SETTINGS: Dict[str, Any] = {
    "AccessTokenValidity": 60,            # minutes - short-lived, renewed silently server-side
    "IdTokenValidity": 60,                # minutes
    "RefreshTokenValidity": 30,           # days - backs the 30-day absolute cap
    "TokenValidityUnits": {
        "AccessToken": "minutes",
        "IdToken": "minutes",
        "RefreshToken": "days",
    },
    # CUSTOM_AUTH stays, because it is how the WhatsApp OTP challenge establishes the session; a
    # refresh flow is ADDED alongside, never in place of it.
    "ExplicitAuthFlows": [
        "ALLOW_CUSTOM_AUTH",
        "ALLOW_REFRESH_TOKEN_AUTH",
        "ALLOW_USER_SRP_AUTH",
    ],
    # The sign-in front door stays non-enumerable; unchanged, restated so an update does not drop it.
    "PreventUserExistenceErrors": "ENABLED",
    "GenerateSecret": False,
    # Rotation is the pending live decision; see module docstring. Left unspecified here on purpose,
    # so this config is not read as asserting a value the describe command has not yet confirmed.
}

#: The DynamoDB table backing server-side custody. Keyed on the HASH of the opaque id (never the id)
#: so a table read cannot yield a usable session. TTL on `absoluteExpiresAt` sweeps dead rows, but
#: it is a janitor, NOT the security boundary - `customer_session.validate` enforces both deadlines
#: in code regardless of whether TTL has fired yet.
REQUIRED_SESSION_TABLE: Dict[str, Any] = {
    "TableName": "stack-wecare-digital-CustomerSessionsTable",
    "KeySchema": [{"AttributeName": "sidHash", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "sidHash", "AttributeType": "S"}],
    "BillingMode": "PAY_PER_REQUEST",
    "TimeToLiveSpecification": {"AttributeName": "absoluteExpiresAt", "Enabled": True},
    "SSESpecification": {"Enabled": True},
    "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True},
}

#: The commands a later operator runs to apply the above, with no credentials present here to run
#: them. Recorded so the BLOCKED work is a precise checklist, not a vague "configure Cognito".
UNBLOCK_COMMANDS = {
    "inspect_rotation": (
        "aws cognito-idp describe-user-pool-client "
        f"--user-pool-id {CUSTOMER_POOL_ID} --client-id {CUSTOMER_APP_CLIENT_ID} "
        "--query 'UserPoolClient.{refresh:RefreshTokenValidity,"
        "rotation:RefreshTokenRotation,flows:ExplicitAuthFlows}'"
    ),
    "update_app_client": (
        "aws cognito-idp update-user-pool-client "
        f"--user-pool-id {CUSTOMER_POOL_ID} --client-id {CUSTOMER_APP_CLIENT_ID} "
        "--explicit-auth-flows ALLOW_CUSTOM_AUTH ALLOW_REFRESH_TOKEN_AUTH ALLOW_USER_SRP_AUTH "
        "--prevent-user-existence-errors ENABLED  "
        "# update-user-pool-client, NOT update-user-pool: the pool full-replace drops OTP triggers"
    ),
    "create_sessions_table": (
        "aws dynamodb create-table "
        "--table-name stack-wecare-digital-CustomerSessionsTable "
        "--attribute-definitions AttributeName=sidHash,AttributeType=S "
        "--key-schema AttributeName=sidHash,KeyType=HASH "
        "--billing-mode PAY_PER_REQUEST --sse-specification Enabled=true"
    ),
    "enable_session_ttl": (
        "aws dynamodb update-time-to-live "
        "--table-name stack-wecare-digital-CustomerSessionsTable "
        "--time-to-live-specification Enabled=true,AttributeName=absoluteExpiresAt"
    ),
}

#: Verbatim record for the feature findings / review. Keeps "what is blocked and how to unblock it"
#: in one asserted place rather than scattered through prose.
BLOCKED_ON_ENVIRONMENT = (
    "No AWS credentials in this environment: the customer app client cannot be inspected "
    "(rotation vs REFRESH_TOKEN_AUTH / GetTokensFromRefreshToken is undecided) and nothing can be "
    "deployed. The session code and tests are complete for both refresh flows; apply the settings "
    "in REQUIRED_APP_CLIENT_SETTINGS / REQUIRED_SESSION_TABLE with the UNBLOCK_COMMANDS once "
    "credentials exist. Never UpdateUserPool - it is a full replace that drops the OTP triggers."
)


def refresh_flow_for(rotation_enabled: bool) -> str:
    """The Cognito API a client with this rotation setting must use to refresh.

    A single source for the rule so the handler and the review agree: rotation forces
    `GetTokensFromRefreshToken`; its absence uses `REFRESH_TOKEN_AUTH`. The two are not
    interchangeable - `REFRESH_TOKEN_AUTH` fails against a rotating client.
    """
    return "GetTokensFromRefreshToken" if rotation_enabled else "REFRESH_TOKEN_AUTH"


__all__ = [
    "CUSTOMER_POOL_ID",
    "CUSTOMER_APP_CLIENT_ID",
    "REQUIRED_APP_CLIENT_SETTINGS",
    "REQUIRED_SESSION_TABLE",
    "UNBLOCK_COMMANDS",
    "BLOCKED_ON_ENVIRONMENT",
    "refresh_flow_for",
]
