"""
GDPR Data Subject Access Request (DSAR) utilities.

Provides automated data export and deletion for GDPR compliance.
Used by handlers that need to process data subject requests.

Usage:
    from lambda_utils.gdpr import export_user_data, delete_user_data
"""

import json
import time
import logging
from typing import Dict, Any, List
from decimal import Decimal

logger = logging.getLogger(__name__)

# Tables that contain user PII, keyed by the field that identifies the user
USER_DATA_TABLES = {
    'Contact': {'key_field': 'phone', 'index': 'phone'},
    'WhatsAppInbound': {'key_field': 'phone', 'index': 'contactId'},
    'WhatsAppOutbound': {'key_field': 'phone', 'index': 'contactId'},
    'Message': {'key_field': 'contactId', 'index': 'contactId'},
    'WhatsAppVoice': {'key_field': 'contactId', 'index': 'contactId'},
    'WhatsAppCalling': {'key_field': 'fromNumber', 'index': None},
    'ScheduledMessage': {'key_field': 'contactId', 'index': 'contactId'},
    'Payment': {'key_field': 'contact', 'index': None},
    'ConversationHistory': {'key_field': 'phoneHash', 'index': None},
    'AIInteraction': {'key_field': 'messageId', 'index': None},
    'SubmitRequest': {'key_field': 'phone', 'index': 'phone'},
    'Invoice': {'key_field': 'contactId', 'index': 'contactId'},
}


def export_user_data(dynamodb_resource, contact_id: str, phone: str,
                     table_prefix: str = 'stack-wecare-digital-') -> Dict[str, Any]:
    """
    Export all user data across tables for a DSAR request.
    Returns a dict of table_name -> list of items.
    """
    export = {}
    for table_name, config in USER_DATA_TABLES.items():
        full_table_name = f'{table_prefix}{table_name}Table'
        try:
            table = dynamodb_resource.Table(full_table_name)
            items = []

            # Try GSI query first (efficient)
            if config['index'] and config['key_field'] in ('contactId', 'phone'):
                lookup_value = contact_id if config['key_field'] == 'contactId' else phone
                if lookup_value:
                    all_query_items = []
                    query_kwargs = {
                        'IndexName': f'{config["index"]}-index',
                        'KeyConditionExpression': f'{config["key_field"]} = :val',
                        'ExpressionAttributeValues': {':val': lookup_value},
                        'Limit': 1000,
                    }
                    while True:
                        resp = table.query(**query_kwargs)
                        all_query_items.extend(resp.get('Items', []))
                        if 'LastEvaluatedKey' not in resp:
                            break
                        query_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
                    items = all_query_items
            else:
                # Fallback: scan with filter (less efficient but covers all tables)
                if phone:
                    all_scan_items = []
                    scan_kwargs = {
                        'FilterExpression': f'contains({config["key_field"]}, :val)',
                        'ExpressionAttributeValues': {':val': phone},
                    }
                    while True:
                        resp = table.scan(**scan_kwargs)
                        all_scan_items.extend(resp.get('Items', []))
                        if 'LastEvaluatedKey' not in resp:
                            break
                        scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
                    items = all_scan_items

            if items:
                # Convert Decimal to float for JSON serialization
                export[table_name] = _sanitize_items(items)
        except Exception as e:
            logger.warning(f'DSAR export skipped for {table_name}: {e}')

    return {
        'contactId': contact_id,
        'phone': phone,
        'exportedAt': int(time.time()),
        'tables': export,
        'tableCount': len(export),
        'totalRecords': sum(len(v) for v in export.values()),
    }


def delete_user_data(dynamodb_resource, contact_id: str, phone: str,
                     table_prefix: str = 'stack-wecare-digital-',
                     dry_run: bool = True) -> Dict[str, Any]:
    """
    Delete all user data across tables for a GDPR erasure request.
    Set dry_run=False to actually delete (default is dry_run=True for safety).
    Returns summary of what was/would be deleted.
    """
    summary = {}
    for table_name, config in USER_DATA_TABLES.items():
        full_table_name = f'{table_prefix}{table_name}Table'
        try:
            table = dynamodb_resource.Table(full_table_name)
            items = []

            if config['index'] and config['key_field'] in ('contactId', 'phone'):
                lookup_value = contact_id if config['key_field'] == 'contactId' else phone
                if lookup_value:
                    all_delete_items = []
                    query_kwargs = {
                        'IndexName': f'{config["index"]}-index',
                        'KeyConditionExpression': f'{config["key_field"]} = :val',
                        'ExpressionAttributeValues': {':val': lookup_value},
                        'Limit': 1000,
                    }
                    while True:
                        resp = table.query(**query_kwargs)
                        all_delete_items.extend(resp.get('Items', []))
                        if 'LastEvaluatedKey' not in resp:
                            break
                        query_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
                    items = all_delete_items

            count = len(items)
            if count > 0 and not dry_run:
                # Get table key schema for deletion
                desc = table.meta.client.describe_table(TableName=full_table_name)
                key_schema = desc['Table']['KeySchema']
                key_names = [k['AttributeName'] for k in key_schema]

                with table.batch_writer() as batch:
                    for item in items:
                        key = {k: item[k] for k in key_names if k in item}
                        if key:
                            batch.delete_item(Key=key)

            summary[table_name] = {'count': count, 'deleted': not dry_run and count > 0}
        except Exception as e:
            summary[table_name] = {'count': 0, 'error': str(e)}

    return {
        'contactId': contact_id,
        'phone': phone,
        'dryRun': dry_run,
        'processedAt': int(time.time()),
        'tables': summary,
        'totalRecords': sum(v.get('count', 0) for v in summary.values()),
    }


def _sanitize_items(items: List[Dict]) -> List[Dict]:
    """Convert Decimal values to float for JSON serialization."""
    sanitized = []
    for item in items:
        clean = {}
        for k, v in item.items():
            if isinstance(v, Decimal):
                clean[k] = float(v)
            elif isinstance(v, dict):
                clean[k] = _sanitize_items([v])[0]
            else:
                clean[k] = v
        sanitized.append(clean)
    return sanitized
