/** Browser error codes only; never relay provider messages or transcript data. */
export function voiceSearchFailureMessage(code?: string): string {
  switch (code) {
    case 'not-allowed':
    case 'service-not-allowed':
    case 'NotAllowedError':
    case 'SecurityError':
      return 'Microphone access is unavailable. Check your permissions or type your search.';
    case 'audio-capture':
    case 'NotFoundError':
    case 'NotReadableError':
      return 'No usable microphone. Connect or enable one, or type your search.';
    case 'no-speech':
    case 'nomatch':
      return 'No speech recognised. Try again or type your search.';
    case 'network':
      return 'Voice search could not connect. Try again or type your search.';
    case 'language-not-supported':
      return 'Voice search is unavailable for this language. Type your search instead.';
    default:
      return 'Voice search could not start or finish. Try again or type your search.';
  }
}
