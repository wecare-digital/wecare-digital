"""Read-only public blog API over the native AWS store."""
import hashlib
import json
import re
import logging
import storage
import faq

log=logging.getLogger(__name__)
FIELDS={'slug','title','excerpt','category','publishedDate','modifiedDate','authorName',
        'coverImage','url','tags','seoTitle','metaDescription','focusKeyword','keywords',
        'hashtags','robots','jsonLd','id'}
DETAIL_FIELDS=FIELDS | {'content','richContent'}
CACHE='public, max-age=60, s-maxage=300, stale-while-revalidate=600'

def public_view(post, detail=False):
    return {k:v for k,v in post.items() if k in (DETAIL_FIELDS if detail else FIELDS)}

def integrity():
    posts=storage.list_blog_posts(published_only=True,include_content=True)
    hashes={p['slug']:hashlib.sha256(json.dumps(public_view(p,True),sort_keys=True,
                ensure_ascii=False,separators=(',',':')).encode()).hexdigest() for p in posts}
    digest=hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'count':len(posts),'hashes':hashes,'aggregateSha256':digest}

def response(status,body,event):
    origin=(event.get('headers') or {}).get('origin','')
    headers={'Content-Type':'application/json','Vary':'Origin, Accept-Encoding','X-Blog-Source':'native-aws'}
    if origin in ('https://wecare.digital','https://www.wecare.digital'):
        headers['Access-Control-Allow-Origin']=origin
    payload=json.dumps(body,ensure_ascii=False,separators=(',',':'))
    if status==200:
        etag='"'+hashlib.sha256(payload.encode()).hexdigest()[:32]+'"'
        headers.update({'ETag':etag,'Cache-Control':CACHE})
        request_headers={str(k).lower():str(v) for k,v in (event.get('headers') or {}).items()}
        if etag in request_headers.get('if-none-match','').split(','):
            return {'statusCode':304,'headers':headers,'body':''}
    return {'statusCode':status,'headers':headers,'body':payload}

def handler(event,context):
    # Direct Lambda invocation requires IAM; HTTP bodies cannot set this marker.
    if event.get('integrityAudit') is True and 'requestContext' not in event:
        return integrity()
    http=(event.get('requestContext') or {}).get('http') or {}
    method=http.get('method') or event.get('httpMethod','GET')
    path=(event.get('rawPath') or http.get('path') or event.get('path','')).rstrip('/')
    if method!='GET':
        return response(405,{'ok':False,'error':'Read-only API'},event)
    stage=str((event.get('requestContext') or {}).get('stage') or '')
    if stage and stage!='$default' and path.startswith('/'+stage+'/'):
        path=path[len(stage)+1:]
    base='/seo-tools/blog-public'
    if path.startswith('/api/'):
        path=path[4:]
    if path!=base and not path.startswith(base+'/'):
        return response(404,{'ok':False,'error':'Unknown route'},event)
    try:
        if path==base:
            posts=[public_view(p) for p in storage.list_blog_posts(published_only=True,include_content=False)]
            wanted={p.strip() for p in str((event.get('queryStringParameters') or {}).get('fields','')).split(',')} & FIELDS
            if wanted:
                wanted.add('slug')
                posts=[{k:v for k,v in p.items() if k in wanted} for p in posts]
            return response(200,{'ok':True,'posts':posts,'total':len(posts)},event)
        slug=path[len(base)+1:]
        if not re.fullmatch('[a-z0-9-]{1,240}',slug):
            return response(404,{'ok':False,'error':'Blog post not found'},event)
        post=storage.get_blog_post(slug,published_only=True)
        if not post:
            return response(404,{'ok':False,'error':'Blog post not found'},event)
        try:
            post=faq.attach(post,storage.list_slug_records(slug))
        except Exception:
            log.warning('Approved FAQ lookup unavailable')
        return response(200,{'ok':True,'post':public_view(post,True)},event)
    except Exception:
        log.exception('Native public blog read failed')
        return response(503,{'ok':False,'error':'The blog is temporarily unavailable'},event)
