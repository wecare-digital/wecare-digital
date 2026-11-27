import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { isPaid, isRetryable, isInFlight, amountLabel } from '../src/lib/paymentVocabulary.ts';
const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');

test('continuous hero clock is cancellable and the pill itself toggles motion', () => {
  const source = read('src/components/RotatingPill.tsx');
  assert.ok(source.includes('window.setInterval( tick, delay )'));
  assert.ok(source.includes('window.clearInterval( timer )'));
  assert.ok(source.includes('if ( paused || words.length <= 1 )'));
  assert.ok(source.includes('clock.stop()'));
  assert.ok(source.includes('aria-pressed={ paused }'));
  assert.doesNotMatch(source, /HeroRotationControl|rp-control/);
});
test('language disclosure contains visible label and controls only its mounted panel', () => {
  const source = read('src/components/SupportWidget.tsx');
  assert.ok(source.includes('${chipLabel} — Language:'));
  assert.ok(source.includes("aria-controls={ open ? 'wc-lang-panel' : undefined }"));
});
test('inactive editorial pages suppress every nested focus target', () => {
  const source = read('src/components/ProductBlogPanel.tsx');
  assert.ok(source.includes('inert={ pageIndex !== activePage }'));
  assert.ok(source.includes('className="pbp-tagrow" tabIndex={ pageIndex === activePage ? undefined : -1 }'));
  assert.ok(read('src/components/BlogTags.tsx').includes('tabIndex={ tabIndex }'));
});
test('public contribution is refused before initiating the native payment rail', () => {
  const source = read('amplify/functions/ecommerce/checkout/handler.py');
  const arm = source.slice(source.indexOf('if action == "create":'), source.indexOf('# Unknown operations must never fall through'));
  assert.ok(arm.includes('_website_contribution_requires_web_rail(body.get("lineItems"))'));
  assert.ok(arm.indexOf('CONTRIBUTION_WEBSITE_ONLY') < arm.indexOf('return _create(identity, body, origin)'));
  assert.ok(source.includes('return _staff_contribution_send('));
});
test('payment status recovery never authorizes another attempt while unresolved', () => {
  for (const s of ['CREATED','PAYMENT_PENDING','PAYMENT_REQUEST_SENT','PAYMENT_READINESS_CHECKED']) {
    assert.equal(isInFlight(s), true);
    assert.equal(isPaid(s), false);
    assert.equal(isRetryable(s), false);
  }
  for (const s of ['PAYMENT_FAILED','PAYMENT_CANCELLED','PAYMENT_EXPIRED']) {
    assert.equal(isPaid(s), false);
    assert.equal(isRetryable(s), true);
  }
  assert.equal(isPaid('PAYMENT_PAID'), true);
  assert.equal(isPaid('unknown'), false);
  assert.equal(amountLabel(30000,'INR'), '₹300.00');
  const status = read('src/pages/checkout/status.tsx');
  assert.ok(status.includes('onClick={ () => window.location.reload() }>Check payment status</button>'));
  assert.ok(status.includes('if ( isPaid( attempt.status ) ) settlePaidCheckout( attemptId );'));
  const cart = read('src/components/cart/CartPage.tsx');
  assert.ok(cart.includes("String( verdict.status || '' ).toUpperCase() === 'VERIFIED_PAID'"));
  assert.ok(cart.includes('options.amountPaise !== expectedTotalPaise'));
  assert.ok(cart.includes('goToCheckoutStatus( attemptId, reviewedBasket );'));
});
test('anonymous acceptance retains axe selectors and verifies continuous motion and user control', () => {
  const audit = read('scripts/audit_public_acceptance.mjs');
  assert.ok(audit.includes('targets: v.nodes.slice(0, 30).map(n => n.target)'));
  assert.ok(audit.includes('verifyHeroRotation'));
  const runner = read('scripts/public_hero_audit.mjs');
  assert.ok(runner.includes('Headline rotation did not continue beyond one cycle'));
  assert.ok(runner.includes('Headline continues when explicitly paused'));
});
