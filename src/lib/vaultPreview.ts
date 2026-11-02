/** Older supported WebKit uses its native PDF engine instead of importing an unsupported parser. */
export function nativeVaultPdfRequired(userAgent:string,hasPromiseResolvers:boolean):boolean{
 const ios=/(?:CPU (?:iPhone )?OS|iPhone OS) (\d+)[_.]/.exec(userAgent);
 const safari=/Version\/(\d+)/.exec(userAgent);
 const webkit=/AppleWebKit/.test(userAgent)&&!/(?:Chrome|Chromium|Edg|OPR)\//.test(userAgent);
 return !hasPromiseResolvers||!!(ios&&Number(ios[1])<18)||!!(webkit&&safari&&Number(safari[1])<18);
}
