import test from 'node:test';
import assert from 'node:assert/strict';
import { safeLocalReturnPath } from '../src/lib/safeReturnPath.ts';

test('the shared WhatsApp auth returns to the exact appointment page, without opening a path prefix', () => {
  assert.equal(safeLocalReturnPath('/elsewhere/arogya-yatra/'), '/elsewhere/arogya-yatra/');
  assert.equal(safeLocalReturnPath('/elsewhere/arogya-yatra'), '/elsewhere/arogya-yatra/');
  for (const destination of ['/elsewhere/', '/elsewhere/other/', '//example.com/', '/elsewhere/arogya-yatra/?next=evil', '/elsewhere/../workspace/', '/elsewhere%2Farogya-yatra/']) {
    assert.equal(safeLocalReturnPath(destination), '/');
  }
});
