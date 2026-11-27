/**
 * Record real active words from before navigation. The continuous rotation
 * must cross the first complete cycle and remain user-controllable.
 */
export async function installHeroTrace(page) {
  await page.addInitScript(() => {
    const trace = [];
    Object.defineProperty(window, '__wcHeroTrace', {value: trace});
    const record = () => {
      const mark = document.querySelector('h1.home-head .rp-mark, h1.rh-head .rp-mark, .rh-decoration .rp-mark');
      const active = mark?.querySelector('.rp-cyc-word.on');
      if (!active) return;
      const word = active.textContent.trim();
      if (trace.at(-1)?.word !== word) trace.push({word, time: performance.now()});
    };
    new MutationObserver(record).observe(document, {subtree: true, childList: true, attributes: true, attributeFilter: ['class']});
    record();
  });
}

export async function verifyHeroRotation(page, words, reduced) {
  const issues = [];
  if (await page.locator('.rp-control').count()) issues.push('Unexpected separate headline rotation control');
  if (!words.length) return {issues: [...issues, 'Missing rotating words'], trace: []};
  const toggle = page.locator('.rp-toggle');
  if (reduced || words.length === 1) {
    if (await toggle.isVisible()) issues.push('Unexpected rotation control in static mode');
    await page.waitForTimeout(5000);
    const trace = await page.evaluate(() => window.__wcHeroTrace || []);
    if (!trace.length || trace.some(entry => entry.word !== words[0])) issues.push('Rotation ignores reduced motion or static word');
    return {issues, trace};
  }
  // Observe the first word again AND the following word. A one-shot
  // introduction that stops at the first word is not continuous rotation.
  try {
    await page.waitForFunction(count => window.__wcHeroTrace?.length >= count + 2, words.length,
      {timeout: Math.max(15000, (words.length + 2) * 3000 + 5000)});
  } catch { issues.push('Headline rotation did not continue beyond one cycle'); }
  const trace = await page.evaluate(() => window.__wcHeroTrace || []);
  if (trace.length < words.length + 2 || trace.some((entry, index) => entry.word !== words[index % words.length])) {
    issues.push('Incomplete or out-of-order continuous headline rotation');
  }
  if (await toggle.count() !== 1 || !await toggle.isVisible()) {
    issues.push('Missing interactive headline pill');
    return {issues, trace};
  }
  try {
    // A keyboard activation pauses the same existing visual pill. Moving focus
    // away must not restart it. Resume with a second activation.
    await toggle.press('Space');
    if (await toggle.getAttribute('aria-pressed') !== 'true') issues.push('Headline pause did not activate');
    await toggle.evaluate(el => el.blur());
    const stoppedAt = await page.evaluate(() => window.__wcHeroTrace.length);
    await page.waitForTimeout(2800);
    if (await page.evaluate(() => window.__wcHeroTrace.length) !== stoppedAt) issues.push('Headline continues when explicitly paused');
    await toggle.press('Space');
    if (await toggle.getAttribute('aria-pressed') !== 'false') issues.push('Headline resume did not activate');
    await page.waitForFunction(count => window.__wcHeroTrace.length > count, stoppedAt, {timeout: 6000});
    // Freeze only this test's browser before settled geometry and contrast
    // measurements. The actual default site remains continuously rotating.
    await toggle.press('Space');
    await toggle.evaluate(el => el.blur());
    await page.waitForTimeout(600);
  } catch { issues.push('Headline pause/resume keyboard interaction failed'); }
  return {issues, trace};
}
