"""复制前冻结原始链接动作；公开to字段不能证明远程XYZ坐标保持。"""
from __future__ import annotations
from io import BytesIO
import math
import fitz
from pypdf.generic import read_object,IndirectObject

ACTION_KEYS=('Dest','A/S','A/D','A/URI','A/F','A/F/F','A/F/UF')

def _plain(value):
    if isinstance(value,(fitz.Rect,fitz.Point,fitz.Matrix)):return list(value)
    if isinstance(value,dict):return {k:_plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_plain(v) for v in value]
    return value

def _direct(value):
    if isinstance(value,IndirectObject):raise ValueError('raw_link_indirect_action_dependency_requires_mapping')
    if isinstance(value,dict):
        for item in value.values():_direct(item)
    elif isinstance(value,list):
        for item in value:_direct(item)

def _parsed_action(raw):
    if len(raw.encode('utf-8'))>65536:
        raise ValueError('raw_link_direct_bounded_action_required')
    value=read_object(BytesIO(raw.encode('utf-8')),object())
    _direct(value)
    return value

def _same_public_link(actual,expected):
    a,b=_plain(actual),_plain(expected)
    if {k:v for k,v in a.items() if k not in ('xref','from','id')}!={k:v for k,v in b.items() if k not in ('xref','from','id')}:
        return False
    if len(a['from'])!=4 or len(b['from'])!=4:
        return False
    return all(math.isfinite(x) and math.isfinite(y) and abs(x-y)<=.001 for x,y in zip(a['from'],b['from']))

def capture_page_link_actions(document,page_index,*,maximum_links=2000):
    """限URI及直接GoToR动作；内部页引用/链式动作需另外映射，不能复制旧xref。"""
    if type(page_index)is not int or not 0<=page_index<len(document):raise ValueError('raw_link_source_page_invalid')
    if type(maximum_links)is not int or not 1<=maximum_links<=2000:raise ValueError('raw_link_annotation_budget')
    links=document[page_index].get_links()
    if len(links)>maximum_links:raise ValueError('raw_link_annotation_budget')
    records=[]
    for link in links:
        fields=_plain(link);xref=link.get('xref')
        if type(xref)is not int or xref<=0:raise ValueError('raw_link_actual_xref_required')
        if fields['kind'] not in (fitz.LINK_URI,fitz.LINK_GOTOR):raise ValueError('raw_link_internal_or_nonstandard_action_requires_mapping')
        if any(not math.isfinite(v) for v in fields['from']):raise ValueError('raw_link_rectangle_not_finite')
        kind,raw=document.xref_get_key(xref,'A')
        if kind!='dict' or len(raw.encode())>65536:raise ValueError('raw_link_direct_bounded_action_required')
        # pdf=None会使pypdf把间接对象解析失败后静默丢弃；非空标记保留其类型。
        # 递归检查不解引用对象，所以无需加载原文整册或引入旧xref的对象图。
        action_object=read_object(BytesIO(raw.encode('utf-8')),object());_direct(action_object)
        if '/Next' in action_object or document.xref_get_key(xref,'AA')!=('null','null'):
            raise ValueError('raw_link_chained_or_additional_action_requires_mapping')
        actions={key:list(document.xref_get_key(xref,key)) for key in ACTION_KEYS}
        expected='/URI' if fields['kind']==fitz.LINK_URI else '/GoToR'
        if actions['A/S']!=['name',expected] or actions['Dest']!=['null','null']:
            raise ValueError('raw_link_public_and_actual_action_disagree')
        records.append({'source_xref':xref,'fields':fields,'raw_A':raw,'action':actions})
    return records

def bind_copied_link_actions(document,page_index,records):
    links=document[page_index].get_links()
    if len(links)!=len(records):raise ValueError('raw_link_copy_annotation_count_changed')
    for link,record in zip(links,records):
        a=_plain(link);b=record['fields']
        if {k:v for k,v in a.items() if k not in ('xref','from','id')}!={k:v for k,v in b.items() if k not in ('xref','from','id')}:
            raise ValueError('raw_link_copy_annotation_identity_changed')
        if max(abs(x-y) for x,y in zip(a['from'],b['from']))>.001:raise ValueError('raw_link_copy_rectangle_changed')
        record['candidate_xref']=link['xref']
    restore_raw_link_actions(document,records)

def restore_raw_link_actions(document,records):
    for record in records:
        document.xref_set_key(record['candidate_xref'],'A',record['raw_A'])
        name=record['fields'].get('id','')
        document.xref_set_key(record['candidate_xref'],'NM',fitz.get_pdf_str(name) if name else 'null')

def copy_page_with_raw_actions(destination,source,page_index):
    records=capture_page_link_actions(source,page_index)
    output_index=len(destination)
    destination.insert_pdf(source,from_page=page_index,to_page=page_index,links=True)
    bind_copied_link_actions(destination,output_index,records)
    return records

def rebind_expected_link_actions(document,page_index,records,expected_links):
    """删除重建或位移后按动作及预期矩形完整绑定；有歧义时先阻断再写回。"""
    links=document[page_index].get_links()
    if len(links)!=len(records) or len(expected_links)!=len(records):
        raise ValueError('raw_link_rebind_annotation_count_changed')
    # 预期位置必须绑定复制前的注释身份，禁止位置列表的顺序替代身份。
    by_source={r['source_xref']:r for r in records}
    if len(by_source)!=len(records) or {l.get('xref') for l in expected_links}!=set(by_source):
        raise ValueError('raw_link_expected_source_identity_changed')
    expected_by_source={l['xref']:l for l in expected_links}
    mapping=[]
    for link in links:
        possible=[r for r in records if _same_public_link(link,expected_by_source[r['source_xref']])]
        if len(possible)!=1:
            raise ValueError('raw_link_rebind_missing_or_ambiguous_host')
        mapping.append((link,possible[0]))
    if len({r['source_xref'] for _,r in mapping})!=len(records):
        raise ValueError('raw_link_rebind_source_annotation_reused')
    ordered=[]
    for link,record in mapping:
        record['candidate_xref']=link['xref']
        record['expected_fields']=_plain(expected_by_source[record['source_xref']])
        ordered.append(record)
    restore_raw_link_actions(document,ordered)
    return ordered

def verify_saved_link_actions(document,page_index,records):
    """保存重开核对完整动作和注释身份；位移后的点击几何由宿主适配器另验。"""
    links=document[page_index].get_links()
    if len(links)!=len(records):raise ValueError('raw_link_saved_annotation_count_changed')
    for link,record in zip(links,records):
        if link.get('id','')!=record['fields'].get('id',''):raise ValueError('raw_link_saved_name_or_order_changed')
        fields={key:list(document.xref_get_key(link['xref'],key)) for key in ACTION_KEYS}
        if fields!=record['action']:raise ValueError('raw_link_saved_action_changed')
        kind,raw=document.xref_get_key(link['xref'],'A')
        if kind!='dict' or _parsed_action(raw)!=_parsed_action(record['raw_A']):
            raise ValueError('raw_link_saved_full_action_changed')
        if not _same_public_link(link,record.get('expected_fields',record['fields'])):
            raise ValueError('raw_link_saved_rectangle_or_public_identity_changed')
    return {'raw_actions_exact':True,'annotations':len(records),'geometry_acceptance':False,
            'relative_file_accessibility_proved':False,'quality_pass':False}
