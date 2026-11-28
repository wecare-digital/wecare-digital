"""
AWS Billing Lambda Function

Purpose: Report AWS Health and Trusted Advisor status for the operations dashboard.
Account: 775261844268
Region: us-east-1

Cost Explorer was REMOVED on 2026-09-28 by owner decision (confirmation YES 4).

Why: the Cost Explorer API bills $0.01 per request. This function made three CE
calls per invocation (month total, group-by-service, previous-month total) and was
invoked 504 times in September 2026, which accounts for 1,512 of the 1,497 measured
paid CE requests -- effectively the entire $14.97/month Cost Explorer charge, which
was 7x the WAF spend it was being used to report on. Cost reporting moved to the
AWS console and Cost Explorer's own UI, which carry no per-request charge.

Do NOT reintroduce a boto3 'ce' client here. Every call is billable, and a dashboard
that polls this endpoint turns a per-request charge into a recurring one. If
programmatic cost data is genuinely needed, export the Cost and Usage Report to S3
and query that instead -- CUR delivery is free and Athena is charged per byte
scanned, not per question asked.

Uses AWS Health and Support (Trusted Advisor) APIs only.
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
import boto3
from botocore.exceptions import ClientError

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin

# Configure logging
from lambda_utils.logging import get_logger

logger = get_logger(__name__)

# AWS clients. Deliberately no 'ce' (Cost Explorer) client -- see module docstring.
health_client = boto3.client('health', region_name='us-east-1')
support_client = boto3.client('support', region_name='us-east-1')

# Account info
AWS_ACCOUNT_ID = os.environ.get('AWS_ACCOUNT_ID', '')

COST_REPORTING_NOTE = (
    'Cost reporting is disabled. The Cost Explorer API bills per request and was '
    'removed on 2026-09-28; use the AWS Billing console for spend data.'
)


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle billing, health, and trusted advisor requests."""
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)

    from lambda_utils.middleware import require_auth
    _auth = require_auth(event, required_role='Admin')
    if _auth is not None:
        return _auth

    logger.info(json.dumps({
        'event': 'billing_handler',
        'requestId': request_id
    }))

    try:
        # Parse query parameters
        query_params = event.get('queryStringParameters') or {}
        month_offset = int(query_params.get('month', '0'))
        include_health = query_params.get('health', 'true').lower() == 'true'
        include_advisor = query_params.get('advisor', 'true').lower() == 'true'

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Calculate target month
        if month_offset == 0:
            # Current month
            start_of_month = datetime(now.year, now.month, 1)
            end_date = now
        else:
            # Previous month(s)
            target_month = now.month + month_offset
            target_year = now.year
            while target_month <= 0:
                target_month += 12
                target_year -= 1
            while target_month > 12:
                target_month -= 12
                target_year += 1

            start_of_month = datetime(target_year, target_month, 1)
            # End of that month
            if target_month == 12:
                end_date = datetime(target_year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = datetime(target_year, target_month + 1, 1) - timedelta(days=1)

        start_date = start_of_month.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')

        # Cost figures are no longer fetched -- see module docstring.
        billing_data = get_cost_reporting_disabled_payload(start_date, end_date_str)

        # Fetch AWS Health data
        if include_health:
            billing_data['health'] = get_aws_health_status(request_id)

        # Fetch Trusted Advisor data
        if include_advisor:
            billing_data['trustedAdvisor'] = get_trusted_advisor_checks(request_id)

        return _response(200, billing_data)

    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))

        logger.error(json.dumps({
            'event': 'billing_error',
            'errorCode': error_code,
            'error': error_msg,
            'requestId': request_id
        }))

        return _response(500, {'error': f'{error_code}: {error_msg}'})

    except Exception as e:
        logger.error(json.dumps({
            'event': 'billing_error',
            'error': str(e),
            'requestId': request_id
        }))
        return _response(500, {'error': str(e)})


def get_cost_reporting_disabled_payload(start_date: str, end_date: str) -> Dict[str, Any]:
    """Return the billing envelope with cost figures explicitly absent.

    The response keeps every key the dashboard's `AWSBillingData` interface reads, so
    the UI renders an empty cost table rather than failing. `costReportingEnabled`
    is the honest signal: zero here means "not measured", not "spent nothing". The
    dashboard must not present it as a zero bill.
    """
    return {
        'totalCost': 0,
        'period': f'{start_date} to {end_date}',
        'services': [],
        'lastUpdated': datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z',
        'accountId': AWS_ACCOUNT_ID,
        'currency': 'USD',
        'recommendations': [],
        'costReportingEnabled': False,
        'note': COST_REPORTING_NOTE,
    }


def _response(status_code: int, body: Dict) -> Dict[str, Any]:
    """Return HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps(body, default=str)
    }


def get_aws_health_status(request_id: str) -> Dict[str, Any]:
    """Fetch AWS Health Dashboard status."""
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        seven_days_ago = now - timedelta(days=7)

        # Get open events
        open_events = []
        scheduled_changes = []
        other_notifications = []

        try:
            # Describe events affecting this account
            events_response = health_client.describe_events(
                filter={
                    'eventStatusCodes': ['open', 'upcoming'],
                    'startTimes': [
                        {'from': seven_days_ago}
                    ]
                }
            )

            for event in events_response.get('events', []):
                event_data = {
                    'arn': event.get('arn', ''),
                    'service': event.get('service', 'Unknown'),
                    'eventTypeCode': event.get('eventTypeCode', ''),
                    'eventTypeCategory': event.get('eventTypeCategory', ''),
                    'region': event.get('region', 'global'),
                    'startTime': event.get('startTime', '').isoformat() if event.get('startTime') else None,
                    'endTime': event.get('endTime', '').isoformat() if event.get('endTime') else None,
                    'statusCode': event.get('statusCode', ''),
                }

                category = event.get('eventTypeCategory', '')
                if category == 'issue':
                    open_events.append(event_data)
                elif category == 'scheduledChange':
                    scheduled_changes.append(event_data)
                else:
                    other_notifications.append(event_data)

        except ClientError as e:
            if 'SubscriptionRequiredException' in str(e):
                logger.info('AWS Health API requires Business/Enterprise Support')
            else:
                logger.warning(f'Health API error: {e}')

        return {
            'openIssues': len(open_events),
            'scheduledChanges': len(scheduled_changes),
            'otherNotifications': len(other_notifications),
            'events': open_events[:5],  # Return top 5 events
            'scheduledEvents': scheduled_changes[:5],
            'notifications': other_notifications[:5],
            'lastChecked': now.isoformat() + 'Z',
            'status': 'healthy' if len(open_events) == 0 else 'issues'
        }

    except Exception as e:
        logger.error(f'Failed to fetch health status: {e}')
        return {
            'openIssues': 0,
            'scheduledChanges': 0,
            'otherNotifications': 0,
            'events': [],
            'scheduledEvents': [],
            'notifications': [],
            'lastChecked': datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z',
            'status': 'unknown',
            'error': str(e)
        }


def get_trusted_advisor_checks(request_id: str) -> Dict[str, Any]:
    """Fetch Trusted Advisor check results."""
    try:
        checks_summary = {
            'actionRecommended': 0,
            'investigationRecommended': 0,
            'noProblemsDetected': 0,
            'notAvailable': 0,
            'checks': [],
            'categories': {
                'cost_optimizing': {'ok': 0, 'warning': 0, 'error': 0},
                'security': {'ok': 0, 'warning': 0, 'error': 0},
                'fault_tolerance': {'ok': 0, 'warning': 0, 'error': 0},
                'performance': {'ok': 0, 'warning': 0, 'error': 0},
                'service_limits': {'ok': 0, 'warning': 0, 'error': 0},
            }
        }

        try:
            # Get all Trusted Advisor checks
            checks_response = support_client.describe_trusted_advisor_checks(language='en')
            checks = checks_response.get('checks', [])

            # Get check summaries
            check_ids = [c['id'] for c in checks[:50]]  # Limit to 50 checks

            if check_ids:
                summaries_response = support_client.describe_trusted_advisor_check_summaries(
                    checkIds=check_ids
                )

                for summary in summaries_response.get('summaries', []):
                    check_id = summary.get('checkId', '')
                    status = summary.get('status', 'not_available')

                    # Find check details
                    check_info = next((c for c in checks if c['id'] == check_id), {})
                    category = check_info.get('category', 'other')

                    # Count by status
                    if status == 'error':
                        checks_summary['actionRecommended'] += 1
                        if category in checks_summary['categories']:
                            checks_summary['categories'][category]['error'] += 1
                    elif status == 'warning':
                        checks_summary['investigationRecommended'] += 1
                        if category in checks_summary['categories']:
                            checks_summary['categories'][category]['warning'] += 1
                    elif status == 'ok':
                        checks_summary['noProblemsDetected'] += 1
                        if category in checks_summary['categories']:
                            checks_summary['categories'][category]['ok'] += 1
                    else:
                        checks_summary['notAvailable'] += 1

                    # Add to checks list if has issues (exclude S3 versioning check)
                    if status in ['error', 'warning']:
                        # Skip S3 Bucket Versioning check (R365s2Qddf) - not needed
                        if check_id == 'R365s2Qddf':
                            checks_summary['investigationRecommended'] -= 1
                            checks_summary['noProblemsDetected'] += 1
                            continue

                        resources_flagged = summary.get('resourcesSummary', {}).get('resourcesFlagged', 0)
                        checks_summary['checks'].append({
                            'id': check_id,
                            'name': check_info.get('name', 'Unknown'),
                            'category': category,
                            'status': status,
                            'resourcesFlagged': resources_flagged,
                            'description': check_info.get('description', '')[:200],
                        })

            # Sort checks by severity (errors first)
            checks_summary['checks'].sort(key=lambda x: (0 if x['status'] == 'error' else 1, -x.get('resourcesFlagged', 0)))
            checks_summary['checks'] = checks_summary['checks'][:10]  # Top 10 issues

        except ClientError as e:
            if 'SubscriptionRequiredException' in str(e):
                logger.info('Trusted Advisor requires Business/Enterprise Support for full access')
                # Return basic checks available to all accounts
                checks_summary['error'] = 'Business Support required for full Trusted Advisor access'
            else:
                logger.warning(f'Trusted Advisor API error: {e}')
                checks_summary['error'] = str(e)

        checks_summary['lastChecked'] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z'
        return checks_summary

    except Exception as e:
        logger.error(f'Failed to fetch Trusted Advisor: {e}')
        return {
            'actionRecommended': 0,
            'investigationRecommended': 0,
            'noProblemsDetected': 0,
            'notAvailable': 0,
            'checks': [],
            'categories': {},
            'lastChecked': datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z',
            'error': str(e)
        }
