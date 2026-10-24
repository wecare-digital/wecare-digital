/**
 * Site Language Lambda — WECARE.DIGITAL
 *
 * Deployed separately from Amplify Gen 2, matching the repository's existing
 * Python Lambda deployment model.
 *
 * Lambda: wecare-site-language
 * Runtime: Python 3.12
 * Region: us-east-1
 *
 * API routes served through https://wecare.digital/api:
 *   GET  /site-language/languages  - dynamic Amazon Translate language list
 *   POST /site-language/translate  - cached translation; source defaults to auto
 *   GET  /site-language/voices     - dynamic Amazon Polly voice list
 *   POST /site-language/tts        - short/medium MP3 speech synthesis
 *
 * Required IAM:
 *   translate:ListLanguages
 *   translate:TranslateText
 *   polly:DescribeVoices
 *   polly:SynthesizeSpeech
 *   dynamodb:GetItem
 *   dynamodb:PutItem
 *
 * Cache table:
 *   stack-wecare-digital-SiteLanguageCache
 */
export const siteLanguageLambdaName = 'wecare-site-language';
export const siteLanguageCacheTableName = 'stack-wecare-digital-SiteLanguageCache';
