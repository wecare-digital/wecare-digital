// DOM-level artifact checks; does not launch/control a browser or call a network.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM,VirtualConsole}=require(process.env.AUDIT_JSDOM_PATH?path.resolve(process.env.AUDIT_JSDOM_PATH):'jsdom');
const errors=[];
function load(file){const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));const dom=new JSDOM(fs.readFileSync(file,'utf8'),{runScripts:'dangerously',virtualConsole:vc});dom.window.fetch=()=>{throw Error('Network prohibited in review artifact');};return dom;}
const report=load('docs/workspace-review/workspace-audit-report.html'),r=report.window.document;
assert.equal(r.querySelectorAll('#pages tr').length,149);
assert.equal(r.querySelectorAll('#functions tr').length,74);
r.querySelector('#scope').value='workspace';r.querySelector('#scope').dispatchEvent(new report.window.Event('change'));
assert.equal(r.querySelectorAll('#pages tr').length,113);
r.querySelector('#search').value='Configuration-blocked';r.querySelector('#search').dispatchEvent(new report.window.Event('input'));
assert.equal(r.querySelectorAll('#pages tr').length,8);
r.querySelector('#clear').click();assert.equal(r.querySelectorAll('#pages tr').length,149);
r.querySelector('#backendSearch').value='wecare-workspace-mcp';r.querySelector('#backendSearch').dispatchEvent(new report.window.Event('input'));
assert.equal(r.querySelectorAll('#functions tr').length,1);
const design=load('docs/workspace-review/workspace-redesign-prototype.html'),d=design.window.document;
assert.equal(d.querySelectorAll('#queue tbody tr').length,5);
const clickText=(selector,text)=>{const n=[...d.querySelectorAll(selector)].find(n=>n.textContent.includes(text));assert(n,'Missing control '+text);n.click();};
clickText('.filter','Unassigned');assert.equal(d.querySelectorAll('#queue tbody tr').length,2);
d.querySelector('.search').value='Document';d.querySelector('.search').dispatchEvent(new design.window.Event('input'));assert.equal(d.querySelectorAll('#queue tbody tr').length,1);
d.querySelector('#queue .open').click();assert.equal(d.querySelector('#drawer').classList.contains('hidden'),false);assert(d.querySelector('#detail').textContent.includes('FL-EXAMPLE-1045'));
d.querySelector('#close').click();assert(d.querySelector('#drawer').classList.contains('hidden'));
clickText('#navigation .nav','Inbox');assert.equal(d.querySelector('.tabs .active').textContent,'All channels');clickText('.tab','WhatsApp');assert.equal(d.querySelector('.tabs .active').textContent,'WhatsApp');
clickText('.bottom .nav','Settings');assert.equal(d.querySelectorAll('.settings-grid .card').length,5);
d.querySelector('#role').value='Admin';d.querySelector('#role').dispatchEvent(new design.window.Event('change'));assert.equal(d.querySelectorAll('.settings-grid .card').length,6);assert([...d.querySelectorAll('#navigation .nav')].some(x=>x.textContent.includes('Content')));
d.querySelector('#role').value='Viewer';d.querySelector('#role').dispatchEvent(new design.window.Event('change'));assert(d.querySelector('#primary').classList.contains('hidden'));assert(![...d.querySelectorAll('#navigation .nav')].some(x=>x.textContent.includes('Content')));
d.querySelector('#jump').click();assert(!d.querySelector('#command').classList.contains('hidden'));d.querySelector('#closeCommand').click();assert(d.querySelector('#command').classList.contains('hidden'));
assert.equal(errors.length,0,errors.join('\n'));
report.window.close();design.window.close();console.log('PASS: 149 page rows, 74 backend rows, 113 workspace filter, 8 blocked SEO routes, report reset/search; prototype filtering, detail, channel selection, role previews and command search. No network/browser launched.');
