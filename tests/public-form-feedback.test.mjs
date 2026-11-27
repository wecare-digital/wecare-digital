import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { voiceSearchFailureMessage } from '../src/lib/publicVoiceSearch.ts';
const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');

test('recognition errors provide a safe, actionable text-search fallback', () => {
  for (const code of ['not-allowed','service-not-allowed','NotAllowedError','SecurityError','audio-capture','NotFoundError','NotReadableError','no-speech','nomatch','network','language-not-supported','unknown',undefined]) {
    const message = voiceSearchFailureMessage(code);
    assert.match(message, /type your search/i);
    assert.ok(message.length < 160);
  }
  assert.match(voiceSearchFailureMessage('not-allowed'), /permissions/i);
  assert.match(voiceSearchFailureMessage('audio-capture'), /microphone/i);
  assert.match(voiceSearchFailureMessage('no-speech'), /no speech/i);
  assert.match(voiceSearchFailureMessage('network'), /connect/i);
  assert.doesNotMatch(voiceSearchFailureMessage('arbitrary provider message'), /arbitrary provider message/);
});

test('voice search keeps the existing accessible control and avoids multiple pending starts', () => {
  const source = read('src/components/VoiceSearchMic.tsx');
  for (const token of ['activeRef.current = true', 'if ( activeRef.current )', 'cancelledRef.current = true', 'recognition.abort()', 'voiceSearchFailureMessage( event.error )', 'aria-live="polite"', 'role="status"', 'aria-describedby={ feedback ? statusId : undefined }']) {
    assert.ok(source.includes(token), token);
  }
  assert.ok(source.includes('transcriptHandlerRef.current( transcript )'));
  assert.ok(source.includes('if ( !supported && !showUnsupportedState ) return null'));
});

test('customer forms use visible focus and connect field errors to the existing notices', () => {
  const checkout = read('src/components/CheckoutProfile.tsx');
  const address = read('src/components/AddressFields.tsx');
  const auth = read('src/pages/auth.tsx');
  for (const source of [checkout,address,auth]) assert.ok(source.includes('outline:2px solid var(--public-brand-green)'));
  assert.ok(checkout.includes('aria-busy={ saving }'));
  assert.ok(checkout.includes('errorDescriptionId={ message ? noticeId : undefined }'));
  assert.ok(checkout.includes('reply.status !== \'PROFILE_READY\''));
  assert.ok(address.includes('aria-describedby={ pinBad ? postalHelpId'));
  assert.ok(address.includes('Enter a valid six-digit Indian PIN code.'));
  assert.ok(auth.includes('event.nativeEvent.isComposing'));
  assert.ok(auth.includes("querySelector<HTMLButtonElement>( '.country-trigger' )?.focus"));
  assert.ok(auth.includes('@media(max-width:279px)'));
});
