"""
Push Notifications Lambda - WECARE.DIGITAL

Registers device tokens with SNS Platform Applications,
stores token-to-user mappings in DynamoDB,
and sends push notifications via SNS.

AWS Resources:
- SNS Platform Application (FCM): for Android push via Firebase
- SNS Platform Application (APNs): for iOS push via Apple
- DynamoDB PushTokensTable: id (PK; SHA-256 of device token)
"""

import json
import os
import boto3
import logging
import hashlib
from datetime import datetime, timezone
from lambda_utils.middleware import require_auth
from lambda_utils.response import cors_headers, extract_origin

sns = boto3.client("sns")
dynamodb = boto3.resource("dynamodb")

PUSH_TOKENS_TABLE = os.environ.get("PUSH_TOKENS_TABLE", "stack-wecare-digital-PushTokensTable")
SNS_ANDROID_ARN = os.environ.get("SNS_PLATFORM_APP_ARN_ANDROID", "")
SNS_IOS_ARN = os.environ.get("SNS_PLATFORM_APP_ARN_IOS", "")

table = dynamodb.Table(PUSH_TOKENS_TABLE)


def handler(event, context):
    """Main Lambda handler."""
    method = event.get("httpMethod", event.get("requestContext", {}).get("http", {}).get("method", "GET"))
    path = event.get("path", event.get("rawPath", ""))
    try:
        body = json.loads(event.get("body", "{}") or "{}")
    except (json.JSONDecodeError, TypeError, ValueError):
        body = {}

    # Authenticated admin API: reflect only an allow-listed origin, never "*".
    headers = {
        **cors_headers(
            extract_origin(event),
            "GET,POST,DELETE,OPTIONS",
            "Content-Type,Authorization",
        ),
        "Vary": "Origin",
    }

    try:
        if method == "OPTIONS":
            return {"statusCode": 200, "headers": headers, "body": ""}

        required_role = "Admin" if any(segment in path for segment in ("send", "devices")) else None
        auth_result = require_auth(event, required_role=required_role)
        if auth_result is not None:
            return auth_result
        if "register" in path and event.get("_auth"):
            body["userId"] = event["_auth"]["username"]

        if "register" in path:
            if method == "POST":
                return register_token(body, headers)
            elif method == "DELETE":
                return unregister_token(body, headers)

        if "devices" in path and method == "GET":
            return list_devices(event.get("queryStringParameters") or {}, headers)

        if "send" in path and method == "POST":
            return send_push(body, headers)

        return {
            "statusCode": 404,
            "headers": headers,
            "body": json.dumps({"error": "Not found"}),
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": headers,
            "body": json.dumps({"error": str(e)}),
        }


def register_token(body, headers):
    """Register a device push token with SNS and store its authenticated owner."""
    device_token = str(body.get("deviceToken", "")).strip()
    platform = str(body.get("platform", "android")).lower()
    user_id = str(body.get("userId", "")).strip()

    if not device_token:
        return {
            "statusCode": 400,
            "headers": headers,
            "body": json.dumps({"error": "deviceToken required"}),
        }
    if platform not in {"android", "ios"}:
        return {
            "statusCode": 400,
            "headers": headers,
            "body": json.dumps({"error": "platform must be android or ios"}),
        }

    platform_arn = SNS_ANDROID_ARN if platform == "android" else SNS_IOS_ARN
    if not platform_arn:
        return {
            "statusCode": 503,
            "headers": headers,
            "body": json.dumps({"error": f"Push delivery is not configured for {platform}"}),
        }

    response = sns.create_platform_endpoint(
        PlatformApplicationArn=platform_arn,
        Token=device_token,
        CustomUserData=user_id,
    )
    endpoint_arn = response["EndpointArn"]
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    device_id = hashlib.sha256(device_token.encode("utf-8")).hexdigest()
    table.put_item(
        Item={
            "id": device_id,
            "deviceToken": device_token,
            "userId": user_id,
            "platform": platform,
            "endpointArn": endpoint_arn,
            "registeredAt": now,
            "updatedAt": now,
        }
    )

    return {
        "statusCode": 200,
        "headers": headers,
        "body": json.dumps({"success": True}),
    }


def unregister_token(body, headers):
    """Remove an authenticated user's device token from SNS and DynamoDB."""
    device_token = str(body.get("deviceToken", "")).strip()
    user_id = str(body.get("userId", "")).strip()

    if not device_token:
        return {
            "statusCode": 400,
            "headers": headers,
            "body": json.dumps({"error": "deviceToken required"}),
        }

    device_id = hashlib.sha256(device_token.encode("utf-8")).hexdigest()
    item = table.get_item(Key={"id": device_id}).get("Item")
    if item and item.get("userId") != user_id:
        return {
            "statusCode": 403,
            "headers": headers,
            "body": json.dumps({"error": "Device token belongs to another user"}),
        }

    if item and item.get("endpointArn"):
        try:
            sns.delete_endpoint(EndpointArn=item["endpointArn"])
        except Exception as error:
            logging.getLogger(__name__).warning("SNS endpoint cleanup failed: %s", error)

    table.delete_item(Key={"id": device_id})
    return {
        "statusCode": 200,
        "headers": headers,
        "body": json.dumps({"success": True}),
    }


def list_devices(params, headers):
    """List a bounded Admin view of registered devices without endpoint credentials."""
    try:
        limit = min(max(int(params.get("limit", 200)), 1), 500)
    except (TypeError, ValueError):
        limit = 200
    scan_kwargs = {"Limit": limit}
    platform = str(params.get("platform", "all")).lower()
    if platform in {"android", "ios"}:
        scan_kwargs.update({
            "FilterExpression": "platform = :platform",
            "ExpressionAttributeValues": {":platform": platform},
        })
    result = table.scan(**scan_kwargs)
    devices = [{
        "deviceId": item.get("id", ""),
        "userId": item.get("userId", ""),
        "platform": item.get("platform", ""),
        "registeredAt": item.get("registeredAt", ""),
        "updatedAt": item.get("updatedAt", ""),
    } for item in result.get("Items", [])]
    return {
        "statusCode": 200,
        "headers": headers,
        "body": json.dumps({
            "devices": devices,
            "count": len(devices),
            "truncated": "LastEvaluatedKey" in result,
            "configured": {"android": bool(SNS_ANDROID_ARN), "ios": bool(SNS_IOS_ARN)},
        }),
    }


def send_push(body, headers):
    """Send push notification to a specific device or all devices of a user."""
    target_user = body.get("userId")
    target_token = body.get("deviceToken")
    title = body.get("title", "Stack CRM")
    message_body = body.get("body", "")
    data = body.get("data", {})

    endpoints = []

    if target_token:
        device_id = hashlib.sha256(str(target_token).encode("utf-8")).hexdigest()
        item = table.get_item(Key={"id": device_id}).get("Item")
        if item and (not target_user or item.get("userId") == target_user):
            endpoints.append(item)
    elif target_user:
        scan_kwargs = {
            "FilterExpression": "userId = :uid",
            "ExpressionAttributeValues": {":uid": target_user},
        }
        while True:
            result = table.scan(**scan_kwargs)
            endpoints.extend(result.get("Items", []))
            if "LastEvaluatedKey" not in result:
                break
            scan_kwargs["ExclusiveStartKey"] = result["LastEvaluatedKey"]
    elif body.get("broadcast"):
        scan_kwargs = {}
        platform_filter = str(body.get("platform", "all")).lower()
        if platform_filter in {"android", "ios"}:
            scan_kwargs.update({
                "FilterExpression": "platform = :platform",
                "ExpressionAttributeValues": {":platform": platform_filter},
            })
        while True:
            result = table.scan(**scan_kwargs)
            endpoints.extend(result.get("Items", []))
            if "LastEvaluatedKey" not in result:
                break
            scan_kwargs["ExclusiveStartKey"] = result["LastEvaluatedKey"]
    else:
        return {
            "statusCode": 400,
            "headers": headers,
            "body": json.dumps({"error": "deviceToken, userId, or broadcast=true is required"}),
        }

    if not endpoints:
        return {
            "statusCode": 404,
            "headers": headers,
            "body": json.dumps({"error": "No registered devices found"}),
        }

    sent = 0
    failed = 0

    for endpoint in endpoints:
        endpoint_arn = endpoint.get("endpointArn")
        platform = endpoint.get("platform", "android")

        try:
            if not endpoint_arn:
                raise ValueError("Stored device is missing an SNS endpoint")
            if platform == "ios":
                # APNs payload
                payload = json.dumps({
                    "APNS": json.dumps({
                        "aps": {
                            "alert": {"title": title, "body": message_body},
                            "sound": "default",
                            "badge": 1,
                        },
                        "data": data,
                    })
                })
            else:
                # FCM payload
                payload = json.dumps({
                    "GCM": json.dumps({
                        "notification": {"title": title, "body": message_body, "sound": "default"},
                        "data": data,
                    })
                })

            sns.publish(
                TargetArn=endpoint_arn,
                Message=payload,
                MessageStructure="json",
            )
            sent += 1
        except Exception as error:
            logging.getLogger(__name__).warning("Push delivery failed: %s", error)
            failed += 1

    return {
        "statusCode": 200,
        "headers": headers,
        "body": json.dumps({"sent": sent, "failed": failed}),
    }
