import { type ClientSchema, a, defineData } from '@aws-amplify/backend';

/**
 * WECARE.DIGITAL data model
 *
 * READ THIS BEFORE TRUSTING IT AS INFRASTRUCTURE.
 *
 * This file declares 58 models and is passed to `defineBackend` by
 * `amplify/backend.ts`. It therefore looks deployed. It is not. Measured against
 * account 775261844268 / us-east-1 on 2026-09-24:
 *
 *     AppSync GraphQL APIs        0
 *     models declared here       58
 *     DynamoDB tables live       77
 *
 * Not one model below has ever been materialised. Every table the platform
 * actually uses was created by CDK (`amplify/link-resources.ts`,
 * `backend-resources.ts`, `seo-resources.ts`) or by a `scripts/provision_*.py`
 * script, under the `stack-wecare-digital-*` naming scheme, and the Python Lambda
 * fleet addresses those names directly through `os.environ` defaults. Nothing at
 * runtime reads this schema.
 *
 * The sharp edge
 * --------------
 * Amplify would not ADOPT the live tables if this were deployed. It would create
 * its own, named after the API, and leave 77 populated tables untouched and
 * unread beside 58 empty ones. The comments in this file cite physical names like
 * `stack-wecare-digital-ContactsTable`, which makes it read as a description of
 * the live tables; it is not that either. Treat every model here as
 * documentation of intent unless you have checked the physical table yourself.
 *
 * Why it is not simply deleted
 * ---------------------------
 * `backend.ts` uses `backend.data.resources.stacks['data']` as the CDK stack that
 * hosts the URL shortener, the SQS queues, the CloudWatch alarms and dashboard,
 * and the SEO resources. Removing `data` from `defineBackend` would take all of
 * that with it. The declaration is load-bearing as a stack anchor even though its
 * models are inert.
 *
 * Keeping it honest
 * -----------------
 * Two gates, deliberately separate, because they answer different questions:
 *
 *     python scripts/check_data_model_drift.py --gate   declared models vs live tables
 *     python scripts/audit_data_model_drift.py --gate   table names in code vs live tables
 *
 * The first is the one that guards this file. Six models declaring tables that do
 * not exist were removed on 2026-09-24 (SmsAws, AirtelSMS, AirtelC2C,
 * RcsMessages, AdminActionLog, ProviderDriftSnapshot) and every remaining
 * disagreement is recorded with its reason in that script rather than left to be
 * rediscovered.
 *
 * TTL is configured in `backend.ts` for 16 models, and is additionally enforced
 * on the physical tables by `scripts/_fix_ddb_ttl.py` - which is what actually
 * takes effect, since the CDK override has nothing to attach to.
 */
const schema = a.schema( {
  // Table 1: Contacts - Contact records with opt-in preferences
  // Requirement 3.2: Default Block Rule - allowlist fields required
  // Contact identifier contract (CRM-KEY-001), settled against the live table on
  // 2026-09-22 rather than from this declaration:
  //
  //   stack-wecare-digital-ContactsTable  KeySchema: id (HASH), no sort key
  //   GSIs: bsuid-index, email-index, phone-index
  //   13 items, every one carrying BOTH id and contactId, equal in 13 of 13
  //
  // In source, 20 files read or write the table and every one uses Key={'id': ...};
  // there is not a single Key={'contactId': ...}. So `id` is the physical key, the
  // runtime is correct, and this model previously declared `contactId` as the
  // identifier - a third version of the truth matching neither the table nor the code.
  //
  // `id` is now declared as the identifier to match the deployed table. `contactId` is
  // retained as an explicit alias because 13 rows carry it and two
  // `_lookup_contact_by_phone` readers return it, but it is no longer presented as the
  // key. `lambda_utils/contact_key` owns the invariant that the two agree; before that
  // module they agreed only by habit, and a diverged row would have made those readers
  // return a value that resolves to nothing - a message stored against a contact that
  // cannot be looked up, with no error anywhere.
  Contact: a
    .model( {
      id: a.id().required(),
      // Alias of `id`, kept for the outward API and the phone-index readers. Writers
      // must set it via contact_key.contact_item_keys so the two cannot diverge.
      contactId: a.string(),
      name: a.string(),
      phone: a.string(),
      email: a.string(),
      // WhatsApp BSUID (Business-Scoped User ID) — unique per WABA portfolio
      // Format: CC.alphanumeric (e.g. "US.13491208655302741918")
      bsuid: a.string(),
      // Parent BSUID — for linked accounts (e.g. parent business account)
      parentBsuid: a.string(),
      // WhatsApp username (optional, user-set, e.g. "@pablomorales")
      username: a.string(),
      // Contact book name — auto-populated by Meta's contact book feature
      contactBookName: a.string(),
      // Opt-in fields (Requirement 3.2: defaults to false)
      optInWhatsApp: a.boolean().default( false ),
      optInSms: a.boolean().default( false ),
      optInEmail: a.boolean().default( false ),
      // Allowlist fields (Requirement 3.2: defaults to false)
      allowlistWhatsApp: a.boolean().default( false ),
      allowlistSms: a.boolean().default( false ),
      allowlistEmail: a.boolean().default( false ),
      lastInboundMessageAt: a.datetime(),
      // Address fields (enriched via flows)
      addressLine1: a.string(),
      addressLine2: a.string(),
      city: a.string(),
      state: a.string(),
      pincode: a.string(),
      country: a.string().default( 'IN' ),
      // Structured address fields (WhatsApp Payments shipping_info)
      houseNumber: a.string(),
      buildingName: a.string(),
      towerNumber: a.string(),
      floorNumber: a.string(),
      landmark: a.string(),
      postalCode: a.string(),
      shippingAddress: a.string(),
      billingAddress: a.string(),
      shippingAddressJson: a.string(),
      billingAddressJson: a.string(),
      gstin: a.string(),
      // Business/profile fields (enriched via flows)
      companyName: a.string(),
      designation: a.string(),
      preferredLanguage: a.string(),
      isPep: a.boolean().default( false ),
      pepDetails: a.string(),
      paidBy: a.string(), // self, company
      lastFlowInteractionAt: a.datetime(),
      satisfactionScore: a.integer(), // NPS/CSAT from feedback flows
      // Welcome message tracking
      welcomeSent: a.boolean(),
      welcomeSentAt: a.datetime(),
      tags: a.string().array(),
      createdAt: a.datetime(),
      updatedAt: a.datetime(),
      deletedAt: a.datetime(),
    } )
    // `id`, matching the deployed KeySchema. Was `contactId`, which the live table has
    // never used as its partition key.
    .identifier( [ 'id' ] )
    // These three match the deployed GSIs exactly: phone-index, email-index,
    // bsuid-index. Verified 2026-09-22.
    .secondaryIndexes( ( index ) => [
      index( 'phone' ),
      index( 'email' ),
      index( 'bsuid' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 2: Messages - All inbound/outbound messages (TTL: 30 days)
  Message: a
    .model( {
      messageId: a.id().required(),
      contactId: a.string().required(),
      channel: a.enum( [ 'WHATSAPP', 'SMS', 'EMAIL', 'RCS' ] ),
      direction: a.enum( [ 'INBOUND', 'OUTBOUND' ] ),
      content: a.string(),
      timestamp: a.datetime(),
      status: a.enum( [ 'PENDING', 'SENT', 'DELIVERED', 'READ', 'FAILED' ] ),
      errorDetails: a.string(),
      whatsappMessageId: a.string(),
      mediaId: a.string(),
      s3Key: a.string(), // S3 storage location for media files
      mediaUrl: a.string(), // Pre-signed URL for media access
      senderPhone: a.string(), // Sender's phone number (inbound)
      senderName: a.string(), // Sender's WhatsApp profile name (inbound)
      senderBsuid: a.string(), // Sender's BSUID (inbound)
      senderParentBsuid: a.string(), // Sender's parent BSUID (inbound, for linked accounts)
      senderUsername: a.string(), // Sender's WhatsApp username (inbound)
      receivingPhone: a.string(), // Receiving phone number (outbound)
      awsPhoneNumberId: a.string(), // WABA phone number ID
      partnerWabaId: a.string(), // Embedded-Signup tenant WABA id (scalar, for tenant-scoped inbox GSI)
      transcription: a.string(), // English transcription of voice notes (audio messages)
      detectedLanguage: a.string(), // Detected language of voice note (e.g. "hi-IN", "en-US")
      expiresAt: a.integer(), // TTL: Unix epoch seconds (30 days)
    } )
    .identifier( [ 'messageId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'contactId' ),
      index( 'whatsappMessageId' ),
      index( 'partnerWabaId' ), // tenant-scoped customer inbox (scales past a bounded scan)
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 3: BulkJobs - Bulk messaging job tracking
  BulkJob: a
    .model( {
      jobId: a.id().required(),
      createdBy: a.string().required(),
      channel: a.enum( [ 'WHATSAPP', 'SMS', 'EMAIL', 'RCS' ] ),
      totalRecipients: a.integer(),
      sentCount: a.integer().default( 0 ),
      failedCount: a.integer().default( 0 ),
      status: a.enum( [ 'PENDING', 'IN_PROGRESS', 'PAUSED', 'COMPLETED', 'CANCELLED', 'FAILED' ] ),
      createdAt: a.datetime(),
      updatedAt: a.datetime(),
    } )
    .identifier( [ 'jobId' ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 4: BulkRecipients - Individual recipient status per job
  BulkRecipient: a
    .model( {
      jobId: a.string().required(),
      recipientId: a.string().required(),
      contactId: a.string().required(),
      status: a.enum( [ 'PENDING', 'SENT', 'FAILED' ] ),
      sentAt: a.datetime(),
      errorDetails: a.string(),
    } )
    .identifier( [ 'jobId', 'recipientId' ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),


  // Table 5: Users - Platform users with RBAC roles
  User: a
    .model( {
      userId: a.id().required(),
      email: a.string().required(),
      role: a.enum( [ 'VIEWER', 'OPERATOR', 'ADMIN' ] ),
      createdAt: a.datetime(),
      lastLoginAt: a.datetime(),
    } )
    .identifier( [ 'userId' ] )
    .secondaryIndexes( ( index ) => [ index( 'email' ) ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 6: MediaFiles - WhatsApp media metadata
  MediaFile: a
    .model( {
      fileId: a.id().required(),
      messageId: a.string().required(),
      s3Key: a.string().required(),
      contentType: a.string(),
      size: a.integer(),
      uploadedAt: a.datetime(),
      whatsappMediaId: a.string(),
    } )
    .identifier( [ 'fileId' ] )
    .secondaryIndexes( ( index ) => [ index( 'messageId' ) ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 7: DLQMessages - Failed message retry queue (TTL: 7 days)
  DLQMessage: a
    .model( {
      dlqMessageId: a.id().required(),
      originalMessageId: a.string(),
      queueName: a.string().required(),
      retryCount: a.integer().default( 0 ),
      lastAttemptAt: a.datetime(),
      payload: a.string(),
      expiresAt: a.integer(), // TTL: Unix epoch seconds (7 days)
    } )
    .identifier( [ 'dlqMessageId' ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 8: AuditLogs - System audit trail (TTL: 180 days)
  AuditLog: a
    .model( {
      logId: a.id().required(),
      userId: a.string(),
      action: a.string().required(),
      resourceType: a.string(),
      resourceId: a.string(),
      timestamp: a.datetime(),
      details: a.string(),
      expiresAt: a.integer(), // TTL: Unix epoch seconds (180 days)
    } )
    .identifier( [ 'logId' ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 9: AIInteractions - AI query/response logs
  AIInteraction: a
    .model( {
      interactionId: a.id().required(),
      messageId: a.string(),
      query: a.string(),
      response: a.string(),
      approved: a.boolean().default( false ),
      feedback: a.string(),
      timestamp: a.datetime(),
    } )
    .identifier( [ 'interactionId' ] )
    .secondaryIndexes( ( index ) => [ index( 'messageId' ) ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 10: Rate limiting counters. Physical table is `RateLimitTable` - the
  // model name keeps the "Tracker" suffix the physical table drops, and that
  // mapping is recorded in scripts/check_data_model_drift.py EXPLICIT_TABLE.
  //
  // The identifier below was `[ 'channel', 'windowStart' ]` until 2026-09-25. The
  // live table has a SINGLE partition key, `id`, and no sort key. That is not a
  // cosmetic difference: lambda_utils/rate_limit.py followed this declaration,
  // called update_item with a composite key, got ValidationException on every
  // call, swallowed it and failed open - so bulk-worker and partner-onboarding
  // ran with no rate limit while their tests passed. Corrected here so the
  // declaration stops teaching the wrong schema. Verified by DescribeTable and a
  // read-only GetItem against both key shapes.
  RateLimitTracker: a
    .model( {
      // `{channel}:{resourceId}:{windowStart}` - see rate_limit.py and
      // outbound-whatsapp._check_rate_limit, which both write this shape.
      id: a.string().required(),
      channel: a.string(),
      windowStart: a.string(),
      messageCount: a.integer().default( 0 ),
      // TTL is ENABLED on this attribute on the live table, so it holds an
      // absolute expiry (windowStart + 24h), not a "last touched" stamp.
      lastUpdatedAt: a.integer(),
    } )
    .identifier( [ 'id' ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 11: SystemConfig - System configuration key-value store
  SystemConfig: a
    .model( {
      configKey: a.string().required(),
      configValue: a.string(),
      updatedBy: a.string(),
      updatedAt: a.datetime(),
    } )
    .identifier( [ 'configKey' ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 12: VoiceCalls - Voice call records (TTL: 90 days)
  VoiceCall: a
    .model( {
      callId: a.id().required(),
      contactId: a.string(),
      phoneNumber: a.string().required(),
      provider: a.enum( [ 'AWS', 'AIRTEL' ] ),
      callType: a.enum( [ 'TTS', 'AUDIO', 'IVR', 'CLICK_TO_CALL' ] ),
      direction: a.enum( [ 'INBOUND', 'OUTBOUND' ] ),
      status: a.enum( [ 'INITIATED', 'RINGING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'NO_ANSWER', 'BUSY' ] ),
      duration: a.integer().default( 0 ),
      recordingUrl: a.string(),
      providerCallId: a.string(),
      createdAt: a.datetime(),
      updatedAt: a.datetime(),
      expiresAt: a.integer(), // TTL: Unix epoch seconds (90 days)
    } )
    .identifier( [ 'callId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'contactId' ),
      index( 'phoneNumber' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // SmsAws REMOVED 2026-09-24. Declared a table `SmsAwsTable` that does not exist
  // in the account; SMS is stored in the canonical MessagesTable under
  // channel='sms' (messaging/sms-aws/handler.py `_store_message`). The three dead
  // constants naming the absent table, and the system-cleanup registry entry that
  // raised ResourceNotFound on every run, were removed in the same change.
  // Table 17: VoiceAws - AWS Pinpoint Voice Calls (dedicated, TTL: 90 days)
  VoiceAws: a
    .model( {
      callId: a.id().required(),
      contactId: a.string(),
      phoneNumber: a.string().required(),
      direction: a.enum( [ 'INBOUND', 'OUTBOUND' ] ),
      callType: a.string(), // tts, audio
      status: a.string(), // initiated, completed, failed
      duration: a.integer().default( 0 ),
      voiceId: a.string(),
      messageText: a.string(),
      providerCallId: a.string(),
      campaignId: a.string(),
      campaignName: a.string(),
      recordingUrl: a.string(),
      errorDetails: a.string(),
      createdAt: a.integer(),
      updatedAt: a.integer(),
      expiresAt: a.integer(), // TTL
    } )
    .identifier( [ 'callId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'contactId' ),
      index( 'phoneNumber' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 15b: DLTTemplates - DLT Template Registry for Airtel SMS
  DLTTemplates: a
    .model( {
      templateId: a.id().required(),
      name: a.string().required(),
      content: a.string().required(),
      messageType: a.string(), // SERVICE_EXPLICIT, SERVICE_IMPLICIT, TRANSACTIONAL, PROMOTIONAL
      senderId: a.string().default( 'WDBEEP' ),
      entityId: a.string().default( '1201161991108627443' ),
      variables: a.string().array(), // extracted {#var#} placeholders
      status: a.enum( [ 'active', 'inactive' ] ),
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'templateId' ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // RcsMessages REMOVED 2026-09-24. Legacy RCS store. All writes stopped in the
  // Phase 4 migration and the canonical MessagesTable is the sole store; the
  // RCS_TABLE constants naming the absent table went on 2026-09-21. The name stays
  // in ACCEPTED_ABSENT in scripts/audit_data_model_drift.py so a reintroduction is
  // still reported.
  // AirtelC2C and AirtelSMS REMOVED 2026-09-24. Both physical tables were deleted
  // on 2026-09-20 with the Airtel retirement, so both models described storage that
  // does not exist. The read paths that still name those tables are deliberate -
  // they exist to keep retired-provider history reachable - and they now report the
  // absence as 410 / storeAbsent through lambda_utils/retired_store rather than
  // raising. See ACCEPTED_ABSENT in scripts/audit_data_model_drift.py.
  //
  // The DLT sender metadata that used to sit above AirtelSMS (Sender ID WDBEEP,
  // Entity ID 1201161991108627443) is India DLT registration data, not provider
  // configuration, and lives in the DLTTemplates model below - which has a real
  // live table.
  // Table 13: VoiceCDR - Airtel Voice CDR Records (TTL: 90 days)
  // Inbound Number: +91 9319767034 (Mobile · Delhi) | Email: voice@wecare.digital
  VoiceCDR: a
    .model( {
      id: a.id().required(),
      vmSessionId: a.string().required(), // Airtel unique session ID
      clientCorrelationId: a.string(), // Xchange ID for searching
      customerId: a.string(), // Customer name in Airtel system

      // Timestamps (epoch milliseconds from Airtel)
      startTime: a.integer(),
      endTime: a.integer(),
      callAnswerTime: a.integer(),
      timestamp: a.string(), // Airtel formatted timestamp

      // Duration fields (milliseconds)
      durationMs: a.integer(),
      durationSec: a.float(),
      fromWaitingTimeMs: a.integer(), // IVR wait time
      fromWaitingTimeSec: a.float(),
      conversationDurationMs: a.integer(), // Actual talk time
      conversationDurationSec: a.float(),
      billableDurationMs: a.integer(),
      billableDurationSec: a.float(),

      // Call details
      callType: a.enum( [ 'INBOUND', 'OUTBOUND' ] ),
      overallCallStatus: a.string(), // Answered, Missed, Disconnected, Busy
      hangupStatus: a.string(), // Party A, Party B, SYSTEM_INITIATED
      hangupCause: a.string(), // SYSTEM_INITIATED, USER_INITIATED

      // Phone numbers
      callerId: a.string(), // CLI number
      callerNumber: a.string(), // From number
      destinationNumber: a.string(), // To number
      calledNumber: a.string(), // Airtel VN for inbound
      displayCliDestination: a.string(),

      // Status details
      callerNumberStatus: a.string(), // Disconnected, NetworkError, NotReachable, Busy, Noanswer, Answer
      callerNumberStatusDetails: a.string(), // SIP code details
      destinationNumberStatus: a.string(),
      destinationNumberStatusDetails: a.string(),

      // Circle and operator info
      circleNameCaller: a.string(), // State name
      circleNameDestination: a.string(),
      operatorNameCaller: a.string(), // Bharti Airtel, Jio, etc.
      operatorNameDestination: a.string(),

      // Recording
      recordingURL: a.string(),
      s3RecordingKey: a.string(),
      s3RecordingUrl: a.string(),

      // Retry info
      retryCountCaller: a.integer(),
      retryCountDestination: a.integer(),

      // Caller/Destination names (from participants)
      callerName: a.string(),
      destinationName: a.string(),

      // Caller duration & setup time
      callerDuration: a.integer(), // Total caller duration in ms
      callerDurationSec: a.float(),
      callSetupTimeCaller: a.integer(), // Call setup time in ms

      // Per-participant timing (epoch ms from participants array)
      callerStartTime: a.integer(),
      callerEndTime: a.integer(),
      callerAnswerTime: a.integer(),
      destStartTime: a.integer(),
      destEndTime: a.integer(),
      destAnswerTime: a.integer(),

      // Audio/IVR URLs (from participants array)
      callerAudioUrl: a.string(),
      destinationAudioUrl: a.string(),

      // OBD Campaign fields
      campaignId: a.string(),
      campaignName: a.string(),
      pulseCount: a.integer(), // Pulse count per Airtel spec
      dtmfCapture: a.string(), // DTMF capture
      missedDestinationNumber: a.string(), // Missed destination number

      // Participants & Events (stored as JSON strings)
      participantsJson: a.string(), // Full participants array
      eventsJson: a.string(), // Full events array

      // Derived overall call status (per Airtel spec matrix)
      derivedOverallStatus: a.string(), // Computed from caller + destination status

      // Metadata
      participantsCount: a.integer(),
      source: a.string().default( 'airtel_cdr_webhook' ),
      inboundNumber: a.string().default( '+919319767034' ),

      createdAt: a.integer(), // Unix epoch seconds
      expiresAt: a.integer(), // TTL: Unix epoch seconds (90 days)
    } )
    .identifier( [ 'id' ] )
    .secondaryIndexes( ( index ) => [
      index( 'vmSessionId' ),
      index( 'callerNumber' ),
      index( 'callType' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 16: OBDCampaigns - Airtel OBD Campaign Records (TTL: 90 days)
  OBDCampaign: a
    .model( {
      id: a.id().required(),
      campaignId: a.string(),
      airtelCampaignId: a.string(), // Airtel-assigned campaign ID
      campaignName: a.string().required(),
      status: a.string().default( 'created' ), // created, running, completed, failed, DELETED
      audioUrl: a.string(),
      sheetFileNames: a.string(), // JSON array of uploaded CSV filenames
      contactCount: a.integer().default( 0 ),
      createdAt: a.integer(),
      updatedAt: a.integer(),
      ttl: a.integer(), // TTL: Unix epoch seconds (90 days)
    } )
    .identifier( [ 'id' ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 18: ScheduledMessages - Scheduled WhatsApp messages
  ScheduledMessage: a
    .model( {
      scheduledId: a.id().required(),
      contactId: a.string().required(),
      contactName: a.string(),
      contactPhone: a.string(),
      recipientBsuid: a.string(), // Recipient's BSUID for BSUID-only sends
      templateName: a.string().required(),
      templateParams: a.string().array(), // template variable values
      phoneNumberId: a.string(),
      scheduledAt: a.datetime().required(),
      status: a.enum( [ 'PENDING', 'SENT', 'FAILED', 'CANCELLED' ] ),
      sentAt: a.datetime(),
      errorDetails: a.string(),
      createdAt: a.datetime(),
      updatedAt: a.datetime(),
    } )
    .identifier( [ 'scheduledId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'contactId' ),
      index( 'status' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 19: WhatsAppVoice - WhatsApp TTS/Audio voice message logs (TTL: 90 days)
  WhatsAppVoice: a
    .model( {
      messageId: a.id().required(),
      contactId: a.string(),
      phoneNumber: a.string(),
      recipientBsuid: a.string(), // Recipient's BSUID for voice messages
      messageText: a.string(),
      voiceId: a.string(), // Polly voice ID
      languageCode: a.string(),
      audioSize: a.integer(),
      s3Key: a.string(),
      whatsappMediaId: a.string(),
      whatsappMessageId: a.string(),
      status: a.string(), // sent, failed
      type: a.string().default( 'tts' ), // tts, audio
      transcription: a.string(), // English transcription of voice note
      detectedLanguage: a.string(), // Detected source language
      createdAt: a.integer(),
      expiresAt: a.integer(), // TTL
    } )
    .identifier( [ 'messageId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'contactId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 20: Payments - Razorpay payment records
  Payment: a
    .model( {
      id: a.id().required(),
      paymentId: a.string(), // Razorpay payment ID
      orderId: a.string(), // Razorpay order ID
      referenceId: a.string(),
      status: a.string(), // captured, failed, refunded
      amount: a.integer(), // Amount in paise
      amountInRupees: a.float(),
      currency: a.string().default( 'INR' ),
      method: a.string(), // upi, card, netbanking, wallet
      contact: a.string(),
      email: a.string(),
      notes: a.string(), // JSON string
      source: a.string().default( 'razorpay_webhook' ),
      createdAt: a.integer(),
    } )
    .identifier( [ 'id' ] )
    .secondaryIndexes( ( index ) => [
      index( 'paymentId' ),
      index( 'orderId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 21: WhatsAppCalling - WhatsApp voice/video call logs
  WhatsAppCalling: a
    .model( {
      id: a.id().required(),
      callId: a.string(),
      wabaId: a.string(),
      phoneNumberId: a.string(),
      displayPhone: a.string(), // Display phone number from webhook metadata
      fromNumber: a.string(),
      toNumber: a.string(),
      callerName: a.string(), // Caller's profile name from contacts array
      fromBsuid: a.string(), // Caller's BSUID (from webhook from_user_id / to_user_id)
      fromParentBsuid: a.string(), // Caller's parent BSUID (from webhook from_parent_user_id / to_parent_user_id)
      callerUsername: a.string(), // Caller's WhatsApp username
      direction: a.string(), // inbound, outbound
      eventType: a.string(), // connect, terminate, permission_response
      status: a.string(), // ringing, ended, logged
      terminateReason: a.string(),
      errorCode: a.string(), // Meta error code (138000-138023) from terminate events
      permission: a.string(), // GRANTED/REJECTED/REVOKED for permission events
      duration: a.integer(),
      sdpOffer: a.string(),
      sdpType: a.string(),
      apiResponse: a.string(), // Truncated API response for debugging
      rawEvent: a.string(),
      timestamp: a.string(),
      createdAt: a.integer(),
      updatedAt: a.integer(),
      ttl: a.integer(), // TTL: Unix epoch seconds (90 days)
    } )
    .identifier( [ 'id' ] )
    .secondaryIndexes( ( index ) => [
      index( 'callId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 22: WhatsAppGroup - WhatsApp Business group tracking & state
  // (Merged: original Table 22 + Table 37 fields into single model)
  WhatsAppGroup: a
    .model( {
      id: a.id().required(),
      groupId: a.string().required(), // Meta group ID
      wabaId: a.string(),
      phoneNumberId: a.string(),
      subject: a.string(), // Group name/subject
      description: a.string(),
      inviteLink: a.string(),
      joinApprovalMode: a.string(), // auto_approve | approval_required
      participantCount: a.integer().default( 0 ),
      maxParticipants: a.integer().default( 512 ),
      owner: a.string(),
      creatorPhone: a.string(),
      participantsJson: a.string(), // JSON array of participants
      suspended: a.boolean().default( false ),
      status: a.string().default( 'active' ), // active, archived, deleted
      lastMessageAt: a.integer(),
      createdAt: a.integer(),
      updatedAt: a.integer(),
      ttl: a.integer(),
    } )
    .identifier( [ 'id' ] )
    .secondaryIndexes( ( index ) => [
      index( 'groupId' ),
      index( 'wabaId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 23: WhatsAppInbound - Inbound WhatsApp messages
  WhatsAppInbound: a
    .model( {
      id: a.id().required(),
      contactId: a.string(),
      phone: a.string(),
      senderName: a.string(),
      senderBsuid: a.string(), // Sender's BSUID (from webhook user_id)
      senderParentBsuid: a.string(), // Sender's parent BSUID (from webhook parent_user_id)
      senderUsername: a.string(), // Sender's WhatsApp username (from webhook)
      messageType: a.string(), // text, image, video, audio, document, location, sticker, reaction
      content: a.string(),
      mediaId: a.string(),
      s3Key: a.string(),
      mediaUrl: a.string(),
      mimeType: a.string(),
      whatsappMessageId: a.string(),
      status: a.string(), // received, read, processed
      templateName: a.string(),
      transcription: a.string(), // English transcription of inbound voice notes
      detectedLanguage: a.string(), // Detected language of voice note
      timestamp: a.string(),
      createdAt: a.integer(),
      expiresAt: a.integer(), // TTL
    } )
    .identifier( [ 'id' ] )
    .secondaryIndexes( ( index ) => [
      index( 'contactId' ),
      index( 'whatsappMessageId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 23: WhatsAppOutbound - Outbound WhatsApp messages
  WhatsAppOutbound: a
    .model( {
      id: a.id().required(),
      contactId: a.string(),
      phone: a.string(),
      recipientBsuid: a.string(), // Recipient's BSUID (when sending to BSUID)
      parentRecipientBsuid: a.string(), // Recipient's parent BSUID (from status webhooks)
      templateName: a.string(),
      templateCategory: a.string(), // UTILITY, MARKETING, AUTHENTICATION
      templateParams: a.string(), // JSON array
      content: a.string(),
      mediaId: a.string(),
      s3Key: a.string(),
      mediaUrl: a.string(),
      whatsappMessageId: a.string(),
      status: a.string(), // sent, delivered, read, failed
      errorDetails: a.string(),
      phoneNumberId: a.string(),
      transcription: a.string(), // English transcription of outbound voice notes
      detectedLanguage: a.string(), // Language of outbound voice note
      timestamp: a.string(),
      createdAt: a.integer(),
      expiresAt: a.integer(), // TTL
    } )
    .identifier( [ 'id' ] )
    .secondaryIndexes( ( index ) => [
      index( 'contactId' ),
      index( 'whatsappMessageId' ),
      index( 'templateName' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 25: WixProductsCache - Cached Wix Store products
  WixProductsCache: a
    .model( {
      productId: a.id().required(),
      name: a.string(),
      slug: a.string(),
      price: a.string(),
      currency: a.string(),
      inStock: a.boolean(),
      productType: a.string(),
      mediaUrl: a.string(),
      rawData: a.string(), // Full Wix product JSON
      syncedAt: a.datetime(),
    } )
    .identifier( [ 'productId' ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 26: WixOrdersCache - Cached Wix Store orders
  WixOrdersCache: a
    .model( {
      orderId: a.id().required(),
      orderNumber: a.string(),
      externalOrderId: a.string(), // Custom order number from external channel
      buyerEmail: a.string(),
      buyerPhone: a.string(),
      totalPrice: a.string(),
      currency: a.string(),
      paymentStatus: a.string(),
      fulfillmentStatus: a.string(),
      status: a.string(), // APPROVED, CANCELED, etc.
      lineItemCount: a.integer(),
      createdDate: a.string(),
      rawData: a.string(), // Full Wix order JSON
      syncedAt: a.datetime(),
    } )
    .identifier( [ 'orderId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'buyerEmail' ),
      index( 'paymentStatus' ),
      index( 'orderNumber' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 24: TemplateAnalytics - WhatsApp template send/delivery tracking
  TemplateAnalytics: a
    .model( {
      id: a.id().required(),
      templateName: a.string().required(),
      templateCategory: a.string(), // UTILITY, MARKETING, AUTHENTICATION
      phone: a.string(),
      status: a.string(), // sent, delivered, read, failed
      whatsappMessageId: a.string(),
      timestamp: a.string(),
      createdAt: a.integer(),
    } )
    .identifier( [ 'id' ] )
    .secondaryIndexes( ( index ) => [
      index( 'templateName' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),
  // Table 27: SubmitRequests - WhatsApp Flow submit request submissions
  SubmitRequest: a
    .model( {
      id: a.id().required(),
      requestId: a.string().required(), // Lambda request ID
      flowToken: a.string(),
      phone: a.string().required(),
      senderName: a.string(),
      contactId: a.string(),
      orderId: a.string().required(),
      subject: a.string(),
      description: a.string(),
      paymentStatus: a.string().default( 'pending' ), // pending, captured, failed
      paymentReferenceId: a.string(), // SR-{orderId}-{requestId}
      paymentAmount: a.integer().default( 4900 ), // paise
      transactionId: a.string(),
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'id' ] )
    .secondaryIndexes( ( index ) => [
      index( 'phone' ),
      index( 'orderId' ),
      index( 'paymentStatus' ),
      index( 'paymentReferenceId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 28: ConversationHistory - AI conversation context per phone hash
  ConversationHistory: a
    .model( {
      phoneHash: a.string().required(),
      lastMessage: a.string(),
      lastResponse: a.string(),
      pendingPaymentRef: a.string(),
      customerProfile: a.string(), // JSON string
      languagePreference: a.string(),
      autoReplyEnabled: a.boolean().default( true ),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'phoneHash' ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 29: WixOrderIds - Mapping between Wix order IDs and WD-ORD numbers
  WixOrderId: a
    .model( {
      wixOrderId: a.string().required(),
      wdOrderNumber: a.string().required(),
      createdAt: a.integer(),
    } )
    .identifier( [ 'wixOrderId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'wdOrderNumber' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 30: Invoice - Invoice records
  Invoice: a
    .model( {
      invoiceId: a.id().required(),
      invoiceNumber: a.string(),
      contactId: a.string(),
      contactName: a.string(),
      contactPhone: a.string(),
      contactEmail: a.string(),
      // Customer fields (used by invoice-engine Lambda)
      customerName: a.string(),
      customerPhone: a.string(),
      paidByPhone: a.string(),
      customerEmail: a.string(),
      shippingAddress: a.string(),
      billingAddress: a.string(),
      gstin: a.string(),
      status: a.string().default( 'created' ), // created, pending_payment, sent, paid, cancelled
      paymentStatus: a.string().default( 'pending' ), // pending, captured, failed, refunded
      entryPoint: a.string(), // manual, pay_flow, whatsapp_payment, webhook
      subtotal: a.integer(), // paise
      taxAmount: a.integer(),
      tax: a.float(), // rupees (used by invoice-engine)
      totalAmount: a.integer(),
      total: a.float(), // rupees (used by invoice-engine)
      discount: a.float(),
      shipping: a.float(),
      handling: a.float(),
      gstRate: a.float(),
      convenienceFee: a.float(),
      currency: a.string().default( 'INR' ),
      referenceId: a.string(), // payment reference
      paymentId: a.string(), // Razorpay payment ID
      orderId: a.string(),
      purpose: a.string(),
      notes: a.string(),
      remarks: a.string(), // JSON array of remarks/refunds/credit notes
      imageUrl: a.string(),
      pdfUrl: a.string(),
      s3Key: a.string(),
      fy: a.string(), // financial year
      paidAt: a.integer(),
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'invoiceId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'contactId' ),
      index( 'referenceId' ),
      index( 'status' ),
      index( 'invoiceNumber' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 31: InvoiceItem - Line items per invoice
  InvoiceItem: a
    .model( {
      invoiceId: a.string().required(),
      itemId: a.string().required(),
      description: a.string(),
      quantity: a.integer().default( 1 ),
      unitPrice: a.integer(), // paise
      amount: a.integer(), // paise
      hsnCode: a.string(),
      gstRate: a.float(),
    } )
    .identifier( [ 'invoiceId', 'itemId' ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 32: InvoiceAsset - Generated invoice images/PDFs
  InvoiceAsset: a
    .model( {
      assetId: a.id().required(),
      invoiceId: a.string().required(),
      assetType: a.string(), // image, pdf
      s3Key: a.string(),
      url: a.string(),
      createdAt: a.integer(),
    } )
    .identifier( [ 'assetId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'invoiceId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 33: InvoiceDeliveryLog - Invoice delivery tracking
  InvoiceDeliveryLog: a
    .model( {
      id: a.id().required(),
      invoiceId: a.string().required(),
      channel: a.string(), // whatsapp, email
      status: a.string(), // sent, delivered, failed
      recipient: a.string(),
      waMessageId: a.string(),
      createdAt: a.integer(),
    } )
    .identifier( [ 'id' ] )
    .secondaryIndexes( ( index ) => [
      index( 'invoiceId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 34: InvoiceSequence - Auto-increment invoice number tracking per FY
  InvoiceSequence: a
    .model( {
      fy: a.string().required(), // e.g. "2025-26"
      lastSeq: a.integer().default( 0 ),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'fy' ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 35: RazorpayWebhookLog - Raw Razorpay webhook event log
  RazorpayWebhookLog: a
    .model( {
      id: a.id().required(),
      eventType: a.string(), // payment.captured, payment.failed, etc.
      paymentId: a.string(),
      orderId: a.string(),
      amount: a.integer(),
      status: a.string(),
      rawPayload: a.string(), // JSON string
      razorpayEventId: a.string(), // Idempotency key
      processedAt: a.integer(),
      createdAt: a.integer(),
      expiresAt: a.integer(), // TTL: Unix epoch seconds (180 days)
    } )
    .identifier( [ 'id' ] )
    .secondaryIndexes( ( index ) => [
      index( 'paymentId' ),
      index( 'eventType' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // (Table 36 PayUWebhookLog removed 2026-09-20 — PayU is retired. No PayU
  //  payment configuration exists on either WABA, no PayU Lambda or route
  //  remains, and stack-wecare-digital-PayUWebhookLogTable was deleted from the
  //  account after verifying ItemCount==0. Razorpay is the only gateway.)

  // (Table 37 WhatsAppGroup removed — merged into Table 22 above)

  // Table 38: WebhookDedup - Webhook idempotency tracking for inbound events
  WebhookDedup: a
    .model( {
      eventId: a.string().required(), // Unique event identifier
      source: a.string().required(), // whatsapp, razorpay
      processedAt: a.integer(),
      expiresAt: a.integer(), // TTL: 7 days
      ttl: a.integer(), // TTL attribute for backend.ts override
      // Lease fields. `claim_event` claims permanently, which is right for an inbound message:
      // a Meta redelivery hours later must not re-insert it. But taking the claim BEFORE the work
      // and never releasing it means a handler exception makes the provider's retry look like a
      // duplicate, and on payment.captured that silently discards a captured payment.
      // `claim_event_with_lease` writes these two instead, so an uncompleted lease lapses and the
      // retry gets through. Absent on every legacy row, which is what keeps those non-reclaimable.
      leaseExpiresAt: a.integer(), // epoch seconds; absent = permanent claim
      completedAt: a.integer(), // set only after the work succeeded
    } )
    .identifier( [ 'eventId' ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 42: PaymentAttempt - the entity that exists BEFORE payment, and is not an order.
  //
  // Most payment attempts never become orders, and that is normal rather than exceptional: an
  // abandoned checkout, a timed-out UPI mandate, a declined card. Every one leaves a record that
  // has to be visible to the customer and to staff, and none may carry an order number, appear in
  // order history, or produce a receipt.
  //
  // So there is deliberately NO orderId or orderNumber field here. The order identity lives in
  // `lambda_utils/ecommerce/order_keys` under PAYMENTATTEMPT#<id> and is minted only after a
  // provider readback confirms capture. Adding those fields to this model would make the rule
  // ("an order does not exist until payment is verified") depend on discipline instead of shape.
  PaymentAttempt: a
    .model( {
      paymentAttemptId: a.string().required(), // UUIDv7, internal, never shown to a customer
      customerId: a.string().required(), // CUS_<ULID>
      referenceId: a.string().required(), // the Meta/Razorpay join key, <=35 chars
      // Integer minor units. Floating-point money is prohibited on this path: 0.1 + 0.2 != 0.3 in
      // binary, and a one-paise difference must fail the payment closed, so a rounding artefact
      // would refuse a legitimate order.
      amountPaise: a.integer().required(),
      currency: a.string().default( 'INR' ), // compared explicitly, never inferred
      configurationName: a.string(), // the Meta payment configuration actually used
      provider: a.string().default( 'razorpay' ),
      cartId: a.string(),
      wixCheckoutId: a.string(),
      // CREATED | PAYMENT_READINESS_CHECKED | PAYMENT_REQUEST_SENT | PAYMENT_PENDING
      // then exactly one of PAYMENT_PAID | PAYMENT_FAILED | PAYMENT_CANCELLED | PAYMENT_EXPIRED
      status: a.string().default( 'CREATED' ),
      // Persisted rank, so the guard is a ConditionExpression rather than a read-then-write race.
      // PAYMENT_PAID outranks every failure: a late `failed` must not unpay a capture.
      attemptRank: a.integer(),
      attemptNumber: a.integer().default( 1 ),
      retryOf: a.string(), // previous paymentAttemptId, for retry lineage
      providerPaymentId: a.string(),
      providerOrderId: a.string(),
      failureCode: a.string(),
      failureReason: a.string(), // constructed from known-safe parts, never a provider string
      createdAt: a.integer(),
      updatedAt: a.integer(),
      paidAt: a.integer(),
      failedAt: a.integer(),
    } )
    .identifier( [ 'paymentAttemptId' ] )
    .secondaryIndexes( ( index ) => [
      // Payment history for one customer, newest first. `createdAt` is the sort key rather than a
      // client-side sort because history is read on every "my payments" view and an attempt chain
      // can be long after retries.
      index( 'customerId' ).sortKeys( [ 'createdAt' ] ),
      index( 'referenceId' ), // resolve an inbound payment event; a unique lookup, so no sort key
      // Staff view of stuck and failed attempts. Only 8 distinct partition values, so `createdAt`
      // is what keeps a query bounded to a window instead of reading the whole status partition.
      index( 'status' ).sortKeys( [ 'createdAt' ] ),
    ] )
    // No TTL, deliberately. A failed attempt is the record proving no order was created, and
    // payment history has to keep it.
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 39: SystemEvent - Persistent system event log (template status, quality, account updates)
  SystemEvent: a
    .model( {
      id: a.id().required(),
      eventType: a.string().required(), // template_status, phone_quality, account_update, user_id_update
      wabaId: a.string(),
      phoneNumberId: a.string(),
      eventData: a.string(), // JSON string
      severity: a.string().default( 'info' ), // info, warning, error, critical
      acknowledged: a.boolean().default( false ),
      createdAt: a.integer(),
      ttl: a.integer(), // TTL: 180 days
    } )
    .identifier( [ 'id' ] )
    .secondaryIndexes( ( index ) => [
      index( 'eventType' ),
      index( 'wabaId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 40: CatalogCache - WhatsApp Commerce catalog product cache
  CatalogCache: a
    .model( {
      id: a.id().required(),
      catalogId: a.string().required(),
      retailerId: a.string(), // Retailer/product ID
      name: a.string(),
      description: a.string(),
      price: a.string(),
      currency: a.string(),
      imageUrl: a.string(),
      availability: a.string(), // in_stock, out_of_stock
      rawData: a.string(), // Full product JSON
      syncedAt: a.integer(),
      ttl: a.integer(), // TTL: 7 days (cache refresh)
    } )
    .identifier( [ 'id' ] )
    .secondaryIndexes( ( index ) => [
      index( 'catalogId' ),
      index( 'retailerId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table 41: AdClickAttribution - Ads that Click to WhatsApp tracking
  AdClickAttribution: a
    .model( {
      id: a.id().required(),
      adId: a.string(),
      campaignId: a.string(),
      referralSource: a.string(), // ctwa (click-to-whatsapp)
      referralBody: a.string(), // Referral message body
      referralUrl: a.string(), // Source URL
      senderPhone: a.string(),
      contactId: a.string(),
      convertedAt: a.integer(), // When user performed target action
      conversionType: a.string(), // message_sent, purchase, signup
      createdAt: a.integer(),
      ttl: a.integer(), // TTL: 180 days
    } )
    .identifier( [ 'id' ] )
    .secondaryIndexes( ( index ) => [
      index( 'adId' ),
      index( 'contactId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // ============================================================
  // FLOW MANAGEMENT TABLES
  // ============================================================

  // Table: FlowRegistry — Config for every WhatsApp Flow
  FlowRegistry: a
    .model( {
      flowId: a.id().required(), // Meta flow ID
      flowCode: a.string().required(), // "01.WD_SR", "02.WD_ADDR", etc.
      flowName: a.string().required(), // Human readable
      flowType: a.string().required(), // form_submit, order_management, interactive, data_collection, payment, booking, feedback
      flowVersion: a.string(), // "7.3"
      dataApiVersion: a.string(), // "4.0"
      wabaId: a.string(), // Which WABA
      status: a.string().default( 'DRAFT' ), // DRAFT, PUBLISHED, DEPRECATED
      category: a.string(), // service_request, order, interactive, data_collection, payment, booking, feedback
      // Payment config
      requiresPayment: a.boolean().default( false ),
      paymentAmount: a.integer(), // paise (4900 = ₹49)
      paymentDescription: a.string(),
      // Payment gateway preference. Only 'razorpay' is supported since 2026-08-23;
      // PayU was removed from both WABAs on Meta. Retained for historical records.
      preferredGateway: a.string(),
      // Specific Meta payment config name: 'WECAREDIGITAL' or 'WECAREUPI'
      paymentConfigName: a.string(),
      // Screen routing config (JSON string)
      screenConfig: a.string(),
      // Contact enrichment mapping (JSON string) e.g. {"address_line1":"addressLine1","city":"city"}
      contactMapping: a.string(),
      // Data fetchers config (JSON string) — which screens need backend data
      dataFetchers: a.string(),
      // Submission number prefix e.g. "WD-SR", "WD-RET", "WD-BK"
      submissionPrefix: a.string(),
      // A/B testing config (JSON) e.g. {"enabled":true,"variantB_flowId":"xxx","splitPercent":50}
      abTestConfig: a.string(),
      // Metadata
      endpointUri: a.string(),
      publishedAt: a.integer(),
      createdAt: a.integer(),
      updatedAt: a.integer(),
      // Extended lifecycle/sync metadata (Part 4 A)
      categories: a.string(), // JSON array of Meta categories
      healthStatusJson: a.string(), // JSON of Meta health_status
      validationErrorsJson: a.string(), // JSON of Meta validation_errors
      previewUrl: a.string(),
      previewExpiresAt: a.integer(),
      lastSyncedAt: a.integer(),
      lastPublishedAt: a.integer(),
      lastDeprecatedAt: a.integer(),
      clonedFromFlowId: a.string(),
      migrationBatchId: a.string(),
      dataChannelUri: a.string(),
      jsonVersion: a.string(),
      applicationId: a.string(),
    } )
    .identifier( [ 'flowId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'flowCode' ),
      index( 'wabaId' ),
      index( 'category' ),
      index( 'status' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // ============================================================
  // ORDER MANAGEMENT TABLES
  // ============================================================

  // Table: Order — Central order repository (all sources: Wix, manual, Shopify, future)
  Order: a
    .model( {
      orderId: a.string().required(), // "WD-ORD-A1B2C3D4" — canonical full ID
      shortId: a.string().required(), // "A1B2C3D4" — 8-char hex for display
      // Source
      source: a.string().required(), // wix | manual | shopify | woocommerce | custom
      sourceOrderId: a.string(), // native ID from source store (e.g. Wix UUID)
      sourceOrderNumber: a.string(), // native display number (e.g. "10042") — internal only
      sourceRawPayload: a.string(), // JSON of raw source data for audit
      // Customer
      customerPhone: a.string().required(),
      customerName: a.string(),
      customerEmail: a.string(),
      contactId: a.string(), // link to ContactsTable
      // Order details
      orderDate: a.string(), // ISO date "2026-02-22"
      orderTime: a.string(), // "18:00:00"
      orderDateIST: a.string(), // "22 Feb 2026, 6:00 PM" — pre-formatted for dropdown
      itemsSummary: a.string(), // "Black Tee × 1, White Cap × 2"
      itemsJson: a.string(), // JSON array [{name, qty, price, sku, image}]
      itemCount: a.integer(),
      totalAmount: a.float(), // rupees (not paise)
      subtotal: a.float(),
      shippingAmount: a.float(),
      taxAmount: a.float(),
      discountAmount: a.float(),
      currency: a.string().default( 'INR' ),
      // Status
      orderStatus: a.string().default( 'active' ), // active | fulfilled | cancelled | returned
      paymentStatus: a.string().default( 'pending' ), // paid | not_paid | pending | refunded
      fulfillmentStatus: a.string(), // not_fulfilled | partially_fulfilled | fulfilled
      // Address
      shippingAddress: a.string(), // JSON or flat string
      billingAddress: a.string(),
      // Metadata
      buyerNote: a.string(),
      adminNotes: a.string(),
      tags: a.string(), // JSON array of tags
      // Timestamps
      createdAt: a.integer(),
      updatedAt: a.integer(),
      syncedAt: a.integer(), // last sync from source
    } )
    .identifier( [ 'orderId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'customerPhone' ),
      index( 'source' ),
      index( 'orderStatus' ),
      index( 'shortId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table: Appointment — Booking/scheduling for consultations and service visits
  Appointment: a
    .model( {
      appointmentId: a.id().required(),
      customerPhone: a.string().required(),
      customerName: a.string(),
      contactId: a.string(),
      orderId: a.string(), // optional link to order
      appointmentType: a.string(), // consultation | service_visit | follow_up | other
      slotDate: a.string(), // "2026-03-15"
      slotTime: a.string(), // "10:00 AM"
      duration: a.string(), // "30 min" | "1 hour"
      location: a.string(), // office | virtual | home_visit
      status: a.string().default( 'booked' ), // booked | confirmed | rescheduled | cancelled | completed | no_show
      notes: a.string(),
      adminNotes: a.string(),
      assignedTo: a.string(),
      reminderSent: a.boolean().default( false ),
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'appointmentId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'customerPhone' ),
      index( 'slotDate' ),
      index( 'status' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table: RxSlot — Prescription/medical tourism slot booking
  RxSlot: a
    .model( {
      rxSlotId: a.id().required(),
      customerPhone: a.string().required(),
      customerName: a.string(),
      contactId: a.string(),
      orderId: a.string(), // optional link to order
      slotType: a.string(), // prescription | medical_tourism | lab_test | pharmacy
      slotDate: a.string(), // "2026-03-15"
      slotTime: a.string(), // "10:00 AM"
      facilityName: a.string(),
      doctorName: a.string(),
      status: a.string().default( 'booked' ), // booked | confirmed | cancelled | completed
      prescriptionNotes: a.string(),
      adminNotes: a.string(),
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'rxSlotId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'customerPhone' ),
      index( 'slotDate' ),
      index( 'status' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table: Document — Customer document management (WhatsApp uploads, manual, web)
  Document: a
    .model( {
      documentId: a.id().required(),
      customerPhone: a.string().required(),
      customerName: a.string(),
      contactId: a.string(),
      orderId: a.string(), // optional link to order
      submissionId: a.string(), // optional link to FlowSubmission
      // Source
      sourceType: a.string().required(), // whatsapp | manual | web | flow
      sourceReferenceId: a.string(), // WhatsApp media ID or upload ref
      // Document details
      documentType: a.string(), // id_proof | address_proof | prescription | invoice | photo | other
      fileName: a.string(),
      fileUrl: a.string(), // S3 URL or CDN URL
      storageKey: a.string(), // S3 key
      mimeType: a.string(),
      fileSize: a.integer(), // bytes
      // Verification
      verificationStatus: a.string().default( 'uploaded' ), // uploaded | under_review | approved | rejected | reupload_required
      remarks: a.string(), // admin remarks or rejection reason
      // Metadata
      tags: a.string(), // JSON array
      uploadedAt: a.integer(),
      reviewedAt: a.integer(),
      reviewedBy: a.string(),
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'documentId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'customerPhone' ),
      index( 'orderId' ),
      index( 'verificationStatus' ),
      index( 'sourceType' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table: EnterpriseAssist — B2B/corporate support cases
  EnterpriseAssist: a
    .model( {
      caseId: a.id().required(),
      contactPhone: a.string().required(),
      contactName: a.string(),
      contactEmail: a.string(),
      accountName: a.string(), // company name
      subject: a.string(),
      description: a.string(),
      priority: a.string().default( 'normal' ), // low | normal | high | urgent
      status: a.string().default( 'open' ), // open | in_progress | resolved | closed
      assignedTo: a.string(),
      notes: a.string(),
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'caseId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'contactPhone' ),
      index( 'status' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table: Review — Customer feedback and ratings
  Review: a
    .model( {
      reviewId: a.id().required(),
      customerPhone: a.string().required(),
      customerName: a.string(),
      contactId: a.string(),
      orderId: a.string(), // optional link
      rating: a.integer(), // 1-5
      reviewText: a.string(),
      category: a.string(), // service | product | delivery | support | other
      status: a.string().default( 'submitted' ), // submitted | approved | hidden
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'reviewId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'customerPhone' ),
      index( 'status' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table: Faq — Customer service FAQ content
  Faq: a
    .model( {
      faqId: a.id().required(),
      category: a.string().required(),
      question: a.string().required(),
      answer: a.string().required(),
      sortOrder: a.integer().default( 0 ),
      isActive: a.boolean().default( true ),
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'faqId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'category' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table: RequestStatusHistory — Audit trail for request status changes
  RequestStatusHistory: a
    .model( {
      historyId: a.id().required(),
      submissionId: a.string().required(), // link to FlowSubmission
      orderId: a.string(), // link to Order
      oldStatus: a.string(),
      newStatus: a.string(),
      changedBy: a.string(), // "admin:userId" | "system" | "webhook"
      changedByName: a.string(),
      notes: a.string(),
      changedAt: a.integer(),
    } )
    .identifier( [ 'historyId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'submissionId' ),
      index( 'orderId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table: DocumentHistory — Audit trail for document actions
  DocumentHistory: a
    .model( {
      historyId: a.id().required(),
      documentId: a.string().required(),
      action: a.string().required(), // uploaded | reviewed | approved | rejected | reupload_requested | deleted
      actorType: a.string(), // admin | system | customer
      actorId: a.string(),
      remarks: a.string(),
      createdAt: a.integer(),
    } )
    .identifier( [ 'historyId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'documentId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // AdminActionLog REMOVED 2026-09-24. Declared an `AdminActionLogsTable` that does
  // not exist, and had zero readers and zero writers anywhere in the repo - the
  // declaration was its only mention. The live admin audit trail is the AuditLog
  // model on stack-wecare-digital-AuditLogsTable, written through
  // lambda_utils/audit.py.
  // Table: AmendmentHistory — Track amendments to submissions
  AmendmentHistory: a
    .model( {
      amendmentId: a.id().required(),
      submissionId: a.string().required(),
      orderId: a.string(),
      amendmentType: a.string().required(), // add_info | correct_details | change_type | cancel | other
      description: a.string().required(),
      submittedBy: a.string(), // phone or userId
      status: a.string().default( 'submitted' ), // submitted | reviewed | applied | rejected
      reviewedBy: a.string(),
      reviewNotes: a.string(),
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'amendmentId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'submissionId' ),
      index( 'orderId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table: FlowSubmission — All flow submissions (generic, all flow types)
  FlowSubmission: a
    .model( {
      submissionId: a.id().required(),
      flowId: a.string().required(), // Meta flow ID
      flowCode: a.string().required(), // "01.WD_SR"
      flowType: a.string(), // form_submit, order_management, etc.
      flowVersion: a.string(), // "7.3"
      // Who
      phone: a.string().required(),
      contactId: a.string(),
      senderName: a.string(),
      // What — full form data as JSON
      formData: a.string(), // JSON string of all form fields
      // Extracted common fields for querying
      orderId: a.string(),
      requestType: a.string(),
      subject: a.string(),
      description: a.string(),
      // Reference numbers
      submissionNumber: a.string(), // "WD-SR-A1B2C3D4"
      flowToken: a.string(),
      // Payment tracking
      paymentRequired: a.boolean().default( false ),
      paymentAmount: a.integer(), // paise
      paymentStatus: a.string().default( 'none' ), // none, pending, captured, failed, refunded
      paymentRefId: a.string(), // "WD-PAY-XXXXXXXX"
      invoiceId: a.string(),
      transactionId: a.string(), // Payment gateway txn ID
      paidAt: a.integer(),
      // Lifecycle
      status: a.string().default( 'open' ), // open, in_progress, resolved, closed, cancelled
      assignedTo: a.string(),
      notes: a.string(),
      resolvedAt: a.integer(),
      // Timestamps
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'submissionId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'phone' ),
      index( 'flowCode' ),
      index( 'paymentStatus' ),
      index( 'paymentRefId' ),
      index( 'submissionNumber' ),
      index( 'status' ),
      index( 'orderId' ),
      index( 'flowId' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // Table: FlowDraft — Draft persistence for interrupted flows (TTL: 7 days)
  FlowDraft: a
    .model( {
      draftKey: a.string().required(), // "{phone}#{flowCode}"
      phone: a.string().required(),
      flowCode: a.string().required(),
      screen: a.string(), // Last screen the user was on
      formData: a.string(), // JSON of accumulated form data
      updatedAt: a.integer(),
      ttl: a.integer(), // TTL: 7 days
    } )
    .identifier( [ 'draftKey' ] )
    .secondaryIndexes( ( index ) => [
      index( 'phone' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // ═══════════════════════════════════════════════════════════════════════
  // PSTN voice (Plivo) — five models RETIRED from this file on 2026-09-23.
  //
  //   PstnCall  PstnCallEvent  PstnAgentPresence  PstnFlowVersion
  //   PstnRecordingAudit
  //
  // None of them existed in the account. Verified against all 76 live tables:
  // the only PSTN table is `PstnSoftphoneSessions`, provisioned by
  // scripts/provision_pstn_softphone.py. Nothing in amplify/functions read or
  // wrote any of the five, so there was no migration to perform.
  //
  // This is the same mistake as PstnNotificationDelivery, noted below and removed
  // on 2026-09-21: a declaration here is not evidence that a table exists, and
  // that gap cost a real outage - every claim raised ClaimStoreUnavailable and
  // /plivo/dial-events answered 503 without sending, while the source looked
  // complete. Five more declarations in the same shape are five more of those
  // waiting, so they are removed rather than left to be discovered by a handler.
  //
  // Where each concern actually lives now:
  //
  //   PstnCall            -> VoiceCDRTable. It is the live call record: 56 rows,
  //                          written by plivo-answer._persist_cdr on every
  //                          callback. NOT read-only for audit, whatever the
  //                          older comment in this file claimed. Per-leg billing
  //                          is the one thing PstnCall modelled that VoiceCDR
  //                          does not; it is unreachable until browser routing is
  //                          enabled, so it belongs to that change, not to a
  //                          table nothing writes.
  //   PstnCallEvent       -> the lifecycle ordering problem this was meant to
  //                          solve is solved in place instead: `cdrRank` plus a
  //                          conditional update in _persist_cdr, so a late
  //                          mid-call callback can no longer overwrite a
  //                          completed call. An append-only event log with no
  //                          reader would not have prevented that.
  //   PstnAgentPresence   -> PstnSoftphoneSessions + lambda_utils/pstn/softphone.py,
  //                          which keeps the distinction that mattered here: the
  //                          local leg being up is not the remote party having
  //                          answered, and talk_time_seconds returns None rather
  //                          than 0 when nobody did.
  //   PstnFlowVersion     -> nothing. The IVR is _answer_xml() in plivo-answer,
  //                          a single hardcoded revision. Versioned flows need a
  //                          flow editor to version; declaring the store first
  //                          gets the order backwards.
  //   PstnRecordingAudit  -> nothing, and correctly so: there is no recording
  //                          feature. `recordingRef` was never written by any
  //                          handler. An audit table for an absent capability
  //                          records nothing and implies the capability exists.
  //
  // Reinstate by reverting this commit AND adding a provisioning script, in that
  // order. A declaration alone will not create a table - that is the whole point
  // of this note.
  // ═══════════════════════════════════════════════════════════════════════

  // PstnNotificationDelivery was declared here until 2026-09-21 and existed in
  // none of the 66 live tables (NOTIF-STORE-001). Its identifier scheme and
  // eligibility/state vocabulary live on in lambda_utils/notifications, which
  // adds the whatsapp channel, an append-only attempt history and a
  // transactional outbox. Those four tables are provisioned and verified by
  // scripts/provision_notification_domain.py rather than declared here,
  // because a declaration in this file is not evidence a table exists - which
  // is precisely how the original came to be permanently broken while looking
  // complete in source.

  // ProviderDriftSnapshot REMOVED 2026-09-24. No table, and no writer: the Plivo
  // drift check in .github/workflows/plivo-drift.yml compares state and reports,
  // it does not persist snapshots. backend.ts carried a TTL entry for it, which
  // the `if ( table )` guard silently turned into a no-op. This was the deferred
  // item 9.2 in .kiro/work/phases-5-10/plan.md; the retired-provider surface it
  // was waiting for is being swept now, so it goes with the rest.
  // Table: FlowLog — Audit trail for every flow screen interaction
  FlowLog: a
    .model( {
      logId: a.id().required(),
      flowId: a.string(),
      flowCode: a.string(),
      flowToken: a.string(),
      phone: a.string(),
      action: a.string(), // INIT, data_exchange, navigate, complete, ping
      screen: a.string(),
      dataSnapshot: a.string(), // JSON of data exchanged
      requestId: a.string(), // Lambda request ID
      isError: a.boolean().default( false ),
      errorType: a.string(),
      errorMessage: a.string(),
      createdAt: a.integer(),
      ttl: a.integer(), // TTL: 90 days
    } )
    .identifier( [ 'logId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'phone' ),
      index( 'flowId' ),
      index( 'flowCode' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // ═══════════════════════════════════════════════════════════════════════
  // CRM — Lead, Pipeline, Stage, Opportunity, Activity.
  //
  // Added in Phase 4. Before this the live account held 70 tables and not one CRM
  // entity: FlowSubmission, AdClickAttribution, SubmitRequest, Order and
  // ConversationMeta each carried a fragment of the funnel, and none could be
  // joined into "who is in the pipeline, at what stage, worth how much".
  //
  // Provisioned by `scripts/provision_crm_domain.py`, whose index map is pinned to
  // the one the tests model — see TestProvisioningMatchesWhatTheCodeQueries. The
  // declarations below match the deployed key schemas exactly. CRM-KEY-001 is what
  // happens when they do not: this file claimed `contactId` was the Contact key for
  // as long as the live table had been using `id`.
  //
  // No model here carries a TTL. These rows are the business record — which enquiry
  // came from which campaign and what it was worth — and it cannot be rebuilt from
  // MessagesTable, which expires at 30 days.
  //
  // Domain logic lives in `lambda_utils/crm/`; these models exist so that the
  // declared schema and the deployed tables agree.
  // ═══════════════════════════════════════════════════════════════════════

  // CrmPipeline — configuration. `pipelineId` is derived from the name, so
  // re-provisioning is a no-op rather than a second pipeline that splits the board.
  CrmPipeline: a
    .model( {
      pipelineId: a.id().required(),
      name: a.string().required(),
      description: a.string(),
      // A string, not a boolean: DynamoDB cannot index a boolean, and the
      // alternative is scanning every pipeline on every request.
      isDefault: a.string().required(),
      active: a.boolean().default( true ),
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'pipelineId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'isDefault' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // CrmStage — a column on the board. `displayOrder` is position only;
  // opportunities reference `stageId`, so reordering does not rewrite them.
  CrmStage: a
    .model( {
      stageId: a.id().required(),
      pipelineId: a.string().required(),
      name: a.string().required(),
      // OPEN | WON | LOST. Entering a closed stage implies the outcome, which is how
      // dragging a card to Won wins the deal in one action instead of two.
      kind: a.string().required(),
      displayOrder: a.integer().required(),
      // Forecast weight in whole percent. Deliberately optional: a default 50 would
      // quietly become half the pipeline value in every report.
      probability: a.integer(),
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'stageId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'pipelineId' ).sortKeys( [ 'displayOrder' ] ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // CrmLead — an inbound enquiry. `leadId` is a hash of (source, sourceRef), so a
  // replayed webhook lands on the same row; MANUAL and IMPORT get random ids so a
  // deliberate duplicate stays a duplicate.
  CrmLead: a
    .model( {
      leadId: a.id().required(),
      // The Contact's canonical `id` value. See lambda_utils/contact_key.
      contactId: a.string().required(),
      pipelineId: a.string().required(),
      // NEW | WORKING | NURTURING | QUALIFIED | CONVERTED | DISQUALIFIED | JUNK.
      // JUNK is separate from DISQUALIFIED because they mean different things to a
      // conversion rate: one was never an enquiry at all.
      state: a.string().required(),
      source: a.string().required(),
      // Stored as well as hashed into the id: the hash gives idempotency, the stored
      // value answers "which Flow submission was this?", which a digest cannot.
      sourceRef: a.string(),
      // "{contactId}#{pipelineId}" — the business-duplicate question, answered at
      // read time as policy rather than enforced as a uniqueness constraint.
      contactPipelineKey: a.string().required(),
      phone: a.string(),
      name: a.string(),
      email: a.string(),
      subject: a.string(),
      detail: a.string(),
      ownerId: a.string(),
      channel: a.string(),
      campaign: a.string(),
      // Integer paise, matching FlowSubmission.paymentAmount and Payment. Float
      // currency drifts visibly once a forecast sums a few thousand rows.
      amountPaise: a.integer(),
      metadata: a.json(),
      // Absent until conversion. That absence is the ConditionExpression that makes
      // conversion once-only, so it must never be initialised to a placeholder.
      opportunityId: a.string(),
      convertedAt: a.integer(),
      disqualifiedReason: a.string(),
      // Captured once and never moved: response time is measured from it, and an
      // overwrite would make every slow response look instant.
      firstTouchedAt: a.integer(),
      lastActivityAt: a.integer(),
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'leadId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'contactId' ).sortKeys( [ 'createdAt' ] ),
      index( 'state' ).sortKeys( [ 'createdAt' ] ),
      index( 'contactPipelineKey' ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // CrmOpportunity — a qualified lead with a value, on a board.
  CrmOpportunity: a
    .model( {
      opportunityId: a.id().required(),
      contactId: a.string().required(),
      pipelineId: a.string().required(),
      stageId: a.string().required(),
      title: a.string().required(),
      // OPEN | WON | LOST | ABANDONED. ABANDONED is not LOST: a deal that evaporated
      // does not belong in a win-rate denominator.
      outcome: a.string().required(),
      leadId: a.string(),
      amountPaise: a.integer(),
      currency: a.string().default( 'INR' ),
      ownerId: a.string(),
      source: a.string(),
      expectedCloseAt: a.integer(),
      metadata: a.json(),
      // Separate from createdAt because stage dwell time is what identifies a stuck
      // funnel, and it cannot be derived from row age after the first move.
      stageEnteredAt: a.integer(),
      closedAt: a.integer(),
      closeReason: a.string(),
      lastActivityAt: a.integer(),
      createdAt: a.integer(),
      updatedAt: a.integer(),
    } )
    .identifier( [ 'opportunityId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'contactId' ).sortKeys( [ 'createdAt' ] ),
      index( 'stageId' ).sortKeys( [ 'createdAt' ] ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

  // CrmActivity — the append-only timeline. Three sparse indexes, one per subject.
  CrmActivity: a
    .model( {
      activityId: a.id().required(),
      // NOTE | CALL | MESSAGE | EMAIL | MEETING | TASK | STAGE_CHANGE |
      // STATE_CHANGE | SYSTEM. A closed set: free text becomes forty spellings of
      // "call" within a month and no report can group them.
      kind: a.string().required(),
      contactId: a.string(),
      leadId: a.string(),
      opportunityId: a.string(),
      summary: a.string(),
      body: a.string(),
      actorId: a.string(),
      channel: a.string(),
      // A provider id — wamid, call id, payment id — so a timeline entry traces back
      // to the transport record that caused it.
      reference: a.string(),
      // The last three kinds are system-written. A user-supplied STAGE_CHANGE could
      // claim a transition that never happened, destroying the timeline's value as
      // the audit trail for stage movement.
      isSystem: a.boolean().default( false ),
      dueAt: a.integer(),
      completedAt: a.integer(),
      metadata: a.json(),
      // The sort key of all three timeline indexes.
      at: a.integer().required(),
      createdAt: a.integer(),
    } )
    .identifier( [ 'activityId' ] )
    .secondaryIndexes( ( index ) => [
      index( 'contactId' ).sortKeys( [ 'at' ] ),
      index( 'leadId' ).sortKeys( [ 'at' ] ),
      index( 'opportunityId' ).sortKeys( [ 'at' ] ),
    ] )
    .authorization( ( allow ) => [ allow.authenticated() ] ),

} );

export type Schema = ClientSchema<typeof schema>;

export const data = defineData( {
  schema,
  authorizationModes: {
    defaultAuthorizationMode: 'userPool',
  },
  // DynamoDB billing mode: PAY_PER_REQUEST (on-demand)
} ) as any;
