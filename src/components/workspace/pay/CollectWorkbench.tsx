import React from 'react';
import CollectCreate,{type CollectPreview} from './CollectCreate';
import CollectLog from './CollectLog';
import CollectControl from './CollectControl';
export default function CollectWorkbench(){
  const [tab,setTab]=React.useState<'Create'|'Control'|'Log'>('Create'),[revision,setRevision]=React.useState(0);
  const [draft,setDraft]=React.useState<CollectPreview|null>(null),[saved,setSaved]=React.useState<CollectPreview|null>(null);
  const onCreated=React.useCallback(()=>setRevision(n=>n+1),[]),onDraft=React.useCallback((p:CollectPreview|null)=>setDraft(p),[]),onSaved=React.useCallback((p:CollectPreview|null)=>setSaved(p),[]);
  const preview=tab==='Log'?saved:draft;
  return <main className="collect"><header><p>WORKSPACE</p><h1>Collect</h1><p>Raise a custom invoice, review its actual image and track the payment and receipt.</p></header>
    <nav aria-label="Collect tabs">{(['Create','Control','Log'] as const).map(name=><button key={name} aria-current={tab===name?'page':undefined} onClick={()=>setTab(name)}>{name}</button>)}</nav>
    <div className="workbench"><div className="main"><div hidden={tab!=='Create'}><CollectCreate onPreview={onDraft} onCreated={onCreated}/></div>{tab==='Control'&&<CollectControl/>}{tab==='Log'&&<CollectLog revision={revision} onPreview={onSaved}/>}</div>
      <aside aria-label="Actual invoice preview"><h2>Invoice preview</h2>{preview?<><p>{preview.label}</p><img src={preview.src} alt={preview.label}/></>:<p>{tab==='Log'?'Choose a saved invoice to view its actual image.':'Select a customer and complete the custom invoice to load the server-rendered image.'}</p>}</aside></div>
    <style jsx>{`.collect{padding:24px 0 48px;color:var(--text-primary)}header p{font-size:12px;color:var(--text-muted);line-height:1.7}header p:first-child{font-size:10px;letter-spacing:.15em;font-weight:700}h1{font-size:30px;margin:8px 0}nav{display:flex;gap:8px;border-bottom:1px solid var(--border);padding:12px 0;margin-bottom:22px}nav button{border:0;background:transparent;color:var(--text-muted);padding:12px 20px;border-radius:8px;font:inherit;font-size:13px;cursor:pointer}nav button[aria-current]{background:var(--bg-secondary);color:var(--text-primary);font-weight:700}.workbench{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(280px,.8fr);gap:24px;align-items:start}.main{min-width:0}aside{position:sticky;top:100px;border:1px solid var(--border);border-radius:12px;padding:16px;min-width:0}aside h2{font-size:15px;margin:0}aside p{font-size:11px;color:var(--text-muted);line-height:1.7}aside img{display:block;width:100%;height:auto}button:focus-visible{outline:3px solid var(--accent);outline-offset:2px}@media(max-width:950px){.workbench{grid-template-columns:1fr}aside{position:static}}`}</style>
  </main>;
}
