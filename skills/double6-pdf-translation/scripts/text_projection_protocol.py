"""整段翻译的可逆保护协议：保护元素原位恢复，缺失/重复/未知 token 立即失败。"""
from __future__ import annotations
import copy,hashlib,json,re
TOKEN=re.compile(r'\[\[PT_(\d{4})\]\]')
REF=re.compile(r'\[\d+(?:\s*[,–-]\s*\d+)*\]')
class ProjectionError(ValueError):pass

def encode(spans:list[dict])->dict:
    protected=[];parts=[]
    def protect(span=None,**metadata):
        i=len(protected)
        if i>=1000:raise ProjectionError('protected span count limit')
        token=f'[[PT_{i:04d}]]';protected.append({'token':token,'kind':'atom' if span is not None else 'boundary',**metadata,**({'span':copy.deepcopy(span)} if span is not None else {})})
        return token
    def plain(content):
        if not isinstance(content,str) or not content:raise ProjectionError('empty text span')
        if '[[PT_' in content:raise ProjectionError('source token collision')
        position=0;result=[]
        for match in REF.finditer(content):
            result.append(content[position:match.start()]);result.append(protect({'type':'text','content':match.group()}));position=match.end()
        result.append(content[position:]);return ''.join(result)
    def one(span,inside_link=False):
        kind=span.get('type')
        if kind not in ('text','equation_inline','code_inline','hyperlink'):raise ProjectionError('unknown span type')
        if kind=='hyperlink':
            if inside_link:raise ProjectionError('nested hyperlink unsupported')
            if not span.get('url') or not span.get('content'):raise ProjectionError('incomplete hyperlink')
            begin=protect(container='hyperlink',direction='begin',url=span['url'])
            middle=''.join(one(s,True) for s in span['content'])
            return begin+middle+protect(container='hyperlink',direction='end')
        if kind!='text' or any(s in ('superscript','subscript') for s in span.get('styles',[])):return protect(span)
        if span.get('styles'):
            begin=protect(container='textstyle',direction='begin',styles=span['styles'])
            middle=plain(span['content'])
            return begin+middle+protect(container='textstyle',direction='end')
        return plain(span.get('content'))
    for span in spans:parts.append(one(span))
    text=''.join(parts)
    return {'schema_version':1,'text':text,'protected':protected,'source_spans_sha256':hashlib.sha256(json.dumps(spans,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}

def decode(translation:str,binding:dict,*,allow_atom_reordering:bool=False)->list[dict]:
    if REF.search(translation):raise ProjectionError('literal reference outside protected token')
    expected=[p['token'] for p in binding['protected']]
    actual=[m.group() for m in TOKEN.finditer(translation)]
    if sorted(expected)!=sorted(actual):raise ProjectionError('protected tokens missing duplicated or unknown')
    if '[[PT_' in TOKEN.sub('',translation):raise ProjectionError('malformed protected token')
    # 连续引用及原始脚注关系不得被模型重新排序。
    if actual!=expected:
        if not allow_atom_reordering:raise ProjectionError('protected token order changed')
        # 中文修饰语可使科学名称调序；引用与容器边界继续保序。调序仍须语义复核。
        ordered={p['token'] for p in binding['protected'] if p['kind']!='atom'
                 or p['span']['type']!='equation_inline'
                 or REF.fullmatch(p['span']['content'])}
        if [v for v in actual if v in ordered]!=[v for v in expected if v in ordered]:
            raise ProjectionError('reference_or_boundary_order_changed')
    lookup={p['token']:p for p in binding['protected']};out=[];stack=[(None,out)];position=0
    for m in TOKEN.finditer(translation):
        if m.start()>position:stack[-1][1].append({'type':'text','content':translation[position:m.start()]})
        token=lookup[m.group()]
        if token['kind']=='atom':stack[-1][1].append(copy.deepcopy(token['span']))
        elif token['direction']=='begin':stack.append((token,[]))
        else:
            if len(stack)==1:raise ProjectionError('unmatched protected boundary')
            opening,content=stack.pop()
            if opening['container']!=token['container'] or not content:raise ProjectionError('invalid or empty protected container')
            if token['container']=='hyperlink':stack[-1][1].append({'type':'hyperlink','url':opening['url'],'content':content})
            else:
                if any(s['type']!='text' for s in content):raise ProjectionError('styled text container has non-text child')
                for span in content:span['styles']=list(dict.fromkeys(opening['styles']+span.get('styles',[])))
                stack[-1][1].extend(content)
        position=m.end()
    if len(stack)!=1:raise ProjectionError('unclosed protected container')
    if position<len(translation):out.append({'type':'text','content':translation[position:]})
    if not out:raise ProjectionError('empty translated paragraph')
    return out

def encode_plain(source:str)->dict:return encode([{'type':'text','content':source}])
def decoded_plain(translation:str,binding:dict)->str:
    spans=decode(translation,binding)
    if any(s['type']!='text' for s in spans):raise ProjectionError('plain decode cannot flatten protected non-text spans')
    return ''.join(s['content'] for s in spans)
