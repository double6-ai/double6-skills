"""LM Studio native Chat：显式无历史输入与严格真实响应合同。"""
import math
NATIVE_ENDPOINT='http://127.0.0.1:1234/api/v1/chat'
CONTRACT_ID='lmstudio_native_chat_v1'
TRANSPORT={'request_timeout_seconds':110,'max_attempts':1}
PARAMETERS={'reasoning':'off','stream':False,'store':False,'temperature':0.7,
            'top_p':1.0,'repeat_penalty':1.0,'max_output_tokens':2048,'context_length':4096}
OFFICIAL_SOURCE='https://lmstudio.ai/docs/developer/rest/chat'

def native_payload(model,system,source):
    if not all(isinstance(x,str) and x for x in (model,system,source)):
        raise ValueError('explicit model, control and complete literal source required')
    return {'model':model,'system_prompt':system,'input':source,**PARAMETERS}

def validate_native_response(response,expected_instance):
    if response.get('model_instance_id')!=expected_instance:
        raise ValueError('actual model instance differs from owned freeze')
    stats=response.get('stats')
    if not isinstance(stats,dict) or not valid_count(stats.get('reasoning_output_tokens')) or stats['reasoning_output_tokens']!=0:
        raise ValueError('zero reasoning token count not demonstrated')
    output=response.get('output')
    if not isinstance(output,list) or len(output)!=1 or any(not isinstance(x,dict) or x.get('type')!='message' or not isinstance(x.get('content'),str) or not x['content'].strip() for x in output):
        raise ValueError('non-message, reasoning, tool or invalid output rejected')
    for field in ('input_tokens','total_output_tokens'):
        if not valid_count(stats.get(field)) or stats[field]<=0:
            raise ValueError('actual token usage absent or invalid')
    return stats


def valid_count(value):
    return (type(value) is int and value>=0) or (type(value) is float and math.isfinite(value) and value>=0 and value.is_integer())


def native_text(response,expected_instance):
    validate_native_response(response,expected_instance)
    return '\n\n'.join(item['content'].strip() for item in response['output'])


def post_native(*,base_url,model,system,source,attempt_callback=None,response_callback=None):
    from model_client import post_chat
    endpoint=base_url.rstrip('/').removesuffix('/v1')+'/api/v1/chat'
    return post_chat(endpoint=endpoint,model=model,system_prompt=system,user_input=source,
                     provider='lmstudio_native',extra_body=PARAMETERS,
                     **TRANSPORT,attempt_callback=attempt_callback,response_callback=response_callback)
