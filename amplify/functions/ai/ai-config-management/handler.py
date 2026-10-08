"""
AI Config Management Lambda Function

Purpose: Manage Bedrock AI configuration for WhatsApp auto-replies
- Enable/disable AI responses
- Configure response language preferences
- Set custom prompts and fallback messages
- View AI interaction logs
- Control which message types trigger AI

Table: SystemConfigTable
Keys:
- ai_config: Main AI configuration
- ai_prompts_{lang}: Language-specific prompts
- ai_fallbacks_{lang}: Language-specific fallback messages
"""

import os
import json
import logging
import boto3
from typing import Dict, Any, List
from decimal import Decimal
import time

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.agent import governance as gov

# Configure logging
from lambda_utils.logging import get_logger

logger = get_logger(__name__)

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Environment variables
SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
AI_INTERACTIONS_TABLE = os.environ.get('AI_INTERACTIONS_TABLE', 'stack-wecare-digital-AIInteractionsTable')
CONVERSATION_HISTORY_TABLE = os.environ.get('CONVERSATION_HISTORY_TABLE', 'stack-wecare-digital-ConversationHistoryTable')

# CORS headers
# CORS headers provided by lambda_utils.response.cors_headers(origin)

# Default AI configuration
DEFAULT_AI_CONFIG = {
    'enabled': False,
    'autoReplyEnabled': False,
    'respondToInteractive': True,  # Respond to button/list replies
    'respondToText': True,
    'respondToMedia': False,
    'respondToLocation': True,
    'maxResponseLength': 500,
    'responseDelay': 0,  # Seconds to wait before responding
    'supportedLanguages': ['en', 'hi', 'hi-Latn', 'bn', 'ta', 'te', 'gu', 'mr'],
    'defaultLanguage': 'en',
    # No agent, alias or knowledge-base id. Re-measured 2026-09-23: the account's
    # only Bedrock Agent is an empty never-prepared shell (no model, 0-character
    # instruction, null role, 0 action groups) and the account holds 0 knowledge
    # bases. The values previously here - '4UUQYFWX64' / 'TSTALIASID' /
    # 'static-faq' - named nothing, and this config is returned by an API and
    # rendered in the dashboard, so they read as working configuration.
    # Empty means not configured, which is the truth. See plan item 6.4.
    'agentId': '',
    'agentAlias': '',
    'knowledgeBaseId': '',
    'modelId': 'amazon.nova-pro-v1:0',
}

# Supported languages with display names
SUPPORTED_LANGUAGES = {
    'en': 'English',
    'hi': 'Hindi',
    'hi-Latn': 'Hinglish',
    'bn': 'Bengali',
    'ta': 'Tamil',
    'te': 'Telugu',
    'gu': 'Gujarati',
    'mr': 'Marathi',
}


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AI Config Management API Handler
    
    Routes:
    - GET /ai/config - Get AI configuration
    - PUT /ai/config - Update AI configuration
    - GET /ai/prompts - Get all language prompts
    - PUT /ai/prompts/{lang} - Update prompt for language
    - GET /ai/fallbacks - Get all fallback messages
    - PUT /ai/fallbacks/{lang} - Update fallback for language
    - GET /ai/interactions - Get AI interaction logs
    - GET /ai/stats - Get AI usage statistics
    """
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)
    
    # Handle both API Gateway v1 (REST) and v2 (HTTP) event formats
    request_context = event.get('requestContext', {})
    
    # API Gateway v2 (HTTP API) format
    if 'http' in request_context:
        http_method = request_context.get('http', {}).get('method', 'GET')
        path = request_context.get('http', {}).get('path', '')
    else:
        # API Gateway v1 (REST API) format
        http_method = event.get('httpMethod', 'GET')
        path = event.get('path', '')

    # Also check rawPath for HTTP API
    if not path:
        path = event.get('rawPath', '')
    
    path_params = event.get('pathParameters') or {}
    query_params = event.get('queryStringParameters') or {}
    
    logger.info(json.dumps({
        'event': 'ai_config_request',
        'method': http_method,
        'path': path,
        'rawPath': event.get('rawPath', ''),
        'requestId': request_id
    }))
    
    # Handle OPTIONS preflight
    if http_method == 'OPTIONS':
        return options_response(origin)

    from lambda_utils.middleware import require_auth
    _auth = require_auth(event)
    if _auth is not None:
        return _auth
    
    try:
        body = {}
        if event.get('body'):
            body = json.loads(event.get('body', '{}'))
        
        # Route handling
        if http_method == 'GET':
            # Internal AI config (FloatingAgent - admin tasks)
            if '/ai/internal/config' in path:
                return _get_internal_config(request_id)
            # External AI config (WhatsApp auto-reply) — supports ?key= for arbitrary config
            elif '/ai/config' in path:
                cfg_key = query_params.get('key', 'ai_config')
                return _get_config(request_id, config_key=cfg_key)
            elif '/ai/prompts' in path:
                lang = path_params.get('lang')
                return _get_prompts(lang, request_id)
            elif '/ai/fallbacks' in path:
                lang = path_params.get('lang')
                return _get_fallbacks(lang, request_id)
            elif '/ai/interactions' in path:
                return _get_interactions(query_params, request_id)
            elif '/ai/stats' in path:
                return _get_stats(request_id)
            elif '/ai/languages' in path:
                return _get_languages(request_id)
            elif '/ai/botflow' in path:
                return _get_botflow_config(request_id)
        
        elif http_method == 'PUT':
            # Body-based clear-logs trigger via existing PUT route
            if body.get('_action') == 'clear-logs':
                return _clear_ai_logs(request_id)
            # Internal AI config
            if '/ai/internal/config' in path:
                return _update_internal_config(body, request_id)
            # External AI config — supports body.key for arbitrary config
            elif '/ai/config' in path:
                cfg_key = body.pop('key', 'ai_config') if isinstance(body, dict) else 'ai_config'
                return _update_config(body, request_id, config_key=cfg_key)
            elif '/ai/prompts' in path:
                lang = path_params.get('lang') or body.get('language')
                return _update_prompt(lang, body, request_id)
            elif '/ai/fallbacks' in path:
                lang = path_params.get('lang') or body.get('language')
                return _update_fallback(lang, body, request_id)
            elif '/ai/botflow' in path:
                return _update_botflow_config(body, request_id)
        
        elif http_method == 'POST':
            if body.get('_action') == 'clear-logs':
                return _clear_ai_logs(request_id)
            elif '/ai/test' in path:
                return _test_ai_response(body, request_id)
            elif '/ai/clear-logs' in path:
                return _clear_ai_logs(request_id)
        
        elif http_method == 'DELETE':
            if '/ai/botflow' in path:
                return _delete_botflow_configs(request_id)
            elif '/ai/clear-logs' in path:
                return _clear_ai_logs(request_id)
        
        return _error_response(400, 'Invalid request')
        
    except json.JSONDecodeError:
        return _error_response(400, 'Invalid JSON in request body')
    except Exception as e:
        logger.error(json.dumps({
            'event': 'ai_config_error',
            'error': str(e),
            'requestId': request_id
        }))
        return _error_response(500, str(e))


def _get_config(request_id: str, config_key: str = 'ai_config') -> Dict[str, Any]:
    """Get AI configuration — or any SystemConfig entry by key."""
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        response = config_table.get_item(Key={'id': config_key})

        if 'Item' in response:
            config_value = response['Item'].get('configValue', '{}')
            try:
                config = json.loads(config_value) if isinstance(config_value, str) else config_value
            except (json.JSONDecodeError, TypeError):
                config = config_value
        else:
            if config_key == 'ai_config':
                config = DEFAULT_AI_CONFIG.copy()
                config_table.put_item(Item={
                    'id': 'ai_config',
                    'configValue': json.dumps(config),
                    'updatedAt': Decimal(str(int(time.time())))
                })
            else:
                return {
                    'statusCode': 200,
                    'headers': cors_headers(origin),
                    'body': json.dumps({'config': None, 'configKey': config_key})
                }

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'config': config, 'configKey': config_key})
        }
    except Exception as e:
        logger.error(f'Failed to get config [{config_key}]: {str(e)}')
        if config_key == 'ai_config':
            return {
                'statusCode': 200,
                'headers': cors_headers(origin),
                'body': json.dumps({'config': DEFAULT_AI_CONFIG})
            }
        return _error_response(500, f'Failed to get config: {str(e)}')


def _update_config(body: Dict, request_id: str, config_key: str = 'ai_config') -> Dict[str, Any]:
    """Update AI configuration — or any SystemConfig entry by key."""
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)

        # If a specific key is provided (non-ai_config), do a raw put
        if config_key != 'ai_config':
            config_value = body.get('config', body.get('configValue', body))
            store_val = json.dumps(config_value) if not isinstance(config_value, str) else config_value
            config_table.put_item(Item={
                'id': config_key,
                'configValue': store_val,
                'updatedAt': Decimal(str(int(time.time())))
            })
            logger.info(json.dumps({
                'event': 'system_config_updated',
                'configKey': config_key,
                'requestId': request_id
            }))
            return {
                'statusCode': 200,
                'headers': cors_headers(origin),
                'body': json.dumps({'success': True, 'configKey': config_key})
            }

        # AI config: merge with existing
        response = config_table.get_item(Key={'id': 'ai_config'})
        if 'Item' in response:
            existing = json.loads(response['Item'].get('configValue', '{}'))
        else:
            existing = DEFAULT_AI_CONFIG.copy()

        for key, value in body.items():
            if key in DEFAULT_AI_CONFIG:
                existing[key] = value

        config_table.put_item(Item={
            'id': 'ai_config',
            'configValue': json.dumps(existing),
            'updatedAt': Decimal(str(int(time.time())))
        })

        logger.info(json.dumps({
            'event': 'ai_config_updated',
            'enabled': existing.get('enabled'),
            'autoReplyEnabled': existing.get('autoReplyEnabled'),
            'requestId': request_id
        }))

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'success': True, 'config': existing})
        }
    except Exception as e:
        return _error_response(500, f'Failed to update config: {str(e)}')


def _get_prompts(lang: str, request_id: str) -> Dict[str, Any]:
    """Get language-specific prompts."""
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)

        if lang:
            response = config_table.get_item(Key={'id': f'ai_prompt_{lang}'})
            if 'Item' in response:
                prompt = response['Item'].get('configValue', '')
                return {
                    'statusCode': 200,
                    'headers': cors_headers(origin),
                    'body': json.dumps({'language': lang, 'prompt': prompt})
                }
            return {
                'statusCode': 200,
                'headers': cors_headers(origin),
                'body': json.dumps({'language': lang, 'prompt': _get_default_prompt(lang)})
            }

        prompts = {}
        for lang_code in SUPPORTED_LANGUAGES.keys():
            response = config_table.get_item(Key={'id': f'ai_prompt_{lang_code}'})
            if 'Item' in response:
                prompts[lang_code] = response['Item'].get('configValue', '')
            else:
                prompts[lang_code] = _get_default_prompt(lang_code)

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'prompts': prompts})
        }
    except Exception as e:
        return _error_response(500, f'Failed to get prompts: {str(e)}')


def _update_prompt(lang: str, body: Dict, request_id: str) -> Dict[str, Any]:
    """Update language-specific prompt."""
    if not lang:
        return _error_response(400, 'Language code is required')

    prompt = body.get('prompt', '')
    if not prompt:
        return _error_response(400, 'Prompt text is required')

    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        config_table.put_item(Item={
            'id': f'ai_prompt_{lang}',
            'configValue': prompt,
            'updatedAt': Decimal(str(int(time.time())))
        })

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'success': True, 'language': lang})
        }
    except Exception as e:
        return _error_response(500, f'Failed to update prompt: {str(e)}')


def _get_fallbacks(lang: str, request_id: str) -> Dict[str, Any]:
    """Get language-specific fallback messages."""
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)

        if lang:
            response = config_table.get_item(Key={'id': f'ai_fallback_{lang}'})
            if 'Item' in response:
                fallback = response['Item'].get('configValue', '')
                return {
                    'statusCode': 200,
                    'headers': cors_headers(origin),
                    'body': json.dumps({'language': lang, 'fallback': fallback})
                }
            return {
                'statusCode': 200,
                'headers': cors_headers(origin),
                'body': json.dumps({'language': lang, 'fallback': _get_default_fallback(lang)})
            }

        fallbacks = {}
        for lang_code in SUPPORTED_LANGUAGES.keys():
            response = config_table.get_item(Key={'id': f'ai_fallback_{lang_code}'})
            if 'Item' in response:
                fallbacks[lang_code] = response['Item'].get('configValue', '')
            else:
                fallbacks[lang_code] = _get_default_fallback(lang_code)

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'fallbacks': fallbacks})
        }
    except Exception as e:
        return _error_response(500, f'Failed to get fallbacks: {str(e)}')


def _update_fallback(lang: str, body: Dict, request_id: str) -> Dict[str, Any]:
    """Update language-specific fallback message."""
    if not lang:
        return _error_response(400, 'Language code is required')

    fallback = body.get('fallback', '')
    if not fallback:
        return _error_response(400, 'Fallback message is required')

    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        config_table.put_item(Item={
            'id': f'ai_fallback_{lang}',
            'configValue': fallback,
            'updatedAt': Decimal(str(int(time.time())))
        })

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'success': True, 'language': lang})
        }
    except Exception as e:
        return _error_response(500, f'Failed to update fallback: {str(e)}')


def _get_interactions(query_params: Dict, request_id: str) -> Dict[str, Any]:
    """Get AI interaction logs."""
    try:
        ai_table = dynamodb.Table(AI_INTERACTIONS_TABLE)
        limit = int(query_params.get('limit', 50))
        
        interactions = []
        scan_kwargs = {}
        while True:
            response = ai_table.scan(**scan_kwargs)
            interactions.extend(response.get('Items', []))
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        # Sort by timestamp descending
        interactions.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
        # Limit results after sorting
        interactions = interactions[:limit]
        
        # Convert Decimal to int for JSON serialization
        for item in interactions:
            if 'timestamp' in item:
                item['timestamp'] = int(item['timestamp'])
        
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'interactions': interactions, 'count': len(interactions)})
        }
    except Exception as e:
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'interactions': [], 'count': 0, 'error': str(e)})
        }


def _get_stats(request_id: str) -> Dict[str, Any]:
    """Get AI usage statistics."""
    try:
        ai_table = dynamodb.Table(AI_INTERACTIONS_TABLE)
        
        # Scan all interactions for stats with pagination
        interactions = []
        scan_kwargs = {}
        while True:
            response = ai_table.scan(**scan_kwargs)
            interactions.extend(response.get('Items', []))
            if 'LastEvaluatedKey' not in response:
                break
            scan_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        total = len(interactions)
        approved = sum(1 for i in interactions if i.get('approved'))
        
        # Calculate by language (if tracked)
        by_language = {}
        for item in interactions:
            lang = item.get('detectedLanguage', 'unknown')
            by_language[lang] = by_language.get(lang, 0) + 1
        
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'totalInteractions': total,
                'approvedResponses': approved,
                'approvalRate': round(approved / total * 100, 1) if total > 0 else 0,
                'byLanguage': by_language
            })
        }
    except Exception as e:
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({
                'totalInteractions': 0,
                'approvedResponses': 0,
                'approvalRate': 0,
                'byLanguage': {},
                'error': str(e)
            })
        }


def _get_languages(request_id: str) -> Dict[str, Any]:
    """Get supported languages."""
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'languages': SUPPORTED_LANGUAGES})
    }


def _test_ai_response(body: Dict, request_id: str) -> Dict[str, Any]:
    """Refuse an unconfigured test rather than fabricate a generated response."""
    if not isinstance(body.get('message'), str) or not body['message'].strip():
        return _error_response(400, 'Message is required')
    return _error_response(501, 'AI response testing is not configured. Use the internal assistant to test permitted read capabilities.')


def _get_default_prompt(lang: str) -> str:
    """Get default prompt template for language."""
    lang_name = SUPPORTED_LANGUAGES.get(lang, 'English')
    return f"""You are WECARE.DIGITAL's friendly AI assistant.

CRITICAL: You MUST respond ONLY in {lang_name}. Do not mix languages.

INSTRUCTIONS:
- Respond ONLY in {lang_name} language
- Keep responses SHORT (2-3 sentences max)
- Use 1-2 emojis for warmth
- Always mention the specific brand name
- End with a clear action (website, phone, or next step)

BRANDS:
- Travel/Hotels/Visa → BNB Club (wecare.digital/elsewhere/)
- Documents/Registration/GST → Legal Champ (wecare.digital/dastavez/)
- Disputes/Complaints → No Fault (wecare.digital/clear-closure/)
- Puja/Rituals → Ritual Guru (wecare.digital/ritual-guru/)
- Self-inquiry/Reflection → Swdhya (wecare.digital/anew/)

CONTACT: +91 9330994400 | one@wecare.digital"""


def _get_default_fallback(lang: str) -> str:
    """Get default fallback message for language."""
    fallbacks = {
        'en': "Hi! 👋 Thanks for reaching out to WECARE.DIGITAL. For quick help, call us at +91 9330994400 or email one@wecare.digital. We're here to help! 😊",
        'hi': "नमस्ते! 👋 WECARE.DIGITAL से संपर्क करने के लिए धन्यवाद। त्वरित सहायता के लिए +91 9330994400 पर कॉल करें या one@wecare.digital पर ईमेल करें। 😊",
        'hi-Latn': "Hi! 👋 WECARE.DIGITAL se contact karne ke liye thanks. Quick help ke liye +91 9330994400 pe call karein ya one@wecare.digital pe email karein. 😊",
        'bn': "নমস্কার! 👋 WECARE.DIGITAL-এ যোগাযোগ করার জন্য ধন্যবাদ। দ্রুত সাহায্যের জন্য +91 9330994400-এ কল করুন বা one@wecare.digital-এ ইমেল করুন। 😊",
        'ta': "வணக்கம்! 👋 WECARE.DIGITAL-ஐ தொடர்பு கொண்டதற்கு நன்றி। விரைவான உதவிக்கு +91 9330994400 அழைக்கவும் அல்லது one@wecare.digital மின்னஞ்சல் அனுப்பவும். 😊",
        'te': "నమస్కారం! 👋 WECARE.DIGITAL ని సంప్రదించినందుకు ధన్యవాదాలు। త్వరిత సహాయం కోసం +91 9330994400 కు కాల్ చేయండి లేదా one@wecare.digital కు ఇమెయిల్ చేయండి. 😊",
        'gu': "નમસ્તે! 👋 WECARE.DIGITAL નો સંપર્ક કરવા બદલ આભાર. ઝડપી મદદ માટે +91 9330994400 પર કૉલ કરો અથવા one@wecare.digital પર ઇમેઇલ કરો. 😊",
        'mr': "नमस्कार! 👋 WECARE.DIGITAL शी संपर्क साधल्याबद्दल धन्यवाद। जलद मदतीसाठी +91 9330994400 वर कॉल करा किंवा one@wecare.digital वर ईमेल करा. 😊",
    }
    return fallbacks.get(lang, fallbacks['en'])


def _error_response(status_code: int, message: str) -> Dict[str, Any]:
    """Return error response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps({'error': message})
    }


# ============================================================================
# INTERNAL AI CONFIG (FloatingAgent - Admin Tasks)
# ============================================================================

# Default Internal AI configuration
DEFAULT_INTERNAL_AI_CONFIG = {
    'enabled': True,
    # No agent, alias or knowledge-base id. Re-measured 2026-09-23: the account's
    # only Bedrock Agent is an empty never-prepared shell (no model, 0-character
    # instruction, null role, 0 action groups) and the account holds 0 knowledge
    # bases. The values previously here - '4UUQYFWX64' / 'TSTALIASID' /
    # 'static-faq' - named nothing, and this config is returned by an API and
    # rendered in the dashboard, so they read as working configuration.
    # Empty means not configured, which is the truth. See plan item 6.4.
    'agentId': '',
    'agentAlias': '',
    'knowledgeBaseId': '',
    'modelId': 'amazon.nova-pro-v1:0',
    'maxTokens': 1024,
    'temperature': 0.7,
    'systemPrompt': '''You are WECARE.DIGITAL's internal admin assistant.
Help operators with:
- Finding contacts and reviewing message history
- Explaining requests that need a human operator
- Checking message statistics
- Answering questions about the platform''',
}


def _get_internal_config(request_id: str) -> Dict[str, Any]:
    """Read saved preferences and the executor's effective tool authority.

    Preferences never enable a governed tool. This GET must not create a config
    row, and a failed read must not look like a successful settings response.
    """
    try:
        response = dynamodb.Table(SYSTEM_CONFIG_TABLE).get_item(Key={'id': 'ai_internal_config'})
        value = response.get('Item', {}).get('configValue')
        config = DEFAULT_INTERNAL_AI_CONFIG.copy() if value is None else (
            json.loads(value) if isinstance(value, str) else value)
        if not isinstance(config, dict):
            raise ValueError('Stored internal configuration must be an object')
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'config': config,
                                'toolCapabilities': gov.catalog_summary(gov.SURFACE_INTERNAL)})
        }
    except Exception:
        logger.warning('Internal AI configuration read failed: %s', request_id)
        return _error_response(503, 'Internal agent settings are temporarily unavailable')


def _update_internal_config(body: Dict, request_id: str) -> Dict[str, Any]:
    """Update Internal AI configuration (FloatingAgent)."""
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)

        response = config_table.get_item(Key={'id': 'ai_internal_config'})
        if 'Item' in response:
            existing = json.loads(response['Item'].get('configValue', '{}'))
        else:
            existing = DEFAULT_INTERNAL_AI_CONFIG.copy()

        for key, value in body.items():
            if key in DEFAULT_INTERNAL_AI_CONFIG:
                existing[key] = value

        config_table.put_item(Item={
            'id': 'ai_internal_config',
            'configValue': json.dumps(existing),
            'updatedAt': Decimal(str(int(time.time())))
        })

        logger.info(json.dumps({
            'event': 'internal_ai_config_updated',
            'enabled': existing.get('enabled'),
            'requestId': request_id
        }))

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'success': True, 'config': existing})
        }
    except Exception as e:
        return _error_response(500, f'Failed to update internal config: {str(e)}')


# Bot flow config keys stored in SystemConfigTable (using 'id' as PK for compatibility with inbound handler)
BOT_FLOW_CONFIG_KEYS = [
    'welcome_message_config',
    'bot_options_config',
    'bot_rating_config',
    'bot_language_picker_config',
    'bot_flow_config',
]


def _get_botflow_config(request_id: str) -> Dict[str, Any]:
    """Get all bot flow configs from SystemConfigTable."""
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        configs = {}

        for key in BOT_FLOW_CONFIG_KEYS:
            try:
                response = config_table.get_item(Key={'id': key})
                if 'Item' in response:
                    raw = response['Item'].get('configValue', '{}')
                    configs[key] = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                continue

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'configs': configs})
        }
    except Exception as e:
        logger.error(f'Failed to get bot flow config: {str(e)}')
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'configs': {}})
        }


def _update_botflow_config(body: Dict, request_id: str) -> Dict[str, Any]:
    """Update bot flow configs in SystemConfigTable."""
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        config_key = body.get('configKey', '')
        config_value = body.get('configValue', {})

        if not config_key or config_key not in BOT_FLOW_CONFIG_KEYS:
            return _error_response(400, f'Invalid configKey. Must be one of: {BOT_FLOW_CONFIG_KEYS}')

        # Store using 'id' as PK (matches inbound handler pattern)
        config_table.put_item(Item={
            'id': config_key,
            'configValue': json.dumps(config_value) if isinstance(config_value, dict) else str(config_value),
            'updatedAt': Decimal(str(int(time.time())))
        })

        logger.info(json.dumps({
            'event': 'botflow_config_updated',
            'configKey': config_key,
            'requestId': request_id
        }))

        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'success': True, 'configKey': config_key})
        }
    except Exception as e:
        return _error_response(500, f'Failed to update bot flow config: {str(e)}')


def _delete_botflow_configs(request_id: str) -> Dict[str, Any]:
    """Delete all bot flow configs from SystemConfigTable (reset to Lambda defaults)."""
    try:
        config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
        deleted = []
        for key in BOT_FLOW_CONFIG_KEYS:
            try:
                config_table.delete_item(Key={'id': key})
                deleted.append(key)
            except Exception as e:
                logger.warning(f'Config key delete failed for {key}: {e}')
        logger.info(json.dumps({
            'event': 'botflow_configs_reset',
            'deleted': deleted,
            'requestId': request_id
        }))
        return {
            'statusCode': 200,
            'headers': cors_headers(origin),
            'body': json.dumps({'success': True, 'deleted': deleted})
        }
    except Exception as e:
        return _error_response(500, f'Failed to reset bot flow configs: {str(e)}')


def _clear_ai_logs(request_id: str) -> Dict[str, Any]:
    """Clear AI Interactions and Conversation History tables."""
    ddb_client = boto3.client('dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
    results = {}
    total = 0

    for label, table_name in [('ai_interactions', AI_INTERACTIONS_TABLE), ('conversation_history', CONVERSATION_HISTORY_TABLE)]:
        try:
            desc = ddb_client.describe_table(TableName=table_name)
            key_names = [k['AttributeName'] for k in desc['Table']['KeySchema']]
            table = dynamodb.Table(table_name)
            deleted = 0
            scan_kwargs = {
                'ProjectionExpression': ', '.join([f'#{chr(97+i)}' for i in range(len(key_names))]),
                'ExpressionAttributeNames': {f'#{chr(97+i)}': n for i, n in enumerate(key_names)}
            }
            while True:
                resp = table.scan(**scan_kwargs)
                items = resp.get('Items', [])
                if not items:
                    break
                with table.batch_writer() as batch:
                    for item in items:
                        batch.delete_item(Key={k: item[k] for k in key_names})
                        deleted += 1
                if 'LastEvaluatedKey' not in resp:
                    break
                scan_kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
            results[label] = deleted
            total += deleted
        except Exception as e:
            logger.warning(f"Clear {label} error: {e}")
            results[label] = 0

    logger.info(json.dumps({'event': 'clear_ai_logs', 'results': results, 'total': total, 'requestId': request_id}))
    return {
        'statusCode': 200,
        'headers': cors_headers(origin),
        'body': json.dumps({'success': True, 'results': results, 'totalDeleted': total})
    }
