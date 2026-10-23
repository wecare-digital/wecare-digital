/**
 * WhatsApp Voice Lambda - TTS via Polly + Transcription via Transcribe + WhatsApp Audio Messages
 * 
 * Deployed separately from Amplify Gen 2 (see scripts/deploy-whatsapp-voice.ps1)
 * Lambda: wecare-whatsapp-voice
 * Runtime: Python 3.12
 * Region: us-east-1
 * 
 * API Gateway Routes (api.wecare.digital):
 *   POST   /whatsapp-voice/tts             - Generate TTS and send as WhatsApp audio
 *   POST   /whatsapp-voice/send            - Send existing audio as WhatsApp message
 *   POST   /whatsapp-voice/transcribe      - Transcribe voice note from S3 (returns English text)
 *   GET    /whatsapp-voice/voices          - List available Polly voices
 *   GET    /whatsapp-voice/language-config  - Get voice language configuration
 *   PUT    /whatsapp-voice/language-config  - Update voice language configuration
 *   GET    /whatsapp-voice/logs            - List sent voice messages
 *   DELETE /whatsapp-voice/clear-logs      - Clear all logs
 * 
 * Environment Variables:
 *   CONTACTS_TABLE: stack-wecare-digital-ContactsTable
 *   MESSAGES_TABLE: stack-wecare-digital-WhatsAppOutboundTable
 *   VOICE_LOG_TABLE: stack-wecare-digital-WhatsAppVoiceTable
 *   INBOUND_TABLE: stack-wecare-digital-WhatsAppInboundTable
 *   SYSTEM_CONFIG_TABLE: stack-wecare-digital-SystemConfigTable
 *   UNIFIED_MESSAGES_TABLE: stack-wecare-digital-MessagesTable
 *   MEDIA_BUCKET: wecare-digital-get
 *   WHATSAPP_PHONE_NUMBER_ID_1: phone-number-id-waba1-direct-1016149501586345
 *   WHATSAPP_PHONE_NUMBER_ID_2: phone-number-id-waba-t-direct-1055232054343117
 * 
 * IAM Permissions needed:
 *   - polly:SynthesizeSpeech
 *   - transcribe:StartTranscriptionJob, transcribe:GetTranscriptionJob
 *   - translate:TranslateText
 *   - s3:PutObject, s3:GetObject, s3:DeleteObject on wecare-digital-get/secure/d/public/whatsapp/*
 *   - dynamodb:PutItem, Scan, DeleteItem, GetItem, BatchWriteItem, UpdateItem
 */

export const whatsappVoiceLambdaName = 'wecare-whatsapp-voice';
export const whatsappVoiceTableName = 'stack-wecare-digital-WhatsAppVoiceTable';
