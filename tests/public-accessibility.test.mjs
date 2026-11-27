import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { loadTsxModule, readSource } from './helpers/loadTsx.mjs';

const Link = props => {
  const attributes = { ...props };
  delete attributes.prefetch;
  return React.createElement('a', attributes);
};
const Empty = () => null;
// The offline TSX loader does not apply the styled-jsx transform.
const SourceReact = {
  ...React,
  createElement(type, props, ...children) {
    if (type === 'style' && props?.jsx) {
      props = { ...props };
      delete props.jsx;
    }
    return React.createElement(type, props, ...children);
  },
};
const load = (file, mocks = {}, exportNames = []) => loadTsxModule({
  file,
  exportNames,
  globals: { require: name => name === 'react' ? SourceReact : (mocks[name] ?? Empty) },
}).exports;

const BlogTags = load('src/components/BlogTags.tsx', { 'next/link': Link }).default;
const { default: ProductBlogPanel, preserveTrackFocus } = load('src/components/ProductBlogPanel.tsx', {
  'next/link': Link,
  './BlogTags': BlogTags,
  '../lib/navigationSearch': { rankBlogContent: cards => cards },
  '../lib/publicActionNotices': { publicActionText: () => '' },
}, ['preserveTrackFocus']);

test('only the current perspectives page and its article/tag links are available to keyboard users', () => {
  const cards = Array.from({ length: 6 }, (_, i) => ({
    slug: 'article-' + i, title: 'Article ' + i, category: 'Conversations', tags: ['Accessibility'],
  }));
  const rendered = renderToStaticMarkup(React.createElement(ProductBlogPanel, { cards }));
  const pages = [...rendered.matchAll(/<ul class="pbp-page"([^>]*)>(.*?)<\/ul>/gs)];
  assert.equal(pages.length, 2);
  assert.doesNotMatch(pages[0][1], /\b(?:inert|aria-hidden)=/);
  assert.doesNotMatch(pages[0][2], /tabindex="-1"/i);
  assert.match(pages[1][1], /aria-hidden="true"/);
  assert.match(pages[1][1], /\binert=""/);
  const links = [...pages[1][2].matchAll(/<a\b[^>]*>/g)].map(match => match[0]);
  assert.equal(links.length, 6);
  assert.ok(links.every(markup => /tabindex="-1"/i.test(markup)), 'legacy WebViews also skip the hidden article and tag links');
});

test('page changes preserve focus on the track without stealing it from outside the page', () => {
  const focused = { parentElement: null };
  const calls = [];
  const track = {
    ownerDocument: { activeElement: { closest: () => focused } },
    children: { item: next => next === 0 ? focused : {} },
    focus: options => calls.push(options.preventScroll),
  };
  preserveTrackFocus(track, 1);
  focused.parentElement = track;
  preserveTrackFocus(track, 0);
  assert.deepEqual(calls, []);
  preserveTrackFocus(track, 1);
  assert.deepEqual(calls, [true]);
});

function luminance(hex) {
  const channels = hex.match(/[0-9a-f]{2}/gi).map(n => parseInt(n, 16) / 255);
  return channels.map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
    .reduce((total, v, i) => total + v * [0.2126, 0.7152, 0.0722][i], 0);
}

test('Relay OS scroll entrances preserve color and the Elsewhere key hint meets text contrast', () => {
  const relay = readSource('src/pages/relay-os/index.tsx');
  const animationRules = [...relay.matchAll(/^\s*\.anim[^\n{]*\{([^{}]+)\}/gm)];
  assert.ok(animationRules.length >= 4);
  assert.ok(animationRules.every(rule => !/opacity|transition:\s*all/.test(rule[1])));
  assert.match(relay, /\.anim\.is-armed\{transform:translateY\(30px\);transition:transform /);
  assert.match(relay, /\.anim\.is-armed:focus-within\{transition:none\}/);
  assert.match(relay, /\.anim,\.anim\.is-armed\{transform:none;transition:none\}/);

  const elsewhere = readSource('src/components/ElsewhereTravelAssistant.tsx');
  const tokens = readSource('src/styles/tokens.css');
  assert.match(elsewhere, /\.eta-keyhint\{[^}]*color:var\(--text-muted\)/);
  const muted = /--text-muted:\s*(#[0-9a-f]{6});/i.exec(tokens)[1];
  assert.ok((luminance('#ffffff') + 0.05) / (luminance(muted) + 0.05) >= 4.5);
});

test('shared footer copy stays legible throughout its entrance', () => {
  const footer = readSource('src/components/Footer.tsx');
  assert.match(footer, /\.ft-tagline\.is-armed\{transform:translateY\(14px\)\}/);
  assert.match(footer, /\.ft-tagline\.is-armed\.is-in\{transform:none\}/);
  for (const rule of footer.matchAll(/\.ft-tagline[^\n{]*\{([^{}]*)\}/g)) {
    const css = rule[1].replace(/\/\*[\s\S]*?\*\//g, '');
    assert.doesNotMatch(css, /opacity/);
  }
});
