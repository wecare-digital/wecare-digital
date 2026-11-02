import React from 'react';
import * as api from '../../../api/client';

const object=(value:unknown):Record<string,any>=>value&&typeof value==='object'?value as Record<string,any>:{};
export default function ProcessTemplatePreview({templateId}:{templateId:string}) {
  const [template,setTemplate]=React.useState<Awaited<ReturnType<typeof api.getTemplateDetails>>>(null);
  const [message,setMessage]=React.useState('Checking live template…');
  React.useEffect(()=>{let active=true;setTemplate(null);setMessage('Checking live template…');void api.getTemplateDetailsResult(templateId).then(result=>{if(!active)return;if(!result.ok){setMessage(result.failure.message);return;}setTemplate(result.data);setMessage(result.data.status);}).catch(()=>{if(active)setMessage('Template lookup failed. Reload the process to retry.');});return()=>{active=false;};},[templateId]);
  const parts=(template?.components||[]).map(object);
  const header=parts.find(part=>part.type==='HEADER');
  const body=parts.find(part=>part.type==='BODY');
  const footer=parts.find(part=>part.type==='FOOTER');
  const candidate=header?.example?.header_handle?.[0];
  const image=header?.format==='IMAGE'&&typeof candidate==='string'&&candidate.startsWith('https://')?candidate:'';
  const buttons=parts.filter(part=>part.type==='BUTTONS').flatMap(part=>Array.isArray(part.buttons)?part.buttons:[]).map(object);
  return <div className="process-template"><strong>Live WhatsApp preview · {message}</strong>{template&&<>
    {header?.text&&<p>{String(header.text)}</p>}{image&&<><img src={image} alt="Approved WhatsApp template header"/><a href={image} target="_blank" rel="noopener noreferrer">Full header image URL</a></>}
    {body?.text&&<p className="body">{String(body.text)}</p>}{footer?.text&&<small>{String(footer.text)}</small>}
    {buttons.map((button,index)=><div className="button" key={index}><strong>{String(button.text||button.type)}</strong><small>{String(button.type)}{button.flow_id?` · Flow ID ${String(button.flow_id)}`:''}</small>{button.url&&<span>{String(button.url)}</span>}</div>)}
    <small>Variables such as {'{{1}}'} remain visible until the item&apos;s process supplies verified values. Previewing does not send.</small>
  </>}
    <style jsx>{`.process-template{display:grid;gap:12px;border:1px solid var(--border);background:var(--bg-secondary);border-radius:12px;padding:16px;font-size:13px}.process-template img{max-width:100%;max-height:180px;object-fit:contain;justify-self:start}.process-template a{color:var(--text-primary);overflow-wrap:anywhere}.body{white-space:pre-wrap;line-height:1.6;margin:0}small{display:block;color:var(--text-muted);font-size:11px;line-height:1.6}.button{display:grid;gap:4px;border-top:1px solid var(--border);padding-top:10px}.button span{overflow-wrap:anywhere;font-size:12px}`}</style>
  </div>;
}
