import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadTsxModule } from './helpers/loadTsx.mjs';

const { exports: { formatEnvironmentSections, isBuildingCandidate } } = loadTsxModule({
  file: 'src/components/VayuLokEnvironmentData.ts',
  globals: { require: name => name.includes('constants') ? { API_BASE: 'https://unit-test.invalid' } : {} },
});

test('new sources retain missing, zero and historical semantics', () => {
  const items = formatEnvironmentSections({sources:{
    elevation:{status:'ok',elevationM:0},
    cpcb:{status:'ok',station:'Test',readings:[{pollutant:'PM2.5',average:0,observedAt:'2026-11-27T14:00:00+05:30'}]},
    pvgis:{status:'disabled'},
    solar:{status:'budget_limited'},
    spartan:{status:'ok',site:'Delhi',pm25UgM3:41.52,endDate:'2024-03-06',method:'filter'},
  }});
  assert.equal(items.length,4);
  assert.equal(items[0].rows[0].value,'0 m');
  assert.ok(items[1].rows.some(x=>x.value==='0 (source unit not specified)'));
  assert.equal(items[2].rows.length,0);
  assert.match(items[2].note,/budget/);
  assert.match(items[3].note,/Historical scientific/);
  assert.ok(items[3].rows.some(x=>x.value==='2024-03-06'));
});

test('only precise positive-area viewports trigger automatic building lookup', () => {
  assert.equal(isBuildingCandidate(undefined),false);
  assert.equal(isBuildingCandidate({north:29,south:28,east:78,west:77}),false);
  assert.equal(isBuildingCandidate({north:28.601,south:28.6,east:77.201,west:77.2}),true);
  assert.equal(isBuildingCandidate({north:28.6,south:28.6,east:77.2,west:77.2}),false);
});

test('source addition preserves the shared hero and original map design', () => {
  const page=readFileSync(new URL('../src/pages/atmos/nano-climate.tsx',import.meta.url),'utf8');
  const live=readFileSync(new URL('../src/components/VayuLokLive.tsx',import.meta.url),'utf8');
  assert.match(page, /badgeLabel="Nano Climate by WECARE.DIGITAL"/);
  assert.match(page, /words=\{ cycleWords \}/);
  assert.match(page, /<VayuLokApprovedGlobe/);
  assert.doesNotMatch(page, /atlasEnabled\s*\?|vl-atlas-page-head/);
  assert.ok(live.includes('padding-inline-start:10px;border-inline-start:3px solid var(--lime)'));
  assert.equal((live.match(/ref=\{ mapHost \}/g)||[]).length,1);
  assert.match(live, /useVayuLokEnvironmentData/);
});
