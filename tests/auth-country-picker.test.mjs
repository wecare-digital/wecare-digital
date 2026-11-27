import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { authCountryPanelGeometry } from '../src/lib/authCountryPanelGeometry.ts';

test('country panel stays inside the usable viewport at desktop, foldable, mobile and keyboard sizes', () => {
  let checked = 0;
  for (const layoutWidth of [160, 280, 390, 768, 1440]) {
    for (const viewportWidth of [layoutWidth, Math.min(layoutWidth, 390)]) {
      for (const viewportHeight of [160, 220, 400, 900]) {
        for (const viewportTop of [0, 40]) for (const rtl of [false, true]) {
          for (const y of [-30, 30, 180, 800, 1100]) {
            const viewportLeft = layoutWidth === viewportWidth ? 0 : 28;
            const layoutHeight = Math.max(900, viewportTop + viewportHeight);
            const anchor = {left: layoutWidth - 95, right: layoutWidth - 5, top: y, bottom: y + 54};
            const a = authCountryPanelGeometry({layoutWidth,layoutHeight,viewportLeft,viewportTop,viewportWidth,viewportHeight,anchor,rtl});
            const top = a.top ?? layoutHeight - a.bottom - a.maxHeight;
            assert.ok(a.left >= viewportLeft);
            assert.ok(a.left + a.width <= viewportLeft + viewportWidth + 0.1);
            assert.ok(top >= viewportTop - 0.1);
            assert.ok(top + a.maxHeight <= viewportTop + viewportHeight + 0.1);
            assert.ok(a.width > 0 && a.maxHeight > 0);
            checked++;
          }
        }
      }
    }
  }
  assert.equal(checked, 800);
});

test('desktop panel opens below or above the trigger according to available room', () => {
  const input = {layoutWidth:1440,layoutHeight:900,viewportLeft:0,viewportTop:0,viewportWidth:1440,viewportHeight:900,rtl:false};
  const below = authCountryPanelGeometry({...input,anchor:{left:500,right:590,top:200,bottom:254}});
  assert.equal(below.top,262);
  const above = authCountryPanelGeometry({...input,anchor:{left:500,right:590,top:790,bottom:844}});
  assert.equal(above.bottom,118);
});

test('Auth picker retains restrained hover, selection and keyboard paths without changing sign-in', () => {
  const auth = readFileSync(new URL('../src/pages/auth.tsx', import.meta.url), 'utf8');
  const theme = readFileSync(new URL('../src/styles/public-button-theme.css', import.meta.url), 'utf8');
  for (const marker of ['.country-picker{--public-hover-radius:6px;', 'border-radius:8px;background:var(--public-bg)', ".country-row:not([aria-selected='true']):hover", "border-inline-start-color:var(--public-brand-green)", 'viewport?.addEventListener( \'resize\', place )', 'onKeyDown={ onCountryKeyDown }', 'tabIndex={ -1 }', "event.key === 'Escape'", "event.key === 'Enter'", 'phoneRef.current?.focus( { preventScroll: true } )', 'setCountryQuery( \'\' )', 'aria-controls={ countryOpen ?', 'void submitStep( { country: dialCode, phone: national } )']) assert.ok(auth.includes(marker), marker);
  assert.ok(theme.includes('.country-search .public-search-clear'));
  assert.doesNotMatch(auth, /autoFocus\s+type="search"/);
});
