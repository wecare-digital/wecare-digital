import {authFetch, type VaultUploadTicket} from './client';
const BASE=(process.env.NEXT_PUBLIC_API_BASE||'https://wecare.digital/api')+'/secure-files';
/** Upload-init is a mutation. Never retry a response whose outcome is unknown. */
export async function startVaultUpload(input:{name:string;mobile:string;originalFilename:string;contentType:string;sizeBytes:number}):Promise<VaultUploadTicket>{
  const response=await authFetch(BASE+'/upload-init',{method:'POST',body:JSON.stringify(input)});
  const body=await response.json();
  if(!response.ok)throw new Error(body.message||body.error||'Upload registration was not confirmed.');
  if(!body.fileId||!body.uploadUrl||!body.contentType)throw new Error('Upload registration response was incomplete.');
  return body;
}
