#!/usr/bin/env node
/** Serve only a fixed static export on TLS loopback, never a backend proxy. */
import {createServer} from 'node:https';
import {readFile,stat,realpath} from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import {resolve,join,extname,sep} from 'node:path';
import assert from 'node:assert/strict';
const root=await realpath(resolve(process.argv[2]||'out'));
const key=await readFile(process.env.PUBLIC_QA_TLS_KEY);
const cert=await readFile(process.env.PUBLIC_QA_TLS_CERT);
const types={'.html':'text/html; charset=utf-8','.js':'application/javascript','.mjs':'application/javascript','.css':'text/css','.json':'application/json','.xml':'application/xml','.txt':'text/plain; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.ico':'image/x-icon','.woff':'font/woff','.woff2':'font/woff2'};
const origin='https://127.0.0.1:4173';
const server=createServer({key,cert},async(req,res)=>{
  res.setHeader('Cache-Control','no-store');
  res.setHeader('X-Content-Type-Options','nosniff');
  try{
    if(req.headers.host!=='127.0.0.1:4173'||!['GET','HEAD'].includes(req.method)){res.writeHead(405);return res.end();}
    const url=new URL(req.url,origin);
    if(url.origin!==origin){res.writeHead(400);return res.end();}
    if(url.pathname==='/qa-fixture/invoice'&&url.search==='?X-Amz-Signature=synthetic-only'){
      res.writeHead(200,{'Content-Type':'application/octet-stream','Content-Disposition':'attachment; filename="synthetic-checkout-fixture.txt"'});
      return res.end(req.method==='HEAD'?'':'SYNTHETIC CHECKOUT QA ONLY - NOT AN INVOICE');
    }
    const name=decodeURIComponent(url.pathname);
    if(name.includes('\0')||name.includes('\\')||name.split('/').some(p=>p==='..'||p==='.')||name.startsWith('/api/')){res.writeHead(404);return res.end();}
    const path=resolve(root,'.'+name);
    assert.ok(path===root||path.startsWith(root+sep));
    let candidate=path;
    if((await stat(candidate)).isDirectory()) candidate=join(candidate,'index.html');
    const file=await realpath(candidate);
    assert.ok(file.startsWith(root+sep));
    const info=await stat(file);
    if(!info.isFile()){res.writeHead(404);return res.end();}
    res.writeHead(200,{'Content-Type':types[extname(file).toLowerCase()]||'application/octet-stream','Content-Length':info.size});
    if(req.method==='HEAD') return res.end();
    createReadStream(file).on('error',()=>res.destroy()).pipe(res);
  }catch{if(!res.headersSent)res.writeHead(404);res.end();}
});
server.listen(4173,'127.0.0.1',()=>console.log('Immutable QA export listening on '+origin));
