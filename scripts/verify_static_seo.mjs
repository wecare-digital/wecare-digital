#!/usr/bin/env node
/**
 * Exhaustive SEO check of the local static export. No production crawling,
 * private page access or customer data. Build with the repository's npm build.
 */
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';
const dir=resolve(process.argv[2]||'out');
const xml=await readFile(join(dir,'sitemap.xml'),'utf8');
const urls=[...xml.matchAll(/<loc>\s*([^<]+)\s*<\/loc>/g)].map(m=>m[1].replaceAll('&amp;','&'));
const failures=[];
const origin='https://wecare.digital';
const seen=new Set();
function tags(html,name){return [...html.matchAll(new RegExp('<'+name+'\\b[^>]*>','gi'))].map(m=>m[0]);}
function attr(tag,name){return new RegExp('\\b'+name+'=["\\x27]([^"\\x27]*)["\\x27]','i').exec(tag)?.[1]||'';}
function check(html,url,indexable){
  const errors=[];
  const titles=[...html.matchAll(/<title(?:\s[^>]*)?>([\s\S]*?)<\/title>/gi)];
  const desc=tags(html,'meta').filter(tag=>attr(tag,'name').toLowerCase()==='description');
  const robot=tags(html,'meta').filter(tag=>attr(tag,'name').toLowerCase()==='robots').map(tag=>attr(tag,'content')).join(' ');
  const canon=tags(html,'link').filter(tag=>attr(tag,'rel').toLowerCase()==='canonical');
  if(titles.length!==1||!titles[0][1].trim()) errors.push('title');
  if(indexable&&(desc.length!==1||!attr(desc[0],'content').trim())) errors.push('description');
  if(indexable&&(canon.length!==1||attr(canon[0],'href')!==url)) errors.push('canonical');
  if(indexable===/\b(?:noindex|none)\b/i.test(robot)) errors.push('robots');
  if((html.match(/<h1\b/gi)||[]).length!==1) errors.push('h1');
  for(const m of html.matchAll(/<script\b[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)){
    try{JSON.parse(m[1]);}catch{errors.push('JSON-LD');}
  }
  if(errors.length) failures.push({url,errors});
}
for(const url of urls){
  const parsed=new URL(url);
  assert.equal(parsed.origin,origin);
  assert.ok(!parsed.search&&!parsed.hash&&!parsed.pathname.includes('..'));
  if(seen.has(url)) failures.push({url,errors:['duplicate sitemap URL']});
  seen.add(url);
  try{check(await readFile(join(dir,parsed.pathname.replace(/^\/+/,'').replace(/\/?$/,'/'),'index.html'),'utf8'),url,true);}
  catch(e){failures.push({url,errors:['missing export']});}
}
for(const path of ['/auth/','/checkout/','/checkout/status/','/checkout/success/']){
  try{check(await readFile(join(dir,path.slice(1),'index.html'),'utf8'),origin+path,false);}
  catch{failures.push({url:origin+path,errors:['missing protected export']});}
}
const report={sitemapUrls:urls.length,unique:seen.size,failures};
assert.ok(urls.length>0);
await writeFile(process.env.PUBLIC_SEO_REPORT||'/tmp/wecare-seo-report.json',JSON.stringify(report,null,2));
console.log('Static SEO acceptance: '+JSON.stringify({sitemapUrls:urls.length,unique:seen.size,failures:failures.length,examples:failures.slice(0,10)}));
assert.equal(failures.length,0);
