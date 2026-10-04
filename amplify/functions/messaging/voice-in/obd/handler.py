"""Legacy outbound-dialler campaign records, IVR prompt audio, and CDR ingestion.

    GET    /voice-in/obd                 list historical campaign records
    DELETE /voice-in/obd                 delete / clear records (retention)
    POST   /voice-in/obd                 CDR callback ingestion
    POST   /voice-in/obd/tts             Polly text-to-speech -> 8kHz mono PCM WAV
    GET    /voice-in/obd/audio-library   list IVR prompt audio in S3
    POST   /voice-in/obd/audio-library   upload IVR prompt audio to S3
    DELETE /voice-in/obd/audio-library   remove IVR prompt audio

RETIRED 2026-09-19, answering 410:

    /create  /status  /upload-csv  /upload-audio

Those created, populated and polled outbound dialler campaigns on a retired India
voice provider. Campaign dialling is an outbound-calling capability, and the
provider policy assigns PSTN voice to Plivo.

Deliberately retained, because neither is provider-specific and the voice
operations UI depends on both:

  * Polly text-to-speech, which produces the narrowband WAV the IVR needs;
  * the S3 prompt audio library.

Both previously also pushed a copy to the provider's prompt store on a
best-effort basis, and reported the vendor URL as the canonical `audioUrl` even
when that upload had quietly failed. S3 is now the only destination and `audioUrl`
is the S3 URL, so the value returned is one that actually exists.

Historical campaign records remain listable and deletable. Retired vendor
hostnames and credential identifiers are deliberately not repeated in this file,
so the provider-policy scan stays high-precision over runtime code.
See docs/provider-retirement-inventory.md.
"""

import os
import json
import uuid
import time
import logging
import boto3
import boto3.dynamodb.conditions
import base64
from typing import Dict, Any, List
from decimal import Decimal

from lambda_utils.response import cors_response, cors_headers, options_response, extract_origin
from lambda_utils.middleware import require_auth

# Configure logging
from lambda_utils.logging import get_logger
from lambda_utils.privacy import mask_contact_id  # contactId is `wa` + the customer's digits
# Imported for its import-time validation side effect, not for a value: the
# only read of META_API_VERSION here went with the deleted wd_menu send.
from lambda_utils.meta_version import META_API_VERSION  # noqa: F401
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated

logger = get_logger(__name__)

# AWS clients
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
s3 = boto3.client('s3', region_name=AWS_REGION)

# Environment variables
OBD_CAMPAIGNS_TABLE = os.environ.get('OBD_CAMPAIGNS_TABLE', 'stack-wecare-digital-OBDCampaigns')
VOICE_CDR_TABLE = os.environ.get('VOICE_CDR_TABLE', 'stack-wecare-digital-VoiceCDRTable')
S3_BUCKET = os.environ.get('S3_BUCKET', media_paths.BUCKET)
# The PUBLIC host, which is NOT the bucket name.
#
# Every audio URL below used to be built from the BUCKET name. That only
# worked because the old bucket was literally named app.wecare.digital, so its name
# doubled as a hostname. The bucket is now wecare-digital-get, which is not a
# domain, so interpolating it produced https://wecare-digital-get/... - a URL that
# resolves to nothing. Keep the two concepts separate: S3_BUCKET for API calls,
# CDN_DOMAIN for anything a caller will fetch.
CDN_DOMAIN = os.environ.get('CDN_DOMAIN', media_paths.CDN_DOMAIN)
S3_RECORDING_PREFIX = media_paths.public('stack/voice/')
S3_OBD_AUDIO_PREFIX = media_paths.public('stack/voice/obd-audio/')
TTL_DAYS = 90

# Audio spec for generated IVR prompts: 8 kHz, mono, 16-bit PCM WAV. These are
# narrowband telephony constraints, not any one vendor's, and the WAV
# conversion still needs them for the S3 audio library.
PROMPT_SAMPLE_RATE = 8000
PROMPT_CHANNELS = 1
PROMPT_BITS_PER_SAMPLE = 16

# Cached secrets
_secrets_cache = None


# _get_secrets() removed: the retired provider credential is no longer read
# here. The secret still exists in Secrets Manager with no reader and is
# deleted under separate destructive approval.


def _retired_campaign_endpoint(path: str, request_id: str) -> Dict[str, Any]:
    """410 for the outbound-dialler endpoints retired with the provider."""
    logger.warning(json.dumps({
        'event': 'obd_campaign_endpoint_removed',
        'path': path,
        'requestId': request_id,
    }))
    return _response(410, {
        'error': 'Outbound dialler campaign management has been removed.',
        'errorCode': 'ENDPOINT_REMOVED',
        'detail': ('These endpoints created, populated and polled campaigns on a '
                   'retired India voice provider. PSTN voice is now Plivo. '
                   'Historical campaign records remain listable and deletable, '
                   'and text-to-speech plus the S3 audio library are '
                   'unaffected.'),
    })


# Module-level origin for CORS (set per-invocation in handler)
origin = ''


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle OBD campaign operations."""
    request_id = context.aws_request_id if context else str(uuid.uuid4())
    global origin
    origin = extract_origin(event)
    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'POST')
    path = event.get('rawPath', event.get('path', ''))
    query_params = event.get('queryStringParameters') or {}
    
    try:
        body = {}
        if event.get('body'):
            body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
        
        if http_method == 'OPTIONS':
            return _response(200, {'message': 'OK'})

        # ── Authenticate API Gateway callers ──
        # All ten /voice-in/obd routes were public (AuthorizationType=NONE) with no
        # handler check: campaign create, TTS synthesis, audio and CSV upload, and
        # DELETE clear-logs were anonymously reachable. The retired provider that
        # once posted here is gone; the live callers are dashboard operations, which
        # already send a Cognito bearer token. require_auth skips OPTIONS and
        # internal Lambda invokes.
        #
        # This used to note that the guard sat BEFORE a CDR-callback branch, and that
        # removing that branch "belongs to the Airtel retirement sweep, not here".
        # The sweep happened on 2026-09-25 and the branch is gone, so the guard is now
        # simply the first thing after OPTIONS.
        auth_failure = require_auth(event)
        if auth_failure is not None:
            return auth_failure


        if '/tts' in path:
            return _text_to_audio(body, request_id)
        elif '/audio-library' in path:
            if http_method == 'GET':
                return _list_audio_library(query_params, request_id)
            elif http_method == 'POST':
                return _upload_to_audio_library(body, request_id)
            elif http_method == 'DELETE':
                return _delete_audio_library_file(body, query_params, request_id)
        # Campaign creation and provider uploads are gone. Answer explicitly
        # rather than 404, so an operator sees why the capability disappeared.
        elif ('/upload-audio' in path or '/upload-csv' in path
              or '/create' in path or '/status' in path):
            return _retired_campaign_endpoint(path, request_id)
        elif '/list' in path or http_method == 'GET':
            return _list_campaigns(query_params, request_id)
        elif '/clear-logs' in path:
            return _clear_logs(body, request_id)
        elif '/delete' in path or http_method == 'DELETE':
            campaign_id = query_params.get('campaignId') or body.get('campaignId')
            hard_delete = query_params.get('hard') == 'true' or body.get('hardDelete', False)
            if body.get('clearAll'):
                return _clear_logs(body, request_id)
            return _delete_campaign(campaign_id, hard_delete, request_id)
        else:
            if http_method == 'POST':
                # Support clear-logs via POST body action
                if body.get('clearAll') or body.get('_action') == 'clear-logs':
                    return _clear_logs(body, request_id)
                return _retired_campaign_endpoint(path, request_id)
            if http_method == 'DELETE':
                campaign_id = query_params.get('campaignId')
                return _delete_campaign(campaign_id, False, request_id)
            return _response(404, {'error': 'Endpoint not found'})
        
    except json.JSONDecodeError:
        return _response(400, {'error': 'Invalid JSON'})
    except Exception as e:
        logger.error(f"OBD error: {str(e)}")
        return _response(500, {'error': 'Internal server error'})


def _parse_wav_header(data: bytes) -> Dict:
    """Parse WAV file header and return format info."""
    import struct
    if len(data) < 44 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        return {'valid': False, 'error': 'Not a valid WAV file'}
    
    # Find fmt chunk
    pos = 12
    fmt_found = False
    audio_format = channels = sample_rate = bits_per_sample = 0
    data_offset = data_size = 0
    
    while pos < len(data) - 8:
        chunk_id = data[pos:pos+4]
        chunk_size = struct.unpack_from('<I', data, pos+4)[0]
        if chunk_id == b'fmt ':
            if chunk_size < 16:
                return {'valid': False, 'error': 'Invalid fmt chunk'}
            audio_format, channels, sample_rate, _, _, bits_per_sample = struct.unpack_from('<HHIIHH', data, pos+8)
            fmt_found = True
        elif chunk_id == b'data':
            data_offset = pos + 8
            data_size = chunk_size
        pos += 8 + chunk_size
        # Align to even boundary
        if chunk_size % 2:
            pos += 1
    
    if not fmt_found:
        return {'valid': False, 'error': 'No fmt chunk found'}
    
    return {
        'valid': True,
        'audioFormat': audio_format,  # 1 = PCM
        'channels': channels,
        'sampleRate': sample_rate,
        'bitsPerSample': bits_per_sample,
        'dataOffset': data_offset,
        'dataSize': data_size,
        'isPCM': audio_format == 1,
    }


def _convert_wav_to_prompt_spec(audio_bytes: bytes, request_id: str) -> Dict:
    """
    Validate and convert WAV to Airtel spec: 16-bit 8kHz Mono PCM WAV.
    
    Returns: {
        'converted': bool,       # True if conversion was needed
        'compliant': bool,       # True if already compliant (no conversion needed)
        'audioBytes': bytes,     # The compliant WAV bytes
        'originalInfo': dict,    # Original format info
        'error': str or None,    # Error message if failed
        'report': str,           # Human-readable report
    }
    """
    import struct
    
    info = _parse_wav_header(audio_bytes)
    if not info.get('valid'):
        return {'converted': False, 'compliant': False, 'audioBytes': audio_bytes, 'originalInfo': info, 'error': info.get('error', 'Invalid WAV'), 'report': f"Invalid WAV: {info.get('error')}"}
    
    already_compliant = (
        info['isPCM'] and
        info['channels'] == PROMPT_CHANNELS and
        info['sampleRate'] == PROMPT_SAMPLE_RATE and
        info['bitsPerSample'] == PROMPT_BITS_PER_SAMPLE
    )
    
    ch_label = 'Mono' if info['channels'] == 1 else ('Stereo' if info['channels'] == 2 else str(info['channels']) + 'ch')
    fmt_label = 'PCM' if info['isPCM'] else ('fmt=' + str(info['audioFormat']))
    orig_desc = f"{info['sampleRate']}Hz {info['bitsPerSample']}bit {ch_label} {fmt_label}"
    
    if already_compliant:
        return {
            'converted': False, 'compliant': True, 'audioBytes': audio_bytes,
            'originalInfo': info, 'error': None,
            'report': f"Already Airtel-compliant: {orig_desc}"
        }
    
    if not info['isPCM']:
        return {
            'converted': False, 'compliant': False, 'audioBytes': audio_bytes,
            'originalInfo': info, 'error': f'Non-PCM audio (format={info["audioFormat"]}). Only PCM WAV can be auto-converted. Please convert to PCM WAV first.',
            'report': f"Cannot convert non-PCM: {orig_desc}"
        }
    
    if info['dataOffset'] == 0 or info['dataSize'] == 0:
        return {'converted': False, 'compliant': False, 'audioBytes': audio_bytes, 'originalInfo': info, 'error': 'No audio data found in WAV', 'report': 'No data chunk'}
    
    try:
        raw_pcm = audio_bytes[info['dataOffset']:info['dataOffset'] + info['dataSize']]
        src_channels = info['channels']
        src_rate = info['sampleRate']
        src_bits = info['bitsPerSample']
        
        # Step 1: Decode PCM samples to list of float values (mono)
        if src_bits == 16:
            sample_count = len(raw_pcm) // (2 * src_channels)
            samples = list(struct.unpack(f'<{sample_count * src_channels}h', raw_pcm[:sample_count * 2 * src_channels]))
        elif src_bits == 8:
            sample_count = len(raw_pcm) // src_channels
            samples = [((b - 128) * 256) for b in raw_pcm[:sample_count * src_channels]]
        elif src_bits == 24:
            sample_count = len(raw_pcm) // (3 * src_channels)
            samples = []
            for i in range(sample_count * src_channels):
                off = i * 3
                val = raw_pcm[off] | (raw_pcm[off+1] << 8) | (raw_pcm[off+2] << 16)
                if val >= 0x800000:
                    val -= 0x1000000
                samples.append(val >> 8)  # Scale 24-bit to 16-bit
        elif src_bits == 32:
            sample_count = len(raw_pcm) // (4 * src_channels)
            samples = list(struct.unpack(f'<{sample_count * src_channels}i', raw_pcm[:sample_count * 4 * src_channels]))
            samples = [s >> 16 for s in samples]  # Scale 32-bit to 16-bit
        else:
            return {'converted': False, 'compliant': False, 'audioBytes': audio_bytes, 'originalInfo': info, 'error': f'Unsupported bit depth: {src_bits}', 'report': f'Cannot convert {src_bits}-bit'}
        
        # Step 2: Mix to mono if stereo/multi-channel
        if src_channels > 1:
            mono_samples = []
            for i in range(0, len(samples), src_channels):
                chunk = samples[i:i+src_channels]
                mono_samples.append(sum(chunk) // len(chunk))
            samples = mono_samples
        
        # Step 3: Resample to 8000Hz using linear interpolation
        if src_rate != PROMPT_SAMPLE_RATE:
            src_len = len(samples)
            ratio = src_rate / PROMPT_SAMPLE_RATE
            dst_len = int(src_len / ratio)
            resampled = []
            for i in range(dst_len):
                src_pos = i * ratio
                idx = int(src_pos)
                frac = src_pos - idx
                if idx + 1 < src_len:
                    val = samples[idx] * (1 - frac) + samples[idx + 1] * frac
                else:
                    val = samples[min(idx, src_len - 1)]
                resampled.append(int(max(-32768, min(32767, val))))
            samples = resampled
        
        # Step 4: Clamp to 16-bit range
        samples = [max(-32768, min(32767, s)) for s in samples]
        
        # Step 5: Build compliant WAV
        pcm_out = struct.pack(f'<{len(samples)}h', *samples)
        byte_rate = PROMPT_SAMPLE_RATE * PROMPT_CHANNELS * PROMPT_BITS_PER_SAMPLE // 8
        block_align = PROMPT_CHANNELS * PROMPT_BITS_PER_SAMPLE // 8
        wav_header = struct.pack('<4sI4s4sIHHIIHH4sI',
            b'RIFF', 36 + len(pcm_out), b'WAVE',
            b'fmt ', 16, 1, PROMPT_CHANNELS, PROMPT_SAMPLE_RATE, byte_rate, block_align, PROMPT_BITS_PER_SAMPLE,
            b'data', len(pcm_out)
        )
        converted_wav = wav_header + pcm_out
        
        target_desc = f"{PROMPT_SAMPLE_RATE}Hz {PROMPT_BITS_PER_SAMPLE}bit Mono PCM"
        report = f"Converted: {orig_desc} → {target_desc} ({len(audio_bytes)} → {len(converted_wav)} bytes)"
        
        logger.info(json.dumps({
            'event': 'audio_converted_to_airtel_spec',
            'original': orig_desc,
            'target': target_desc,
            'originalSize': len(audio_bytes),
            'convertedSize': len(converted_wav),
            'requestId': request_id
        }))
        
        return {
            'converted': True, 'compliant': True, 'audioBytes': converted_wav,
            'originalInfo': info, 'error': None, 'report': report
        }
    except Exception as e:
        logger.error(f"Audio conversion error: {str(e)}")
        return {'converted': False, 'compliant': False, 'audioBytes': audio_bytes, 'originalInfo': info, 'error': f'Conversion failed: {str(e)}', 'report': f'Conversion error: {str(e)}'}


# _upload_audio() removed 2026-09-19: it uploaded IVR prompts to the retired
# provider's prompt store. Polly text-to-speech (_text_to_audio) and the S3
# audio library further down are NOT provider-specific and are retained - the
# voice operations UI depends on both.


def _text_to_audio(body: Dict, request_id: str) -> Dict[str, Any]:
    """Convert text to speech using AWS Polly, store WAV in S3.

    Generates 16-bit 8kHz Mono WAV (Airtel requirement) via Polly,
    stores the result in S3. S3 is the only destination.

    Request body:
    - text: The text to convert to speech (required, max 3000 chars)
    - voiceId: Polly voice (default: Kajal for en-IN)
    - languageCode: e.g. hi-IN, en-IN (default: en-IN)
    """
    try:
        text = body.get('text', '').strip()
        if not text:
            return _response(400, {'error': 'text is required'})
        if len(text) > 3000:
            return _response(400, {'error': 'text must be 3000 characters or less'})

        voice_id = body.get('voiceId', 'Kajal')
        language_code = body.get('languageCode', 'en-IN')
        engine = 'neural' if voice_id in ('Kajal',) else 'standard'

        polly = boto3.client('polly', region_name=AWS_REGION)

        # Synthesize speech as PCM 8000Hz (Airtel requires 8kHz)
        polly_resp = polly.synthesize_speech(
            Text=text,
            OutputFormat='pcm',
            SampleRate='8000',
            VoiceId=voice_id,
            LanguageCode=language_code,
            Engine=engine,
        )

        pcm_data = polly_resp['AudioStream'].read()

        # Build WAV header for 16-bit 8kHz Mono PCM
        import struct
        num_channels = 1
        sample_rate = 8000
        bits_per_sample = 16
        byte_rate = sample_rate * num_channels * bits_per_sample // 8
        block_align = num_channels * bits_per_sample // 8
        data_size = len(pcm_data)

        wav_header = struct.pack('<4sI4s4sIHHIIHH4sI',
            b'RIFF', 36 + data_size, b'WAVE',
            b'fmt ', 16, 1, num_channels, sample_rate, byte_rate, block_align, bits_per_sample,
            b'data', data_size
        )
        wav_bytes = wav_header + pcm_data
        file_name = f'tts_audio_{int(time.time())}.wav'
        s3_key = f'{S3_RECORDING_PREFIX}tts/{file_name}'

        # Store in S3
        s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=wav_bytes, ContentType='audio/wav')

        logger.info(json.dumps({
            'event': 'obd_tts_generated',
            'textLength': len(text),
            'voiceId': voice_id,
            'wavSize': len(wav_bytes),
            's3Key': s3_key,
            'requestId': request_id
        }))

        # The provider prompt upload that used to run here is gone. S3 is the
        # only destination now, so audioUrl is the S3 URL rather than a
        # vendor-hosted one that may or may not have succeeded.
        audio_url = f'https://{CDN_DOMAIN}/{s3_key}'

        return _response(200, {
            'success': True,
            'audioUrl': audio_url,
            's3Key': s3_key,
            'fileName': file_name,
            'sizeBytes': len(wav_bytes),
            'voiceId': voice_id,
            'languageCode': language_code,
            'textLength': len(text),
        })

    except Exception as e:
        logger.error(f"TTS error: {str(e)}")
        return _response(500, {'error': str(e)})



# Removed 2026-09-19, with the outbound dialler:
#   _upload_csv()          pushed a contact sheet to the provider's file API
#   _create_campaign()     created the campaign on the provider
#   _upload_csv_internal() the same upload, called from campaign creation
#   _get_campaign_status() polled the provider for campaign progress
#
# All four called a retired India voice provider. Campaign dialling is an
# outbound-calling capability, which the provider policy assigns to Plivo.
# Historical campaign records are still listed, read and deleted below.


def _list_campaigns(params: Dict, request_id: str) -> Dict[str, Any]:
    """List OBD campaigns."""
    try:
        table = dynamodb.Table(OBD_CAMPAIGNS_TABLE)
        result = table.scan(Limit=int(params.get('limit', 50)))
        campaigns = result.get('Items', [])
        campaigns.sort(key=lambda x: float(x.get('createdAt', 0)), reverse=True)
        
        return _response(200, {'campaigns': [_normalize_campaign(c) for c in campaigns], 'count': len(campaigns)})
    except Exception as e:
        return _response(500, {'error': str(e)})


def _store_campaign(campaign_id: str, name: str, airtel_id: str, sheets: List[str], audio_url: str, contact_count: int = 0) -> None:
    """Store campaign record."""
    try:
        now = int(time.time())
        table = dynamodb.Table(OBD_CAMPAIGNS_TABLE)
        table.put_item(Item={
            'id': campaign_id,
            'campaignId': campaign_id,
            'airtelCampaignId': airtel_id or '',
            'campaignName': name,
            'sheetFileNames': sheets,
            'audioUrl': audio_url,
            'contactCount': contact_count,
            'status': 'created',
            'createdAt': Decimal(str(now)),
            'updatedAt': Decimal(str(now)),
            'ttl': Decimal(str(now + (TTL_DAYS * 24 * 60 * 60)))
        })
    except Exception as e:
        logger.error(f"Store campaign error: {str(e)}")


def _delete_campaign(campaign_id: str, hard_delete: bool, request_id: str) -> Dict[str, Any]:
    """Delete a campaign (soft or hard delete)."""
    if not campaign_id:
        return _response(400, {'error': 'campaignId is required'})
    
    try:
        table = dynamodb.Table(OBD_CAMPAIGNS_TABLE)
        
        if hard_delete:
            # Hard delete - remove from DynamoDB
            table.delete_item(Key={'id': campaign_id})
            return _response(200, {'success': True, 'deleted': campaign_id, 'type': 'hard'})
        else:
            # Soft delete - mark as deleted
            now = int(time.time())
            table.update_item(
                Key={'id': campaign_id},
                UpdateExpression='SET #status = :status, deletedAt = :deletedAt, updatedAt = :updatedAt',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':status': 'DELETED',
                    ':deletedAt': Decimal(str(now)),
                    ':updatedAt': Decimal(str(now))
                }
            )
            return _response(200, {'success': True, 'deleted': campaign_id, 'type': 'soft'})
    except Exception as e:
        logger.error(f"Delete campaign error: {str(e)}")
        return _response(500, {'error': str(e)})


def _clear_logs(body: Dict, request_id: str) -> Dict[str, Any]:
    """Clear campaign logs (hard delete multiple campaigns)."""
    try:
        campaign_ids = body.get('campaignIds', [])
        clear_all = body.get('clearAll', False)
        
        table = dynamodb.Table(OBD_CAMPAIGNS_TABLE)
        deleted_count = 0
        
        if clear_all:
            # Scan and delete all campaigns with pagination
            scan_kwargs = {'ProjectionExpression': 'id'}
            while True:
                result = table.scan(**scan_kwargs)
                for item in result.get('Items', []):
                    table.delete_item(Key={'id': item['id']})
                    deleted_count += 1
                if 'LastEvaluatedKey' not in result:
                    break
                scan_kwargs['ExclusiveStartKey'] = result['LastEvaluatedKey']
        elif campaign_ids:
            # Delete specific campaigns
            for cid in campaign_ids:
                try:
                    table.delete_item(Key={'id': cid})
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f'Campaign delete failed for {cid}: {e}')
        else:
            return _response(400, {'error': 'campaignIds or clearAll is required'})
        
        return _response(200, {
            'success': True,
            'deletedCount': deleted_count,
            'message': f'Cleared {deleted_count} campaign logs'
        })
    except Exception as e:
        logger.error(f"Clear logs error: {str(e)}")
        return _response(500, {'error': str(e)})


def _normalize_campaign(item: Dict) -> Dict:
    """Normalize campaign for response."""
    return {
        'id': item.get('id', ''),
        'campaignId': item.get('campaignId', ''),
        'airtelCampaignId': item.get('airtelCampaignId', ''),
        'campaignName': item.get('campaignName', ''),
        'status': item.get('status', ''),
        'audioUrl': item.get('audioUrl', ''),
        'sheetFileNames': item.get('sheetFileNames', []),
        'contactCount': int(float(item.get('contactCount', 0))),
        'createdAt': int(float(item.get('createdAt', 0))),
        'updatedAt': int(float(item.get('updatedAt', 0))),
    }


def _list_audio_library(params: Dict, request_id: str) -> Dict[str, Any]:
    """List audio files from S3 obd-audio library folder.
    
    Returns all WAV files stored in s3://wecare-digital-get/stack/voice/obd-audio/
    Each file includes: key, name, size, lastModified, publicUrl, downloadUrl, format info
    """
    try:
        files = []
        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=S3_OBD_AUDIO_PREFIX):
            for obj in page.get('Contents', []):
                key = obj['Key']
                if key == S3_OBD_AUDIO_PREFIX:
                    continue  # skip folder marker
                name = key.replace(S3_OBD_AUDIO_PREFIX, '')
                if not name:
                    continue
                
                # Read first 44 bytes to parse WAV header for format info
                format_info = {}
                try:
                    head_resp = s3.get_object(Bucket=S3_BUCKET, Key=key, Range='bytes=0-255')
                    head_bytes = head_resp['Body'].read()
                    parsed = _parse_wav_header(head_bytes)
                    if parsed.get('valid'):
                        sr = parsed['sampleRate']
                        ch = parsed['channels']
                        bits = parsed['bitsPerSample']
                        compliant = (parsed['isPCM'] and sr == PROMPT_SAMPLE_RATE and ch == PROMPT_CHANNELS and bits == PROMPT_BITS_PER_SAMPLE)
                        format_info = {
                            'sampleRate': sr,
                            'channels': ch,
                            'bitsPerSample': bits,
                            'isPCM': parsed['isPCM'],
                            'airtelCompliant': compliant,
                            'formatLabel': f"{sr}Hz {bits}bit {'Mono' if ch == 1 else 'Stereo'}",
                        }
                except Exception:
                    pass
                
                public_url = f'https://{CDN_DOMAIN}/{key}'
                files.append({
                    'key': key,
                    'name': name,
                    'size': obj['Size'],
                    'lastModified': obj['LastModified'].isoformat() if hasattr(obj['LastModified'], 'isoformat') else str(obj['LastModified']),
                    'publicUrl': public_url,
                    'downloadUrl': public_url,
                    **format_info,
                })
        files.sort(key=lambda x: x.get('lastModified', ''), reverse=True)
        return _response(200, {'success': True, 'files': files, 'count': len(files), 'prefix': S3_OBD_AUDIO_PREFIX})
    except Exception as e:
        logger.error(f"List audio library error: {str(e)}")
        return _response(500, {'error': str(e)})


def _upload_to_audio_library(body: Dict, request_id: str) -> Dict[str, Any]:
    """Upload audio file to S3 obd-audio library.
    
    Stores in s3://wecare-digital-get/stack/voice/obd-audio/{fileName}
    Stores in S3 only. The best-effort upload to a retired provider's prompt
    store was removed on 2026-09-19.
    
    Request body:
    - audioData: base64-encoded WAV file content (required)
    - fileName: custom filename (optional, default: obd_lib_{timestamp}.wav)

    `uploadToAirtel` was documented here until 2026-09-25 as "whether to also upload
    to Airtel (default: true)". No code ever read it - the docstring was the only
    place it existed - but the frontend was sending it on every upload because of
    this line. Both are gone; the audio goes to storage we control.
    """
    try:
        audio_data = body.get('audioData')
        if not audio_data:
            return _response(400, {'error': 'audioData (base64) is required'})
        
        audio_bytes = base64.b64decode(audio_data)
        file_name = body.get('fileName', f'obd_lib_{int(time.time())}.wav')
        # Sanitize filename
        file_name = file_name.replace('/', '_').replace('\\', '_')
        
        # Validate and auto-convert to Airtel spec (16-bit 8kHz Mono PCM WAV)
        conv = _convert_wav_to_prompt_spec(audio_bytes, request_id)
        conversion_report = conv.get('report', '')
        was_converted = conv.get('converted', False)
        if conv.get('error') and not conv.get('compliant'):
            return _response(400, {'error': conv['error'], 'report': conversion_report, 'originalInfo': conv.get('originalInfo')})
        audio_bytes = conv['audioBytes']
        
        s3_key = f'{S3_OBD_AUDIO_PREFIX}{file_name}'
        
        # Store in S3
        s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=audio_bytes, ContentType='audio/wav')
        
        logger.info(json.dumps({
            'event': 'obd_audio_library_upload',
            'fileName': file_name,
            's3Key': s3_key,
            'sizeBytes': len(audio_bytes),
            'requestId': request_id
        }))
        
        # The provider prompt upload that used to run here is gone. The S3 copy
        # above is now the only destination, and it is the one the audio library
        # and the IVR actually read.

        return _response(200, {
            'success': True,
            'fileName': file_name,
            's3Key': s3_key,
            'publicUrl': f'https://{CDN_DOMAIN}/{s3_key}',
            'downloadUrl': f'https://{CDN_DOMAIN}/{s3_key}',
            'audioUrl': f'https://{CDN_DOMAIN}/{s3_key}',
            'sizeBytes': len(audio_bytes),
            'converted': was_converted,
            'conversionReport': conversion_report,
        })
    except Exception as e:
        logger.error(f"Audio library upload error: {str(e)}")
        return _response(500, {'error': str(e)})


def _delete_audio_library_file(body: Dict, params: Dict, request_id: str) -> Dict[str, Any]:
    """Delete audio file from S3 obd-audio library."""
    try:
        s3_key = body.get('s3Key') or params.get('s3Key', '')
        if not s3_key or not s3_key.startswith(S3_OBD_AUDIO_PREFIX):
            return _response(400, {'error': 's3Key is required and must be in obd-audio folder'})
        s3.delete_object(Bucket=S3_BUCKET, Key=s3_key)
        return _response(200, {'success': True, 'deleted': s3_key})
    except Exception as e:
        logger.error(f"Delete audio library file error: {str(e)}")
        return _response(500, {'error': str(e)})


# `_store_recording_to_s3` REMOVED 2026-09-25 with the Airtel CDR surface above:
# its only caller was `_handle_cdr_callback`. Its c2c twin went the same way.
def _clean_phone(phone: str) -> str:
    """Clean phone number to 10 digits."""
    if not phone:
        return ''
    digits = ''.join(c for c in str(phone) if c.isdigit())
    if digits.startswith('91') and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith('0') and len(digits) == 11:
        digits = digits[1:]
    return digits if len(digits) == 10 else ''


def _response(status_code: int, body: Dict) -> Dict[str, Any]:
    """Return HTTP response with CORS headers."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin),
        'body': json.dumps(body, default=str)
    }


# ── CDR Notification Helpers (WhatsApp + RCS on OBD CDR events) ──

def _lookup_contact_id(phone: str) -> str:
    """Look up contactId from ContactsTable by phone number."""
    clean = phone.replace('+', '').replace(' ', '')
    contacts_table = dynamodb.Table('stack-wecare-digital-ContactsTable')
    for variant in [phone, clean, '+' + clean]:
        try:
            resp = contacts_table.query(
                IndexName='phone-index',
                KeyConditionExpression=boto3.dynamodb.conditions.Key('phone').eq(variant),
                Limit=1
            )
            items = resp.get('Items', [])
            if items:
                return items[0].get('contactId') or items[0].get('id') or clean
        except Exception:
            pass
    return clean


def _store_to_inbox(message_id: str, contact_id: str, contact_phone: str,
                    content: str, channel: str, status: str,
                    message_type: str, phone_number_id: str = '',
                    wamid: str = '', request_id: str = '') -> None:
    """Store a sent notification in WhatsAppOutboundTable so it appears in the dashboard inbox."""
    try:
        now = int(time.time())
        store_id = message_id or f"obd_cdr_{contact_phone}_{now}"
        outbound_table = dynamodb.Table('stack-wecare-digital-WhatsAppOutboundTable')
        item = {
            'id': store_id,
            'messageId': store_id,
            'contactId': contact_id,
            'contactPhone': contact_phone,
            'content': content,
            'channel': channel,
            'direction': 'outbound',
            'status': status,
            'messageType': message_type,
            'timestamp': Decimal(str(now)),
            'createdAt': Decimal(str(now)),
            'expiresAt': Decimal(str(now + 30 * 24 * 60 * 60)),
            'requestId': request_id,
        }
        if wamid:
            item['whatsappMessageId'] = wamid
        else:
            item['whatsappMessageId'] = store_id
        if phone_number_id:
            item['phoneNumberId'] = phone_number_id
            item['awsPhoneNumberId'] = phone_number_id
        outbound_table.put_item(Item=item)
        logger.info(json.dumps({
            'event': 'obd_notification_stored_in_inbox',
            'id': store_id,
            'channel': channel,
            'contactId': mask_contact_id(contact_id),
            'requestId': request_id,
        }))
    except Exception as e:
        logger.warning(f'Failed to store OBD notification in inbox: {e}')


def _send_obd_cdr_notifications(cdr_record: Dict, request_id: str) -> None:
    """Send RCS + SMS notifications on OBD CDR events.

    Sends to the CALLER (Party A / destination of OBD campaign) after call completes.
    Channel priority: SMS (AWS End User Messaging) → RCS (Sinch rcsmenu template)
    Updates CDR record with trigger metadata for dashboard display.
    """
    try:
        # For OBD, the callerNumber is the OBD system number; destinationNumber is the actual person called
        # We notify the destination (the person who received the OBD call)
        destination = cdr_record.get('callerNumber', '') or cdr_record.get('destinationNumber', '')
        if not destination:
            return

        clean_dest = destination.replace('+', '').replace(' ', '').replace('-', '')
        # Strip leading 0 (Indian STD prefix)
        if clean_dest.startswith('0') and len(clean_dest) == 11:
            clean_dest = clean_dest[1:]
        # Normalize to 91XXXXXXXXXX format
        if not (clean_dest.startswith('91') and len(clean_dest) == 12):
            if len(clean_dest) >= 10:
                clean_dest = '91' + clean_dest[-10:]

        # Skip notification for system/CLI numbers
        if clean_dest in ('918047311032', '918040761117', '919319767034'):
            # Try the other number
            alt = cdr_record.get('destinationNumber', '') or cdr_record.get('callerNumber', '')
            clean_dest = alt.replace('+', '').replace(' ', '')
            if len(clean_dest) == 10:
                clean_dest = '91' + clean_dest
            if not clean_dest or clean_dest in ('918047311032', '918040761117', '919319767034'):
                return

        contact_id = _lookup_contact_id(clean_dest)
        now_ts = int(time.time())
        sms_message_id = ''
        rcs_message_id = ''
        rcs_sent = False

        # ── 0. Send the follow-up SMS (AWS End User Messaging) ──
        session_id = cdr_record.get('vmSessionId', '') or cdr_record.get('clientCorrelationId', '')
        ivr_sms_content = (
            "Thanks for contacting WECARE.DIGITAL!\n\n"
            "Submit your request here: https://wecare.digital/submit-request/ "
            "or send us a message / voice note on WhatsApp: https://wecare.digital/r/wa.\n\n"
            "We'll review it and follow up if needed."
        )
        try:
            # One call, every country. comms.notify selects the AWS region and
            # applies the TRAI DLT gate; this handler decides neither.
            from lambda_utils.comms.notify import send_notification_sms
            send_notification_sms(
                '+' + clean_dest, ivr_sms_content,
                dlt_template_key='ivr-default',
                campaign='obd-cdr', request_id=request_id)
            sms_message_id = f"obd_sms_{session_id}_{now_ts}"
            _store_to_inbox(
                message_id=sms_message_id,
                contact_id=contact_id,
                contact_phone=clean_dest,
                content=ivr_sms_content,
                channel='sms',
                status='sent',
                message_type='cdr_obd',
                request_id=request_id,
            )
            logger.info(json.dumps({
                'event': 'obd_cdr_sms_triggered',
                'destination': clean_dest[-4:],
                'provider': 'aws-end-user-messaging',
                'smsId': sms_message_id,
                'requestId': request_id,
            }))
        except Exception as sms_err:
            logger.warning(f'OBD CDR SMS failed (non-blocking): {sms_err}')

        # ── 1. RCS via Sinch (rcsmenu template) ──
        try:
            from lambda_utils.sinch_rcs import is_rcs_enabled, send_rcs_ivr_notification
            if is_rcs_enabled():
                rcs_result = send_rcs_ivr_notification(clean_dest, request_id)
                rcs_sent = rcs_result.get('success', False)
                if rcs_sent:
                    rcs_message_id = rcs_result.get('message_id', '')
                    _store_to_inbox(
                        message_id=rcs_message_id,
                        contact_id=contact_id,
                        contact_phone=clean_dest,
                        content='[RCS notification] WECARE.DIGITAL customerservice',
                        channel='rcs',
                        status='sent',
                        message_type='cdr_obd',
                        request_id=request_id,
                    )
                else:
                    logger.warning(f"OBD RCS returned success=false: {rcs_result.get('error', 'unknown')}")
        except Exception as rcs_err:
            logger.warning(f'OBD CDR RCS notification failed (non-blocking): {rcs_err}')

        # ── 3. Update CDR record with trigger metadata ──
        cdr_id = cdr_record.get('id', '')
        if cdr_id:
            try:
                table = dynamodb.Table(VOICE_CDR_TABLE)
                update_expr_parts = []
                expr_values = {}

                if sms_message_id:
                    update_expr_parts.append('smsTriggered = :smsT')
                    expr_values[':smsT'] = True
                    update_expr_parts.append('smsMessageId = :smsId')
                    expr_values[':smsId'] = sms_message_id
                    update_expr_parts.append('smsDltTemplateId = :smsDlt')
                    expr_values[':smsDlt'] = '1007277993798259629'
                    update_expr_parts.append('smsContent = :smsCont')
                    expr_values[':smsCont'] = ivr_sms_content[:200]
                    update_expr_parts.append('smsTimestamp = :smsTs')
                    expr_values[':smsTs'] = str(now_ts)

                if rcs_sent and rcs_message_id:
                    update_expr_parts.append('rcsMessageTriggered = :rcsT')
                    expr_values[':rcsT'] = True
                    update_expr_parts.append('rcsMessageId = :rcsId')
                    expr_values[':rcsId'] = rcs_message_id
                    update_expr_parts.append('rcsMessageContent = :rcsCont')
                    expr_values[':rcsCont'] = '[RCS notification] WECARE.DIGITAL customerservice'
                    update_expr_parts.append('rcsMessageTimestamp = :rcsTs')
                    expr_values[':rcsTs'] = str(now_ts)

                if update_expr_parts:
                    table.update_item(
                        Key={'id': cdr_id},
                        UpdateExpression='SET ' + ', '.join(update_expr_parts),
                        ExpressionAttributeValues=expr_values,
                    )
                    logger.info(json.dumps({
                        'event': 'obd_cdr_trigger_metadata_updated',
                        'cdrId': cdr_id,
                        'rcs': rcs_sent,
                        'requestId': request_id,
                    }))
            except Exception as e:
                logger.warning(f'OBD CDR trigger metadata update failed (non-blocking): {e}')

    except Exception as e:
        logger.warning(f'OBD CDR notification error: {e}')
