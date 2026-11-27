/**
 * Start before navigation: a finite introductory sequence can finish before
 * slow fonts or a load event. Record the actual active words, not a simulated
 * timer. No mutation of the site or its payment/customer state.
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

export async function verifyHeroIntro(page, words, reduced) {
  const issues = [];
  if (await page.locator('.rp-control').count()) issues.push('Unexpected headline rotation control');
  if (!words.length) return {issues: [...issues, 'Missing rotating words'], trace: []};
  if (!reduced && words.length > 1) {
    // The first state may be static HTML, before hydration. Start the stop
    // observation from the first actual change, not the navigation timestamp.
    await page.waitForFunction(() => window.__wcHeroTrace?.length >= 2, undefined, {timeout: 12000})
      .catch(() => issues.push('Headline introduction did not start'));
    await page.waitForFunction(() => {
      const trace = window.__wcHeroTrace;
      return trace?.length > 1 && performance.now() - trace[1].time >= 5500;
    }, undefined, {timeout: 8000}).catch(() => issues.push('Headline introduction observation incomplete'));
  } else {
    await page.waitForTimeout(5000);
  }
  const trace = await page.evaluate(() => window.__wcHeroTrace || []);
  if (reduced || words.length === 1) {
    if (trace.some(entry => entry.word !== words[0])) issues.push('Rotation ignores reduced motion or static word');
  } else {
    if (new Set(trace.map(entry => entry.word)).size !== words.length) issues.push('Incomplete hero introduction');
    if (trace.length !== words.length + 1 || trace.at(-1)?.word !== words[0]
      || trace.at(-1)?.time - trace[1]?.time > 4400) issues.push('Headline rotation did not stop after one introduction');
  }
  return {issues, trace};
}
