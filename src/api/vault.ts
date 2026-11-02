import {authFetch, type VaultUploadTicket} from './client';
const BASE=(process.env.NEXT_PUBLIC_API_BASE||'https://wecare.digital/api')+'/secure-files';
export class VaultUploadRefused extends Error {}
/** Upload-init is a mutation. Never retry a response whose outcome is unknown. */
export async function startVaultUpload(input:{name:string;mobile:string;originalFilename:string;contentType:string;sizeBytes:number}):Promise<VaultUploadTicket>{
  const response=await authFetch(BASE+'/upload-init',{method:'POST',body:JSON.stringify(input)});
  const body=await response.json();
  if(!response.ok){const message=body.message||body.error||'Upload registration was not confirmed.';
    if((response.status>=400&&response.status<500&&response.status!==408)||body.error==='VAULT_UPLOAD_NOT_READY')throw new VaultUploadRefused(message);
    throw new Error(message);
  }
  if(!body.fileId||!body.uploadUrl||!body.contentType)throw new Error('Upload registration response was incomplete.');
  return body;
}
