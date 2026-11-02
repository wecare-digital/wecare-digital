import React from 'react';
import type {PDFDocumentProxy,PDFDocumentLoadingTask,RenderTask} from 'pdfjs-dist';
import {nativeVaultPdfRequired} from '../../../lib/vaultPreview';

/** Render privately in this browser; never forward a document to a viewer service. */
export default function VaultPdfPreview({src,onRendered}:{src:string;onRendered?:()=>void}){
 const canvas=React.useRef<HTMLCanvasElement>(null);
 const [native,setNative]=React.useState(false);
 const [document,setDocument]=React.useState<PDFDocumentProxy|null>(null),[page,setPage]=React.useState(1),[status,setStatus]=React.useState<'loading'|'ready'|'error'>('loading');
 React.useEffect(()=>{let active=true;let loading:PDFDocumentLoadingTask|undefined;setDocument(null);setPage(1);setStatus('loading');
  const nativeViewer=nativeVaultPdfRequired(navigator.userAgent,typeof Promise.withResolvers==='function');setNative(nativeViewer);if(nativeViewer)return;
  void import('pdfjs-dist/legacy/build/pdf.mjs').then(pdf=>{
   if(!active)return;
   const assets='/vendor/pdfjs/'+pdf.version+'/';
   pdf.GlobalWorkerOptions.workerSrc=assets+'pdf.worker.min.mjs';
   loading=pdf.getDocument({url:src,disableRange:true,disableStream:true,enableXfa:false,disableWorkerRendering:true,cMapUrl:assets+'cmaps/',cMapPacked:true,standardFontDataUrl:assets+'standard_fonts/',wasmUrl:assets+'wasm/'});
   return loading.promise.then(value=>{if(active)setDocument(value);});
  }).catch(()=>{if(active)setStatus('error');});
  return()=>{active=false;void loading?.destroy();};
 },[src]);
 React.useEffect(()=>{if(!document||!canvas.current)return;let active=true;let render:RenderTask|undefined;setStatus('loading');const target=canvas.current;target.dataset.rendered='false';
  void document.getPage(page).then(value=>{if(!active)return;const original=value.getViewport({scale:1}),width=Math.max(240,target.parentElement?.clientWidth||420),density=Math.min(window.devicePixelRatio||1,2);const scale=Math.min(width/original.width*density,Math.sqrt(3000000/(original.width*original.height)));const viewport=value.getViewport({scale});target.width=Math.ceil(viewport.width);target.height=Math.ceil(viewport.height);render=value.render({canvas:target,viewport,annotationMode:0});return render.promise.then(()=>{if(active){target.dataset.rendered='true';setStatus('ready');onRendered?.();}});}).catch(()=>{if(active)setStatus('error');});
  return()=>{active=false;render?.cancel();};
 },[document,page,onRendered]);
 if(native)return <div><iframe title="Private PDF preview" src={src} onLoad={()=>{setStatus('ready');onRendered?.();}} onError={()=>setStatus('error')} style={{width:'100%',height:540,border:'1px solid var(--border)'}}/>{status==='error'&&<p role="alert">Native PDF preview failed. Refresh the private link or open the full file.</p>}<p style={{fontSize:11}}>Using this device’s native PDF viewer. Open the full file below for all pages.</p></div>;
 return <div className="pdf-preview" aria-busy={status==='loading'}>{status==='loading'&&<p role="status">Rendering private PDF…</p>}{status==='error'&&<p role="alert">PDF preview could not be rendered. Refresh the private file link or open the full file below.</p>}<canvas ref={canvas} role="img" aria-label={`PDF page ${page}${document?' of '+document.numPages:''}`} style={{display:status==='ready'?'block':'none',width:'100%',height:'auto'}}/>{document&&document.numPages>1&&<div className="pages"><button disabled={page<=1||status==='loading'} onClick={()=>setPage(n=>n-1)}>Previous page</button><span>Page {page} of {document.numPages}</span><button disabled={page>=document.numPages||status==='loading'} onClick={()=>setPage(n=>n+1)}>Next page</button></div>}<style jsx>{`.pdf-preview{min-width:0;border:1px solid var(--border);padding:8px;background:#f7f8f6}.pdf-preview p{font-size:12px;line-height:1.6;color:var(--text-muted)}.pages{display:flex;align-items:center;justify-content:space-between;gap:8px;padding-top:10px;font-size:11px}.pages button{font:inherit;padding:8px;min-height:44px;border:1px solid var(--border);border-radius:7px;background:white;color:var(--text-primary)}.pages button:disabled{opacity:.5}`}</style></div>;
}
