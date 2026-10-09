"""One actual text-only preview; no fake output or application/tool side effects."""
import ast,json,os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

PATH=Path(__file__).resolve().parents[1]/'amplify/functions/ai/ai-config-management/handler.py'

def load(table, runtime):
 tree=ast.parse(PATH.read_text());selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_test_ai_response'];client=Mock(return_value=runtime)
 scope={'Dict':dict,'Any':object,'json':json,'os':os,'boto3':SimpleNamespace(client=client),'dynamodb':SimpleNamespace(Table=lambda _:table),'SYSTEM_CONFIG_TABLE':'fixture','DEFAULT_AI_CONFIG':{'modelId':'amazon.nova-pro-v1:0','defaultLanguage':'en'},'SUPPORTED_LANGUAGES':{'en':'English','hi':'Hindi','bn':'Bengali'},'cors_headers':lambda _: {},'origin':'','logger':Mock(),'_error_response':lambda status,message:{'statusCode':status,'body':json.dumps({'error':message})}}
 exec(compile(ast.Module(body=selected,type_ignores=[]),str(PATH),'exec'),scope);return scope,client

@pytest.fixture
def preview():
 table=Mock();table.get_item.return_value={'Item':{'configValue':json.dumps({'modelId':'amazon.nova-lite-v1:0','defaultLanguage':'en','enabled':False,'enabledTools':['send_whatsapp']})}};runtime=Mock();runtime.converse.return_value={'stopReason':'end_turn','output':{'message':{'role':'assistant','content':[{'text':'A real model fixture response.'}]}}};scope,client=load(table,runtime);return scope,table,runtime,client

def test_generates_existing_configured_text_model_without_tools_or_writes(preview):
 scope,table,runtime,client=preview;result=scope['_test_ai_response']({'message':'  hello  ','modelId':'untrusted-other','tools':['send_whatsapp']},'request')
 assert result['statusCode']==200;body=json.loads(result['body']);assert body['response']=='A real model fixture response.' and body['message']=='hello';assert body['detectedLanguage']=='und' and body['responseLanguage']=='en' and body['languageSource']=='configured'
 kwargs=runtime.converse.call_args.kwargs;assert kwargs['modelId']=='amazon.nova-lite-v1:0';assert kwargs['messages']==[{'role':'user','content':[{'text':'hello'}]}];assert kwargs['inferenceConfig']=={'maxTokens':256,'temperature':0.2};assert 'toolConfig' not in kwargs and 'guardrailConfig' not in kwargs;assert client.call_args.args==('bedrock-runtime',);table.get_item.assert_called_once_with(Key={'id':'ai_config'});table.put_item.assert_not_called();table.update_item.assert_not_called();table.delete_item.assert_not_called();scope['logger'].info.assert_not_called()

def test_missing_saved_config_uses_existing_default_without_initializing_row(preview):
 scope,table,runtime,_=preview;table.get_item.return_value={};assert scope['_test_ai_response']({'message':'hello'},'request')['statusCode']==200;assert runtime.converse.call_args.kwargs['modelId']=='amazon.nova-pro-v1:0';table.put_item.assert_not_called()

def test_supported_response_language_is_explicit(preview):
 scope,_,runtime,_=preview;body=json.loads(scope['_test_ai_response']({'message':'hello','language':'hi'},'request')['body']);assert body['responseLanguage']=='hi' and body['languageSource']=='requested';assert 'Hindi' in runtime.converse.call_args.kwargs['system'][0]['text']

@pytest.mark.parametrize('body',[None,[],{}, {'message':None},{'message':12},{'message':' '},{'message':'x'*2001},{'message':'\ud800'},{'message':'hello','language':'invalid'},{'message':'hello','language':[]}])
def test_invalid_input_never_reaches_model_or_config(preview,body):
 scope,table,runtime,_=preview;assert scope['_test_ai_response'](body,'request')['statusCode']==400;table.get_item.assert_not_called();runtime.converse.assert_not_called()

@pytest.mark.parametrize('config',[{},None,[],{'modelId':''},{'modelId':'unconfigured-model'},{'modelId':'amazon.nova-lite-v1:0','defaultLanguage':'invalid'}])
def test_unconfigured_model_or_language_fails_explicitly_without_inference(preview,config):
 scope,table,runtime,_=preview;table.get_item.return_value={'Item':{'configValue':config}};result=scope['_test_ai_response']({'message':'hello'},'request');assert result['statusCode']==503;assert 'response' not in json.loads(result['body']);runtime.converse.assert_not_called()

@pytest.mark.parametrize('result',[{}, {'stopReason':'tool_use','output':{'message':{'role':'assistant','content':[{'toolUse':{'name':'send_whatsapp'}}]}}}, {'stopReason':'guardrail_intervened'}, {'stopReason':'end_turn','output':{'message':{'role':'assistant','content':[{'text':' '}]}}}, {'stopReason':'end_turn','output':{'message':{'role':'assistant','content':[{'text':'x'*4001}]}}}, {'stopReason':'end_turn','output':{'message':{'role':'user','content':[{'text':'hello'}]}}}, {'stopReason':'end_turn','output':{'message':{'role':'assistant','content':[{'text':'hello','toolUse':{}}]}}}])
def test_failed_or_nontext_provider_result_never_fabricates_success(preview,result):
 scope,_,runtime,_=preview;runtime.converse.return_value=result;response=scope['_test_ai_response']({'message':'hello'},'request');assert response['statusCode']==503;assert 'response' not in json.loads(response['body'])

@pytest.mark.parametrize('failure_target',['model','config'])
def test_exception_details_and_prompt_never_escape(preview,failure_target):
 scope,table,runtime,_=preview
 if failure_target=='model':runtime.converse.side_effect=RuntimeError('provider-secret fixture-prompt')
 else:table.get_item.side_effect=RuntimeError('provider-secret fixture-prompt')
 response=scope['_test_ai_response']({'message':'fixture-prompt'},'request');assert response['statusCode']==503;assert 'provider-secret' not in response['body'] and 'fixture-prompt' not in response['body'];logged=str(scope['logger'].mock_calls);assert 'provider-secret' not in logged and 'fixture-prompt' not in logged;table.put_item.assert_not_called()
