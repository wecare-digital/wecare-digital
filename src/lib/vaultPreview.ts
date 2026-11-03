/** Older supported WebKit uses its native PDF engine instead of importing an unsupported parser. */
export function nativeVaultPdfRequired(userAgent:string,hasPromiseResolvers:boolean):boolean{
 const ios=/(?:CPU (?:iPhone )?OS|iPhone OS) (\d+)[_.]/.exec(userAgent);
 const safari=/Version\/(\d+)/.exec(userAgent);
 const webkit=/AppleWebKit/.test(userAgent)&&!/(?:Chrome|Chromium|Edg|OPR)\//.test(userAgent);
 return !!(ios&&Number(ios[1])<18)||!!(webkit&&(!hasPromiseResolvers||safari&&Number(safari[1])<18));
}

/** A native iframe receives verified PDF bytes, never a remote 403/error document. */
export async function loadNativeVaultPdf(src:string,signal:AbortSignal):Promise<Blob>{
 const response=await fetch(src,{signal,cache:'no-store'});
 if(!response.ok)throw new Error('Private PDF request failed');
 const type=(response.headers.get('content-type')||'application/octet-stream').split(';')[0].trim().toLowerCase();
 if(!['application/pdf','application/octet-stream'].includes(type))throw new Error('Private response is not a PDF');
 const file=await response.blob();
 if(!file.size||file.size>100*1024*1024||!(await file.slice(0,1024).text()).includes('%PDF-'))throw new Error('Private PDF bytes are invalid');
 return new Blob([file],{type:'application/pdf'});
}
