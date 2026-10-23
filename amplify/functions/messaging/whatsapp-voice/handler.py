"""
WhatsApp Voice Lambda Function

Purpose: Generate TTS audio via Amazon Polly, transcribe voice notes via Amazon Transcribe,
         and send as WhatsApp audio messages. Full multi-language support with English translation.
Uses: Amazon Polly (TTS) + Amazon Transcribe (STT) + Amazon Translate + Meta Graph API (Direct API) + S3 (storage)

Endpoints:
  POST   /whatsapp-voice/tts             - Generate TTS and send as WhatsApp audio
  POST   /whatsapp-voice/send            - Send existing audio file as WhatsApp message
  POST   /whatsapp-voice/transcribe      - Transcribe voice note from S3 (returns English text)
  GET    /whatsapp-voice/voices          - List available Polly voices
  GET    /whatsapp-voice/language-config  - Get voice language configuration
  PUT    /whatsapp-voice/language-config  - Update voice language configuration
  GET    /whatsapp-voice/logs            - List sent voice messages
  DELETE /whatsapp-voice/clear-logs      - Clear all logs
"""

import os
import json
import uuid
import time
import logging
import base64
import hmac
import hashlib
import boto3
import urllib.request
import urllib.error
from typing import Dict, Any, Optional
from decimal import Decimal

from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated
from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.validation import normalize_phone
from lambda_utils.privacy import mask_phone  # a full number must never reach CloudWatch

from lambda_utils.logging import get_logger

logger = get_logger(__name__)

REGION = os.environ.get('AWS_REGION', 'us-east-1')
dynamodb = boto3.resource('dynamodb', region_name=REGION)
polly = boto3.client('polly', region_name=REGION)
s3 = boto3.client('s3', region_name=REGION)
transcribe = boto3.client('transcribe', region_name=REGION)

# Environment
CONTACTS_TABLE = os.environ.get('CONTACTS_TABLE', 'stack-wecare-digital-ContactsTable')
MESSAGES_TABLE = os.environ.get('MESSAGES_TABLE', 'stack-wecare-digital-WhatsAppOutboundTable')
VOICE_LOG_TABLE = os.environ.get('VOICE_LOG_TABLE', 'stack-wecare-digital-WhatsAppVoiceTable')
INBOUND_TABLE = os.environ.get('INBOUND_TABLE', 'stack-wecare-digital-WhatsAppInboundTable')
UNIFIED_MESSAGES_TABLE = os.environ.get('UNIFIED_MESSAGES_TABLE', 'stack-wecare-digital-MessagesTable')
SYSTEM_CONFIG_TABLE = os.environ.get('SYSTEM_CONFIG_TABLE', 'stack-wecare-digital-SystemConfigTable')
MEDIA_BUCKET = os.environ.get('MEDIA_BUCKET', media_paths.BUCKET)
MEDIA_PREFIX = os.environ.get('MEDIA_PREFIX',
                              media_paths.deliverable_public('whatsapp/voice/'))
# Amazon Transcribe writes its result straight into the bucket, so the OutputKey
# needs the same root as everything else or the job lands outside the served tree.
TRANSCRIPTION_PREFIX = media_paths.deliverable_public('whatsapp/transcriptions/')

# WhatsApp Phone Number IDs
PHONE_NUMBER_ID_1 = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_1',
    'phone-number-id-waba1-direct-1016149501586345')
PHONE_NUMBER_ID_2 = os.environ.get('WHATSAPP_PHONE_NUMBER_ID_2',
    'phone-number-id-waba-t-direct-1055232054343117')

# Direct API phone IDs and their Meta phone IDs
DIRECT_API_PHONES = {
    PHONE_NUMBER_ID_1: '1016149501586345',
    PHONE_NUMBER_ID_2: '1055232054343117',
}

# Token cache for Direct API
_voice_token_cache = {}
secrets_client = boto3.client('secretsmanager', region_name=REGION)

def _load_voice_token() -> str:
    """Load Meta access token for Direct API calls."""
    if 'token' in _voice_token_cache:
        return _voice_token_cache['token']
    resp = secrets_client.get_secret_value(SecretId='wecare/meta-system-user-token')
    data = json.loads(resp['SecretString'])
    _voice_token_cache['token'] = (data.get('access_token') or '').strip()
    _voice_token_cache['app_secret'] = (data.get('app_secret') or '').strip()
    return _voice_token_cache['token']

from lambda_utils.meta_version import META_API_VERSION  # one source; validated at import
TTL_SECONDS = 90 * 24 * 60 * 60  # 90 days


# Polly voices grouped by language
POLLY_VOICES = {
    'en-IN': [
        {'id': 'Kajal', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Raveena', 'gender': 'Female', 'engine': 'standard'},
    ],
    'en-US': [
        {'id': 'Joanna', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Matthew', 'gender': 'Male', 'engine': 'neural'},
        {'id': 'Ivy', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Kendra', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Salli', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Joey', 'gender': 'Male', 'engine': 'neural'},
        {'id': 'Ruth', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Stephen', 'gender': 'Male', 'engine': 'neural'},
    ],
    'en-GB': [
        {'id': 'Amy', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Emma', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Brian', 'gender': 'Male', 'engine': 'neural'},
        {'id': 'Arthur', 'gender': 'Male', 'engine': 'neural'},
    ],
    'hi-IN': [
        {'id': 'Kajal', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Aditi', 'gender': 'Female', 'engine': 'standard'},
    ],
    'arb': [
        {'id': 'Zeina', 'gender': 'Female', 'engine': 'standard'},
        {'id': 'Hala', 'gender': 'Female', 'engine': 'neural'},
    ],
    'es-US': [
        {'id': 'Lupe', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Pedro', 'gender': 'Male', 'engine': 'neural'},
    ],
    'fr-FR': [
        {'id': 'Lea', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Remi', 'gender': 'Male', 'engine': 'neural'},
    ],
    'de-DE': [
        {'id': 'Vicki', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Daniel', 'gender': 'Male', 'engine': 'neural'},
    ],
    'ja-JP': [
        {'id': 'Kazuha', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Takumi', 'gender': 'Male', 'engine': 'neural'},
    ],
    'ko-KR': [
        {'id': 'Seoyeon', 'gender': 'Female', 'engine': 'neural'},
    ],
    'pt-BR': [
        {'id': 'Camila', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Thiago', 'gender': 'Male', 'engine': 'neural'},
    ],
    'cmn-CN': [
        {'id': 'Zhiyu', 'gender': 'Female', 'engine': 'neural'},
    ],
    'it-IT': [
        {'id': 'Bianca', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Adriano', 'gender': 'Male', 'engine': 'neural'},
    ],
    'tr-TR': [
        {'id': 'Burcu', 'gender': 'Female', 'engine': 'neural'},
    ],
    'ru-RU': [
        {'id': 'Tatyana', 'gender': 'Female', 'engine': 'standard'},
        {'id': 'Maxim', 'gender': 'Male', 'engine': 'standard'},
    ],
    'nl-NL': [
        {'id': 'Laura', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Lotte', 'gender': 'Female', 'engine': 'standard'},
    ],
    'pl-PL': [
        {'id': 'Ola', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Jacek', 'gender': 'Male', 'engine': 'standard'},
    ],
    'sv-SE': [
        {'id': 'Elin', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Astrid', 'gender': 'Female', 'engine': 'standard'},
    ],
    'da-DK': [
        {'id': 'Sofie', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Naja', 'gender': 'Female', 'engine': 'standard'},
    ],
    'nb-NO': [
        {'id': 'Ida', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Liv', 'gender': 'Female', 'engine': 'standard'},
    ],
    'ca-ES': [
        {'id': 'Arlet', 'gender': 'Female', 'engine': 'neural'},
    ],
    'cy-GB': [
        {'id': 'Gwyneth', 'gender': 'Female', 'engine': 'standard'},
    ],
    'fi-FI': [
        {'id': 'Suvi', 'gender': 'Female', 'engine': 'neural'},
    ],
    'ro-RO': [
        {'id': 'Carmen', 'gender': 'Female', 'engine': 'standard'},
    ],
    'es-ES': [
        {'id': 'Lucia', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Sergio', 'gender': 'Male', 'engine': 'neural'},
    ],
    'es-MX': [
        {'id': 'Mia', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Andres', 'gender': 'Male', 'engine': 'neural'},
    ],
    'pt-PT': [
        {'id': 'Ines', 'gender': 'Female', 'engine': 'neural'},
    ],
    'fr-CA': [
        {'id': 'Gabrielle', 'gender': 'Female', 'engine': 'neural'},
        {'id': 'Liam', 'gender': 'Male', 'engine': 'neural'},
    ],
    'en-AU': [
        {'id': 'Olivia', 'gender': 'Female', 'engine': 'neural'},
    ],
    'en-NZ': [
        {'id': 'Aria', 'gender': 'Female', 'engine': 'neural'},
    ],
    'en-ZA': [
        {'id': 'Ayanda', 'gender': 'Female', 'engine': 'neural'},
    ],
}


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle WhatsApp voice/TTS operations."""
    request_id = context.aws_request_id if context else 'local'
    global origin
    origin = extract_origin(event)
    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'POST')
    path = event.get('rawPath', event.get('path', ''))
    query_params = event.get('queryStringParameters') or {}

    logger.info(json.dumps({
        'event': 'whatsapp_voice_handler',
        'method': http_method, 'path': path, 'requestId': request_id
    }))

    try:
        if http_method == 'OPTIONS':
            return _response(200, {'message': 'OK'})

        from lambda_utils.middleware import require_auth
        required_role = 'Admin' if http_method in ('POST', 'PUT', 'DELETE') else None
        _auth = require_auth(event, required_role=required_role)
        if _auth is not None:
            return _auth

        # DELETE /whatsapp-voice/clear-logs
        if http_method == 'DELETE' and 'clear-logs' in path:
            return _clear_logs(request_id)

        # GET/PUT /whatsapp-voice/language-config
        if 'language-config' in path:
            body = json.loads(event.get('body', '{}')) if http_method == 'PUT' else {}
            return _handle_language_config(http_method, body, request_id)

        # GET /whatsapp-voice/voices
        if http_method == 'GET' and 'voices' in path:
            return _list_voices()

        # GET /whatsapp-voice/logs
        if http_method == 'GET':
            return _list_logs(query_params, request_id)

        # POST /whatsapp-voice/tts
        if http_method == 'POST' and 'tts' in path:
            body = json.loads(event.get('body', '{}'))
            return _handle_tts(body, request_id)

        # POST /whatsapp-voice/transcribe
        if http_method == 'POST' and 'transcribe' in path:
            body = json.loads(event.get('body', '{}'))
            return _handle_transcribe(body, request_id)

        # POST /whatsapp-voice/send (send existing audio)
        if http_method == 'POST':
            body = json.loads(event.get('body', '{}'))
            return _handle_send_audio(body, request_id)

        return _response(405, {'error': 'Method not allowed'})

    except json.JSONDecodeError:
        return _response(400, {'error': 'Invalid JSON'})
    except Exception as e:
        logger.error(f"WhatsApp voice error: {str(e)}", exc_info=True)
        return _response(500, {'error': 'Internal server error'})


def _handle_tts(body: Dict, request_id: str) -> Dict[str, Any]:
    """Generate TTS via Polly and send as WhatsApp audio message."""
    contact_id = body.get('contactId', '')
    phone_number = body.get('phoneNumber')
    message_text = body.get('messageText', '')
    voice_id = body.get('voiceId', 'Kajal')
    language_code = body.get('languageCode', 'en-IN')
    engine = body.get('engine', 'neural')
    phone_number_id = body.get('phoneNumberId', PHONE_NUMBER_ID_1)
    recipient_bsuid = body.get('recipientBsuid', '')

    if not message_text:
        return _response(400, {'error': 'messageText is required'})

    # Normalize phone input to consistent digits-only format
    if phone_number:
        normalized = normalize_phone(phone_number)
        if normalized:
            phone_number = f'+{normalized}'

    # Resolve phone number from contact if needed
    if not phone_number and contact_id:
        contact = _get_contact(contact_id)
        phone_number = contact.get('phone') if contact else None

    if not phone_number:
        return _response(400, {'error': 'phoneNumber or contactId required'})

    phone_e164 = _format_phone(phone_number)
    if not phone_e164:
        return _response(400, {'error': 'Invalid phone number'})

    msg_id = str(uuid.uuid4())

    try:
        # Step 1: Generate TTS audio via Polly (OGG Vorbis for WhatsApp)
        logger.info(json.dumps({
            'event': 'polly_synthesize',
            'voiceId': voice_id, 'language': language_code,
            'engine': engine, 'textLength': len(message_text)
        }))

        # Use SSML for better control
        ssml_text = f'<speak><prosody rate="medium">{message_text}</prosody></speak>'

        polly_response = polly.synthesize_speech(
            Text=ssml_text,
            TextType='ssml',
            OutputFormat='mp3',
            VoiceId=voice_id,
            Engine=engine,
            LanguageCode=language_code,
        )

        audio_stream = polly_response['AudioStream'].read()
        audio_size = len(audio_stream)

        logger.info(json.dumps({
            'event': 'polly_success',
            'audioSize': audio_size,
            'contentType': polly_response.get('ContentType', '')
        }))

        # Step 2: Upload to S3
        s3_key = f"{MEDIA_PREFIX}wecare-digital-{msg_id[:8]}.mp3"
        s3.put_object(
            Bucket=MEDIA_BUCKET,
            Key=s3_key,
            Body=audio_stream,
            ContentType='audio/mpeg',
            Metadata={
                'voiceId': voice_id,
                'language': language_code,
                'messageText': message_text[:200],
                'contactId': contact_id,
            }
        )

        logger.info(json.dumps({
            'event': 's3_upload_success',
            'bucket': MEDIA_BUCKET, 's3Key': s3_key
        }))

        # Step 3: Upload to WhatsApp via Direct API PostWhatsAppMessageMedia
        media_id = _upload_to_whatsapp(s3_key, phone_number_id, request_id)

        if not media_id:
            return _response(500, {
                'error': 'Failed to upload audio to WhatsApp',
                'messageId': msg_id, 's3Key': s3_key
            })

        # Step 4: Send WhatsApp audio message
        wa_message_id = _send_whatsapp_audio(
            phone_e164, media_id, phone_number_id, request_id,
            recipient_bsuid=recipient_bsuid
        )

        # Step 5: Store log
        now = int(time.time())
        _store_log({
            'messageId': msg_id,
            'contactId': contact_id,
            'phoneNumber': phone_e164,
            'recipientBsuid': recipient_bsuid or None,
            'messageText': message_text[:500],
            'voiceId': voice_id,
            'languageCode': language_code,
            'engine': engine,
            'audioSize': audio_size,
            's3Key': s3_key,
            'whatsappMediaId': media_id,
            'whatsappMessageId': wa_message_id or '',
            'phoneNumberId': phone_number_id,
            'status': 'sent' if wa_message_id else 'failed',
            'type': 'tts',
            'transcription': message_text,
            'detectedLanguage': language_code,
            'createdAt': Decimal(str(now)),
            'expiresAt': Decimal(str(now + TTL_SECONDS)),
        })

        # Step 6: Also store in messages table for inbox display
        _store_message_record(
            msg_id, contact_id, f'[Voice Note] {message_text[:100]}',
            'sent' if wa_message_id else 'failed',
            phone_number_id, phone_e164, s3_key, wa_message_id,
            transcription=message_text,  # TTS text is the transcription
            language_code=language_code,
        )

        return _response(200, {
            'success': True,
            'messageId': msg_id,
            'whatsappMessageId': wa_message_id,
            's3Key': s3_key,
            'audioSize': audio_size,
            'voiceId': voice_id,
            'status': 'sent' if wa_message_id else 'upload_only'
        })

    except polly.exceptions.InvalidSsmlException as e:
        # Retry without SSML
        logger.warning(f"SSML failed, retrying plain text: {str(e)}")
        try:
            polly_response = polly.synthesize_speech(
                Text=message_text,
                TextType='text',
                OutputFormat='mp3',
                VoiceId=voice_id,
                Engine=engine,
                LanguageCode=language_code,
            )
            audio_stream = polly_response['AudioStream'].read()
            s3_key = f"{MEDIA_PREFIX}wecare-digital-{msg_id[:8]}.mp3"
            s3.put_object(
                Bucket=MEDIA_BUCKET, Key=s3_key,
                Body=audio_stream, ContentType='audio/mpeg'
            )
            media_id = _upload_to_whatsapp(s3_key, phone_number_id, request_id)
            wa_message_id = _send_whatsapp_audio(
                phone_e164, media_id, phone_number_id, request_id,
                recipient_bsuid=recipient_bsuid
            ) if media_id else None

            now = int(time.time())
            _store_log({
                'messageId': msg_id, 'contactId': contact_id,
                'phoneNumber': phone_e164, 'recipientBsuid': recipient_bsuid or None,
                'messageText': message_text[:500],
                'voiceId': voice_id, 'languageCode': language_code,
                's3Key': s3_key, 'whatsappMediaId': media_id or '',
                'whatsappMessageId': wa_message_id or '',
                'status': 'sent' if wa_message_id else 'failed',
                'type': 'tts', 'transcription': message_text,
                'detectedLanguage': language_code,
                'createdAt': Decimal(str(now)),
                'expiresAt': Decimal(str(now + TTL_SECONDS)),
            })
            return _response(200, {
                'success': True, 'messageId': msg_id,
                'whatsappMessageId': wa_message_id, 's3Key': s3_key
            })
        except Exception as e2:
            logger.error(f"Polly plain text also failed: {str(e2)}")
            return _response(500, {'error': f'TTS failed: {str(e2)}'})

    except Exception as e:
        logger.error(f"TTS error: {str(e)}", exc_info=True)
        return _response(500, {'error': str(e)})


def _handle_send_audio(body: Dict, request_id: str) -> Dict[str, Any]:
    """Send an existing audio file (from S3 or base64) as WhatsApp audio message."""
    contact_id = body.get('contactId', '')
    phone_number = body.get('phoneNumber')
    phone_number_id = body.get('phoneNumberId', PHONE_NUMBER_ID_1)
    s3_key = body.get('s3Key')
    audio_base64 = body.get('audioBase64')
    content_type = body.get('contentType', 'audio/ogg')
    recipient_bsuid = body.get('recipientBsuid', '')

    # Normalize phone input
    if phone_number:
        normalized = normalize_phone(phone_number)
        if normalized:
            phone_number = f'+{normalized}'

    if not phone_number and contact_id:
        contact = _get_contact(contact_id)
        phone_number = contact.get('phone') if contact else None

    if not phone_number:
        return _response(400, {'error': 'phoneNumber or contactId required'})

    phone_e164 = _format_phone(phone_number)
    msg_id = str(uuid.uuid4())

    try:
        # If base64 audio provided, upload to S3 first
        if audio_base64 and not s3_key:
            ext = 'ogg' if 'ogg' in content_type else 'mp3'
            s3_key = f"{MEDIA_PREFIX}wecare-digital-{msg_id[:8]}.{ext}"
            audio_bytes = base64.b64decode(audio_base64)
            s3.put_object(
                Bucket=MEDIA_BUCKET, Key=s3_key,
                Body=audio_bytes, ContentType=content_type,
                Metadata={'contactId': contact_id, 'type': 'recording'}
            )

        if not s3_key:
            return _response(400, {'error': 's3Key or audioBase64 required'})

        # Upload to WhatsApp
        media_id = _upload_to_whatsapp(s3_key, phone_number_id, request_id)
        if not media_id:
            return _response(500, {'error': 'Failed to upload to WhatsApp'})

        # Send audio message
        wa_message_id = _send_whatsapp_audio(
            phone_e164, media_id, phone_number_id, request_id,
            recipient_bsuid=recipient_bsuid
        )

        now = int(time.time())
        _store_log({
            'messageId': msg_id, 'contactId': contact_id,
            'phoneNumber': phone_e164, 'recipientBsuid': recipient_bsuid or None,
            's3Key': s3_key,
            'whatsappMediaId': media_id,
            'whatsappMessageId': wa_message_id or '',
            'phoneNumberId': phone_number_id,
            'status': 'sent' if wa_message_id else 'failed',
            'type': 'recording',
            'createdAt': Decimal(str(now)),
            'expiresAt': Decimal(str(now + TTL_SECONDS)),
        })

        _store_message_record(
            msg_id, contact_id, '[Voice Recording]',
            'sent' if wa_message_id else 'failed',
            phone_number_id, phone_e164, s3_key, wa_message_id
        )

        return _response(200, {
            'success': True, 'messageId': msg_id,
            'whatsappMessageId': wa_message_id, 's3Key': s3_key
        })

    except Exception as e:
        logger.error(f"Send audio error: {str(e)}", exc_info=True)
        return _response(500, {'error': str(e)})


# ── Supported Transcribe language codes (Amazon Transcribe) ──
TRANSCRIBE_LANGUAGES = {
    'en-US': 'English (US)',
    'en-GB': 'English (UK)',
    'en-IN': 'English (Indian)',
    'hi-IN': 'Hindi',
    'ar-SA': 'Arabic',
    'es-US': 'Spanish (US)',
    'es-ES': 'Spanish (Spain)',
    'fr-FR': 'French',
    'de-DE': 'German',
    'ja-JP': 'Japanese',
    'ko-KR': 'Korean',
    'pt-BR': 'Portuguese (BR)',
    'zh-CN': 'Chinese (Mandarin)',
    'it-IT': 'Italian',
    'tr-TR': 'Turkish',
    'ru-RU': 'Russian',
    'nl-NL': 'Dutch',
    'pl-PL': 'Polish',
    'sv-SE': 'Swedish',
    'da-DK': 'Danish',
    'id-ID': 'Indonesian',
    'ms-MY': 'Malay',
    'th-TH': 'Thai',
    'vi-VN': 'Vietnamese',
    'ta-IN': 'Tamil',
    'te-IN': 'Telugu',
    'bn-IN': 'Bengali',
    'mr-IN': 'Marathi',
    'gu-IN': 'Gujarati',
    'kn-IN': 'Kannada',
    'ml-IN': 'Malayalam',
    'ur-IN': 'Urdu',
    'pa-IN': 'Punjabi',
}


def _handle_transcribe(body: Dict, request_id: str) -> Dict[str, Any]:
    """
    Transcribe a voice note from S3 using Amazon Transcribe.
    Returns English transcription + detected language.

    Supports two modes:
    1. s3Key provided — transcribe from existing S3 object
    2. messageId provided — look up s3Key from inbound/outbound tables, transcribe, and update record

    Always produces English text (uses auto language detection + translation if needed).
    """
    s3_key = body.get('s3Key', '')
    message_id = body.get('messageId', '')
    direction = body.get('direction', 'INBOUND')  # INBOUND or OUTBOUND
    source_table = None
    source_record = None

    # If messageId provided, look up s3Key from the appropriate table
    if message_id and not s3_key:
        try:
            if direction == 'INBOUND':
                table = dynamodb.Table(INBOUND_TABLE)
                result = table.get_item(Key={'id': message_id})
            else:
                table = dynamodb.Table(MESSAGES_TABLE)
                result = table.get_item(Key={'id': message_id})
            source_record = result.get('Item', {})
            s3_key = source_record.get('s3Key', '')
            source_table = table
        except Exception as e:
            logger.warning(f"Could not look up message {message_id}: {e}")

    if not s3_key:
        return _response(400, {'error': 's3Key or messageId required'})

    # Check if already transcribed (cached in record)
    if source_record and source_record.get('transcription'):
        return _response(200, {
            'transcription': source_record['transcription'],
            'detectedLanguage': source_record.get('detectedLanguage', ''),
            'cached': True,
            'messageId': message_id,
        })

    try:
        job_name = f"wecare-{uuid.uuid4().hex[:12]}"
        media_uri = f"s3://{MEDIA_BUCKET}/{s3_key}"

        logger.info(json.dumps({
            'event': 'transcribe_start',
            's3Key': s3_key,
            'jobName': job_name,
            'requestId': request_id,
        }))

        # Start transcription with auto language detection
        transcribe.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={'MediaFileUri': media_uri},
            IdentifyLanguage=True,
            LanguageOptions=list(TRANSCRIBE_LANGUAGES.keys()),
            OutputBucketName=MEDIA_BUCKET,
            OutputKey=f"{TRANSCRIPTION_PREFIX}{job_name}.json",
        )

        # Poll for completion (max ~60s for short voice notes)
        max_wait = 60
        poll_interval = 3
        elapsed = 0
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            status_resp = transcribe.get_transcription_job(TranscriptionJobName=job_name)
            job = status_resp['TranscriptionJob']
            status = job['TranscriptionJobStatus']

            if status == 'COMPLETED':
                break
            elif status == 'FAILED':
                reason = job.get('FailureReason', 'Unknown')
                logger.error(f"Transcription failed: {reason}")
                return _response(500, {'error': f'Transcription failed: {reason}'})

        if status != 'COMPLETED':
            return _response(504, {'error': 'Transcription timed out', 'jobName': job_name})

        # Read transcription result from S3
        result_key = f"{TRANSCRIPTION_PREFIX}{job_name}.json"
        result_obj = s3.get_object(Bucket=MEDIA_BUCKET, Key=result_key)
        result_data = json.loads(result_obj['Body'].read().decode('utf-8'))

        transcripts = result_data.get('results', {}).get('transcripts', [])
        transcript_text = transcripts[0].get('transcript', '') if transcripts else ''
        detected_lang = result_data.get('results', {}).get('language_code', '')

        logger.info(json.dumps({
            'event': 'transcribe_complete',
            'detectedLanguage': detected_lang,
            'transcriptLength': len(transcript_text),
            'jobName': job_name,
            'requestId': request_id,
        }))

        # If detected language is not English, translate to English
        english_text = transcript_text
        if detected_lang and not detected_lang.startswith('en'):
            try:
                translate_client = boto3.client('translate', region_name=REGION)
                # Map Transcribe lang code to Translate source code
                src_lang = detected_lang.split('-')[0]  # e.g. "hi-IN" -> "hi"
                translate_resp = translate_client.translate_text(
                    Text=transcript_text,
                    SourceLanguageCode=src_lang,
                    TargetLanguageCode='en',
                )
                english_text = translate_resp.get('TranslatedText', transcript_text)
                logger.info(json.dumps({
                    'event': 'translate_complete',
                    'sourceLanguage': src_lang,
                    'translatedLength': len(english_text),
                }))
            except Exception as te:
                logger.warning(f"Translation failed, using original: {te}")
                # Fall back to original transcript

        # Update the source record with transcription
        if source_table and message_id:
            try:
                key = {'id': message_id}
                source_table.update_item(
                    Key=key,
                    UpdateExpression='SET transcription = :t, detectedLanguage = :l',
                    ExpressionAttributeValues={
                        ':t': english_text,
                        ':l': detected_lang,
                    },
                )
            except Exception as ue:
                logger.warning(f"Could not update record with transcription: {ue}")

        # Also update the unified Messages table (messageId key)
        if message_id:
            try:
                msg_table = dynamodb.Table(UNIFIED_MESSAGES_TABLE)
                msg_table.update_item(
                    Key={'id': message_id},
                    UpdateExpression='SET transcription = :t, detectedLanguage = :l',
                    ExpressionAttributeValues={
                        ':t': english_text,
                        ':l': detected_lang,
                    },
                )
            except Exception as ue2:
                logger.warning(f"Could not update unified Messages table: {ue2}")

        # Clean up transcription output from S3 (optional, keep it small)
        try:
            s3.delete_object(Bucket=MEDIA_BUCKET, Key=result_key)
        except Exception as e:
            logger.debug(f"S3 transcription cleanup failed for {result_key}: {e}")

        return _response(200, {
            'transcription': english_text,
            'originalTranscription': transcript_text if english_text != transcript_text else None,
            'detectedLanguage': detected_lang,
            'messageId': message_id,
            'cached': False,
        })

    except Exception as e:
        logger.error(f"Transcribe error: {str(e)}", exc_info=True)
        return _response(500, {'error': str(e)})


def _handle_language_config(http_method: str, body: Dict, request_id: str) -> Dict[str, Any]:
    """
    GET: Return voice language configuration (enabled languages, default voices, auto-transcribe setting).
    PUT: Update voice language configuration.
    Stored in SystemConfigTable under key 'voice_language_config'.
    """
    config_table = dynamodb.Table(SYSTEM_CONFIG_TABLE)
    config_key = 'voice_language_config'

    if http_method == 'GET':
        try:
            result = config_table.get_item(Key={'id': config_key})
            item = result.get('Item', {})
            config_value = item.get('configValue', '{}')
            config = json.loads(config_value) if isinstance(config_value, str) else config_value
            # Merge with defaults
            defaults = {
                'autoTranscribe': True,
                'enabledLanguages': list(POLLY_VOICES.keys()),
                'defaultVoices': {lang: voices[0]['id'] for lang, voices in POLLY_VOICES.items()},
                'autoReplyWithVoice': False,
                'transcribeLanguages': list(TRANSCRIBE_LANGUAGES.keys()),
            }
            for k, v in defaults.items():
                if k not in config:
                    config[k] = v
            return _response(200, {'config': config})
        except Exception as e:
            logger.error(f"Get language config error: {e}")
            return _response(500, {'error': str(e)})

    # PUT — update config
    try:
        new_config = body.get('config', body)
        config_table.put_item(Item={
            'id': config_key,
            'configKey': config_key,
            'configValue': json.dumps(new_config, default=str),
            'updatedAt': str(int(time.time())),
        })
        return _response(200, {'success': True, 'config': new_config})
    except Exception as e:
        logger.error(f"Update language config error: {e}")
        return _response(500, {'error': str(e)})


def _upload_to_whatsapp(s3_key: str, phone_number_id: str,
                        request_id: str) -> Optional[str]:
    """Upload media to WhatsApp via Direct Meta API."""
    meta_phone_id = DIRECT_API_PHONES.get(phone_number_id)
    if not meta_phone_id:
        logger.error(f"No Direct API mapping for phone {phone_number_id}")
        return None
    # Direct API: download from S3, upload to Meta
    try:
        obj = s3.get_object(Bucket=MEDIA_BUCKET, Key=s3_key)
        media_bytes = obj['Body'].read()
        content_type = obj.get('ContentType', 'audio/ogg')
        
        token = _load_voice_token()
        app_secret = _voice_token_cache.get('app_secret', '')
        url = f"https://graph.facebook.com/{META_API_VERSION}/{meta_phone_id}/media"
        if app_secret:
            proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
            url = f"{url}?appsecret_proof={proof}"
        
        import io, email.mime.multipart
        boundary = 'wecareupload'
        body = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="messaging_product"\r\n\r\nwhatsapp\r\n'
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="type"\r\n\r\n{content_type}\r\n'
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="file"; filename="audio.ogg"\r\n'
            f'Content-Type: {content_type}\r\n\r\n'
        ).encode() + media_bytes + f'\r\n--{boundary}--\r\n'.encode()
        
        req = urllib.request.Request(url, data=body, headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': f'multipart/form-data; boundary={boundary}'
        }, method='POST')
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        media_id = result.get('id', '')
        logger.info(f"Direct API media upload: {media_id}")
        return media_id
    except Exception as e:
        logger.error(f"Direct API media upload error: {e}")
        return None


def _send_whatsapp_audio(phone: str, media_id: str,
                         phone_number_id: str,
                         request_id: str,
                         recipient_bsuid: str = '') -> Optional[str]:
    """Send audio message via Direct Meta API."""
    try:
        digits = ''.join(c for c in phone if c.isdigit())
        wa_payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': f'+{digits}',
            'type': 'audio',
            'audio': {'id': media_id}
        }
        if recipient_bsuid:
            wa_payload['recipient'] = recipient_bsuid

        meta_phone_id = DIRECT_API_PHONES.get(phone_number_id)
        if not meta_phone_id:
            logger.error(f"No Direct API mapping for phone {phone_number_id}")
            return None
        # Direct API
        token = _load_voice_token()
        app_secret = _voice_token_cache.get('app_secret', '')
        url = f"https://graph.facebook.com/{META_API_VERSION}/{meta_phone_id}/messages"
        if app_secret:
            proof = hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
            url = f"{url}?appsecret_proof={proof}"
        req = urllib.request.Request(url, data=json.dumps(wa_payload).encode(), headers={
            'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'
        }, method='POST')
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
        wa_msg_id = result.get('messages', [{}])[0].get('id', '')
        logger.info(json.dumps({
            'event': 'whatsapp_audio_sent',
            'messageId': wa_msg_id, 'to': mask_phone(phone)
        }))
        return wa_msg_id

    except Exception as e:
        logger.error(f"WhatsApp send error: {str(e)}")
        return None


def _list_voices() -> Dict[str, Any]:
    """Return available Polly voices grouped by language + transcribe languages."""
    return _response(200, {
        'voices': POLLY_VOICES,
        'transcribeLanguages': TRANSCRIBE_LANGUAGES,
    })


def _list_logs(params: Dict, request_id: str) -> Dict[str, Any]:
    """List WhatsApp voice message logs."""
    try:
        table = dynamodb.Table(VOICE_LOG_TABLE)
        limit = int(params.get('limit', 100))
        # Paginate then sort, so we return the true most-recent logs (a single
        # page + Limit would sort only an arbitrary first slice).
        items = []
        scan_kwargs = {}
        while True:
            result = table.scan(**scan_kwargs)
            items.extend(result.get('Items', []))
            if 'LastEvaluatedKey' not in result or len(items) >= 2000:
                break
            scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
        items.sort(key=lambda x: float(x.get('createdAt', 0)), reverse=True)
        items = items[:limit]
        return _response(200, {
            'logs': [_normalize_log(i) for i in items],
            'count': len(items)
        })
    except Exception as e:
        logger.error(f"List logs error: {str(e)}")
        return _response(500, {'error': str(e)})


def _clear_logs(request_id: str) -> Dict[str, Any]:
    """Clear all voice message logs (paginated to handle large tables)."""
    try:
        table = dynamodb.Table(VOICE_LOG_TABLE)
        deleted = 0
        scan_kwargs = {'ProjectionExpression': 'messageId'}
        while True:
            result = table.scan(**scan_kwargs)
            items = result.get('Items', [])
            if not items:
                break
            with table.batch_writer() as batch:
                for item in items:
                    batch.delete_item(Key={'messageId': item['messageId']})
                    deleted += 1
            if 'LastEvaluatedKey' not in result:
                break
            scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
        return _response(200, {'success': True, 'deletedCount': deleted})
    except Exception as e:
        logger.error(f"Clear logs error: {str(e)}")
        return _response(500, {'error': str(e)})


def _store_log(item: Dict) -> None:
    """Store voice message log."""
    try:
        table = dynamodb.Table(VOICE_LOG_TABLE)
        clean = {k: v for k, v in item.items() if v is not None and v != ''}
        table.put_item(Item=clean)
    except Exception as e:
        logger.error(f"Store log error: {str(e)}")


def _store_message_record(msg_id: str, contact_id: str, content: str,
                          status: str, phone_number_id: str,
                          recipient_phone: str, s3_key: str,
                          wa_message_id: Optional[str],
                          transcription: str = '',
                          language_code: str = '') -> None:
    """Store in messages table so it shows in WhatsApp inbox."""
    try:
        table = dynamodb.Table(MESSAGES_TABLE)
        now = int(time.time())
        item = {
            'id': msg_id,
            'messageId': msg_id,
            'contactId': contact_id,
            'content': content,
            'direction': 'OUTBOUND',
            'channel': 'whatsapp',
            'status': status,
            'messageType': 'audio',
            'mediaUrl': f"https://{MEDIA_BUCKET}.s3.amazonaws.com/{s3_key}",
            's3Key': s3_key,
            'whatsappMessageId': wa_message_id or '',
            'awsPhoneNumberId': phone_number_id,
            'recipientPhone': recipient_phone,
            'createdAt': Decimal(str(now)),
            'updatedAt': Decimal(str(now)),
            'expiresAt': Decimal(str(now + 30 * 24 * 60 * 60)),
        }
        if transcription:
            item['transcription'] = transcription
        if language_code:
            item['detectedLanguage'] = language_code
        table.put_item(Item=item)
    except Exception as e:
        logger.error(f"Store message error: {str(e)}")


def _normalize_log(item: Dict) -> Dict:
    """Normalize log record."""
    return {
        'messageId': item.get('messageId', ''),
        'contactId': item.get('contactId', ''),
        'phoneNumber': item.get('phoneNumber', ''),
        'messageText': item.get('messageText', ''),
        'voiceId': item.get('voiceId', ''),
        'languageCode': item.get('languageCode', ''),
        'audioSize': int(item.get('audioSize', 0)),
        's3Key': item.get('s3Key', ''),
        'whatsappMediaId': item.get('whatsappMediaId', ''),
        'whatsappMessageId': item.get('whatsappMessageId', ''),
        'status': item.get('status', ''),
        'type': item.get('type', 'tts'),
        'transcription': item.get('transcription', ''),
        'detectedLanguage': item.get('detectedLanguage', ''),
        'createdAt': int(float(item.get('createdAt', 0))),
    }


def _get_contact(contact_id: str) -> Dict:
    """Get contact from DynamoDB."""
    try:
        table = dynamodb.Table(CONTACTS_TABLE)
        # Table key is 'id', not 'contactId'
        result = table.get_item(Key={'id': contact_id})
        return result.get('Item', {})
    except Exception as e:
        logger.error(f"Get contact error: {str(e)}")
        return {}


def _format_phone(phone: str) -> str:
    """Format phone to E.164."""
    if not phone:
        return ''
    digits = ''.join(c for c in str(phone) if c.isdigit())
    if len(digits) == 10:
        return f'+91{digits}'
    if phone.startswith('+'):
        return phone
    return f'+{digits}' if digits else ''


def _response(status_code: int, body: Dict) -> Dict[str, Any]:
    """HTTP response with CORS."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps(body, default=str)
    }
