import base64, hashlib, json, os, re, time, urllib.parse, urllib.request
import boto3
REGION='us-east-1'; ISSUER='https://cognito-idp.us-east-1.amazonaws.com/us-east-1_cSx0RHCIR'
POOL='us-east-1_cSx0RHCIR'; SCOPE='aws.cognito.signin.user.admin'
PROTOCOLS={'2025-11-25','2025-06-18','2025-03-26'}

def reply(status,body,extra=None):
    return {'statusCode':status,'headers':{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',**(extra or {})},'body':json.dumps(body,default=str)}

def auth(token):
    p=token.split('.')
    if len(p)!=3: raise ValueError()
    v=json.loads(base64.urlsafe_b64decode(p[1]+'='*(-len(p[1])%4)))
    resource=os.environ['API_BASE']+'/mcp'
    if v.get('iss')!=ISSUER or v.get('client_id')!=os.environ['CHAT_CLIENT_ID'] or v.get('aud')!=resource or v.get('token_use')!='access' or type(v.get('exp')) is not int or v['exp']<=time.time() or SCOPE not in str(v.get('scope','')).split() or not v.get('sub'): raise ValueError()
    c=boto3.client('cognito-idp',region_name=REGION); u=c.get_user(AccessToken=token)
    a={x['Name']:x['Value'] for x in u.get('UserAttributes',[])}
    if a.get('sub')!=v['sub'] or not u.get('Username'): raise ValueError()
    g=c.admin_list_groups_for_user(UserPoolId=POOL,Username=u['Username']).get('Groups',[])
    if 'Admin' not in {x['GroupName'] for x in g}: raise PermissionError()
    return hashlib.sha256((ISSUER+':'+v['sub']).encode()).hexdigest()

def secret():
    raw=boto3.client('secretsmanager',region_name=REGION).get_secret_value(SecretId=os.environ['SECRET_ID'])['SecretString']
    v=json.loads(raw)
    if not isinstance(v,dict): raise ValueError()
    return v

def get(url,headers=None):
    q=urllib.request.Request(url,headers={'Accept':'application/json',**(headers or {})})
    with urllib.request.urlopen(q,timeout=8) as r:
        b=r.read(524289)
        if len(b)>524288: raise ValueError()
        return json.loads(b or b'{}')

def post_form(url,data):
    q=urllib.request.Request(url,data=urllib.parse.urlencode(data).encode(),headers={'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(q,timeout=8) as r:
        b=r.read(524289)
        if len(b)>524288: raise ValueError()
        return json.loads(b or b'{}')

def schema(p,r): return {'type':'object','properties':p,'required':r,'additionalProperties':False}

def tools():
    if os.environ['PROVIDER']=='plivo':
        t=[('connection_verify','Verify the configured Plivo account.',schema({},[])),('get_cdr','Read one Plivo call detail record.',schema({'call_uuid':{'type':'string'}},['call_uuid'])),('get_mdr','Read one Plivo message detail record.',schema({'message_uuid':{'type':'string'}},['message_uuid']))]
    else:
        t=[('connection_verify','Verify the configured Sinch India RCS application.',schema({},[])),('get_application','Read configured Sinch India RCS application metadata.',schema({},[]))]
    sec=[{'type':'oauth2','scopes':[SCOPE]}]
    return [{'name':n,'description':d,'inputSchema':s,'securitySchemes':sec,'_meta':{'securitySchemes':sec}} for n,d,s in t]

def plivo(name,args):
    s=secret(); aid=s.get('auth_id'); tok=s.get('auth_token')
    if not isinstance(aid,str) or not re.fullmatch(r'[A-Za-z0-9]{1,100}',aid) or not isinstance(tok,str) or not tok: raise ValueError()
    h={'Authorization':'Basic '+base64.b64encode((aid+':'+tok).encode()).decode()}; root='https://api.plivo.com/v1/Account/'+aid+'/'
    if name=='connection_verify':
        v=get(root,h)
        if v.get('auth_id')!=aid: raise ValueError()
        return {'provider':'plivo','status':'verified','mode':'read-only','accountType':v.get('account_type'),'billingMode':v.get('billing_mode')}
    f='call_uuid' if name=='get_cdr' else 'message_uuid'; ident=args.get(f)
    if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9-]{8,128}',ident): raise ValueError()
    v=get(root+('Call/' if name=='get_cdr' else 'Message/')+urllib.parse.quote(ident,safe='')+'/',h)
    keys=('call_uuid','call_status','direction','initiation_time','answer_time','end_time','duration','bill_duration') if name=='get_cdr' else ('message_uuid','message_state','message_direction','message_time','error_code','units')
    return {k:v.get(k) for k in keys if k in v}

def sinch(name,args):
    s=secret(); req=('username','password','project_id','app_id')
    if any(not isinstance(s.get(k),str) or not s[k] for k in req): raise ValueError()
    tok=post_form('https://auth.aclwhatsapp.com/realms/ipmessaging/protocol/openid-connect/token',{'grant_type':'password','client_id':'ipmessaging-client','username':s['username'],'password':s['password']}).get('access_token')
    if not isinstance(tok,str) or not tok: raise ValueError()
    app=get('https://convapi.aclwhatsapp.com/v1/projects/'+s['project_id']+'/apps/'+s['app_id'],{'Authorization':'Bearer '+tok})
    if app.get('id')!=s['app_id']: raise ValueError()
    out={'provider':'sinch','platform':'sinch-india-rcs','status':'verified','projectId':s['project_id'],'appId':app['id']}
    for k in ('display_name','name','region'):
        if k in app and isinstance(app[k],(str,int,float,bool)): out[k]=app[k]
    return out

def run(name,args):
    specs={x['name']:x['inputSchema'] for x in tools()}; s=specs.get(name)
    if not s or not isinstance(args,dict) or set(args)-set(s['properties']) or set(s['required'])-set(args): raise ValueError()
    return plivo(name,args) if os.environ['PROVIDER']=='plivo' else sinch(name,args)

def handler(event,context):
    h={k.lower():v for k,v in (event.get('headers') or {}).items()}; base=os.environ['API_BASE']
    challenge={'WWW-Authenticate':'Bearer resource_metadata="'+base+'/.well-known/oauth-protected-resource", scope="'+SCOPE+'"'}
    b=h.get('authorization','')
    if not b.startswith('Bearer '): return reply(401,{'error':'Staff OAuth authorization required'},challenge)
    try: auth(b[7:])
    except PermissionError: return reply(403,{'error':'Current staff administrator membership required'})
    except Exception: return reply(401,{'error':'Staff OAuth authorization required'},challenge)
    if (event.get('requestContext') or {}).get('http',{}).get('method')!='POST': return reply(405,{'error':'Use POST'},{'Allow':'POST'})
    if h.get('mcp-protocol-version','2025-11-25') not in PROTOCOLS: return reply(400,{'error':'Unsupported MCP protocol version'})
    rid=None
    try:
        raw=event.get('body','')
        if event.get('isBase64Encoded'): raw=base64.b64decode(raw,validate=True).decode()
        q=json.loads(raw); rid=q.get('id'); m=q.get('method'); p=q.get('params',{})
        if 'id' not in q:
            if m in {'notifications/initialized','notifications/cancelled'}: return reply(202,{})
            raise ValueError()
        if m=='initialize':
            v=p.get('protocolVersion'); result={'protocolVersion':v if v in PROTOCOLS else '2025-11-25','capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'wecare-'+os.environ['PROVIDER']+'-provider-mcp','version':'1.0.0'}}
        elif m=='ping': result={}
        elif m=='tools/list': result={'tools':tools()}
        elif m=='tools/call': result={'content':[{'type':'text','text':json.dumps(run(p.get('name'),p.get('arguments',{})),default=str)}],'isError':False}
        else: return reply(200,{'jsonrpc':'2.0','id':rid,'error':{'code':-32601,'message':'Method not found'}})
        return reply(200,{'jsonrpc':'2.0','id':rid,'result':result})
    except Exception:
        return reply(200,{'jsonrpc':'2.0','id':rid,'error':{'code':-32603,'message':'Operation failed; no credentials returned'}})
