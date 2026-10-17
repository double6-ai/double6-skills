"""依据源命名目标和成品语义锚点，把 GoToR 改为中文 PDF 内部 GoTo。"""
import re,unicodedata,math
from io import BytesIO
from pathlib import Path
from pypdf.generic import read_object,DictionaryObject
import fitz
from remote_destination_audit import source_destination,xyz,equivalent
from raw_link_actions import _parsed_action

POLICY={'id':'semantic_internal_citation_v1','maximum_pages':20,'maximum_annotations':1000,
 'reference_prefix_characters':32,'destination_margin_pt':2.,'coordinate_tolerance_pt':.001,
 'split_line_baseline_tolerance_pt':.25,'split_line_max_gap_heights':2.,
 'case_overrides_allowed':False,'missing_or_ambiguous_anchor':'stop_complete_write'}

def canonical(s):
 return ''.join(c for c in unicodedata.normalize('NFKC',s) if not c.isspace() and unicodedata.category(c)!='Cf')

def lines(doc):
 if len(doc)>POLICY['maximum_pages']:raise ValueError('page_budget_exceeded')
 out=[]
 for i in range(len(doc)):
  blocks=doc[i].get_text('dict',flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']
  for b in blocks:
   for line in b.get('lines',[]):
    text=''.join(s['text'] for s in line['spans'])
    out.append({'page':i+1,'bbox':line['bbox'],'text':text,'canonical':canonical(text),
                'baseline':line['spans'][0]['origin'][1]})
 return join_reference_markers(out)

def join_reference_markers(rows):
 """合并源印刷行拆开的编号片段；同基线、同列的相邻内容必须唯一。"""
 result=[]
 for row in rows:
  if not re.fullmatch(r'\d+\.',row['canonical']):result.append(row);continue
  box=row['bbox'];height=box[3]-box[1]
  neighbors=[r for r in rows if r is not row and r['page']==row['page']
   and abs(r.get('baseline',r['bbox'][1])-row.get('baseline',box[1]))<=POLICY['split_line_baseline_tolerance_pt']
   and 0<=r['bbox'][0]-box[2]<=height*POLICY['split_line_max_gap_heights']
   and r['canonical'] and not re.fullmatch(r'\d+\.',r['canonical'])]
  if len(neighbors)!=1:result.append(row);continue
  neighbor=neighbors[0];text=row['text']+' '+neighbor['text'];b=neighbor['bbox']
  result.append({**row,'text':text,'canonical':canonical(text),'bbox':[min(box[0],b[0]),min(box[1],b[1]),max(box[2],b[2]),max(box[3],b[3])],
                 'joined_printed_line_fragments':True})
 return result

def unique(values,reason):
 if len(values)!=1:raise ValueError(reason+f':{len(values)}')
 return values[0]

def semantic_anchor(name,literal,destination,source_lines,target_lines):
 name=unicodedata.normalize('NFKC',name.replace('\ufeff','')).split(':',1)[-1].strip()
 ref=re.match(r'^(\d+)\.\s',name);fig=re.match(r'^Fig\.\s*(\d+)\b',name)
 page=destination['page_index']+1
 if ref:
  n=ref[1];prefix=canonical(name)[:POLICY['reference_prefix_characters']]
  candidates=lambda values:[r for r in values if re.match(r'^'+re.escape(n)+r'\.\s',r['text']) and r['canonical'].startswith(prefix)]
  sa=unique([r for r in candidates(source_lines) if r['page']==page],'source_reference_identity_missing_or_ambiguous')
  ta=unique(candidates(target_lines),'target_reference_identity_missing_or_ambiguous')
  return {'kind':'reference','identity':n,'source_name_prefix':prefix,'source_anchor':sa,'target_anchor':ta}
 if fig:
  n=fig[1]
  sa=unique([r for r in source_lines if r['page']==page and re.match(r'^Fig\.\s*'+re.escape(n)+r'\s*[|｜]',r['text'])],'source_figure_identity_missing_or_ambiguous')
  ta=unique([r for r in target_lines if re.match(r'^图\s*'+re.escape(n)+r'\s*[|｜]',r['text'])],'target_figure_identity_missing_or_ambiguous')
  return {'kind':'figure','identity':n,'source_anchor':sa,'target_anchor':ta}
 # Unnamed InDesign equation anchors require an independently unique, isolated equation number.
 if not re.match(r'^(?:Anchor\s+\d+|\ufffc)(?::\d+)?$',name):raise ValueError('unknown_source_destination_semantics')
 n=canonical(literal)
 if not n.isdigit():raise ValueError('equation_literal_not_numeric')
 query='('+n+')'
 sa=unique([r for r in source_lines if r['page']==page and r['canonical']==query],'source_equation_identity_missing_or_ambiguous')
 ta=unique([r for r in target_lines if r['canonical']==query],'target_equation_identity_missing_or_ambiguous')
 return {'kind':'equation','identity':n,'source_anchor':sa,'target_anchor':ta}

def plan(source,target,bindings):
 if not bindings or len(bindings)>POLICY['maximum_annotations']:raise ValueError('annotation_budget_or_scope_missing')
 actual={(p+1,l['xref']) for p in range(len(target)) for l in target[p].get_links() if l['kind']==fitz.LINK_GOTOR}
 if actual!={(r['page'],r['xref']) for r in bindings}:raise ValueError('complete_remote_scope_required')
 source_lines=lines(source);target_lines=lines(target);sx={source.page_xref(p):p for p in range(len(source))};out=[]
 for r in bindings:
  kind,name=source.xref_get_key(r['source_xref'],'Dest')
  if kind=='null':kind,name=source.xref_get_key(r['source_xref'],'A/D')
  if kind not in ('name','string'):raise ValueError('named_source_identity_required')
  expected=source_destination(source,r['source_xref'],sx)
  action=_parsed_action(target.xref_get_key(r['xref'],'A')[1])
  filespec=action.get('/F');filename=str(filespec.get('/F')) if isinstance(filespec,dict) else str(filespec)
  if filename!=Path(source.name).name or (isinstance(filespec,dict) and '/UF' in filespec and str(filespec['/UF'])!=filename):raise ValueError('remote_dependency_filename_identity_mismatch')
  if str(action.get('/S'))!='/GoToR' or '/Next' in action or not equivalent(expected,xyz(action['/D'])):raise ValueError('existing_remote_source_binding_mismatch')
  anchor=semantic_anchor(name,r['target_literal'],expected,source_lines,target_lines)
  page=target[anchor['target_anchor']['page']-1];box=fitz.Rect(anchor['target_anchor']['bbox'])
  point=fitz.Point(max(page.rect.x0,box.x0-POLICY['destination_margin_pt']),max(page.rect.y0,box.y0-POLICY['destination_margin_pt']))
  if not page.rect.contains(point):raise ValueError('target_anchor_outside_page')
  native=point*~page.transformation_matrix
  out.append({'host_page':r['page'],'xref':r['xref'],'source_xref':r['source_xref'],'source_name':name,'before_action':target.xref_get_key(r['xref'],'A')[1],
    **anchor,'target_page':page.number+1,'target_page_xref':page.xref,'target_point':list(point),'native_point':list(native),'zoom':expected['zoom']})
 return {'policy':POLICY,'bindings':out,'complete_scope':True}

def apply(document,plan):
 if plan['policy']!=POLICY or not plan['complete_scope']:raise ValueError('frozen_complete_plan_required')
 for row in plan['bindings']:
  if document.xref_get_key(row['xref'],'A')[1]!=row['before_action']:raise ValueError('write_input_action_changed')
  if document.page_xref(row['target_page']-1)!=row['target_page_xref']:raise ValueError('write_target_page_identity_changed')
 for row in plan['bindings']:
  x,y=row['native_point'];zoom='null' if row['zoom'] is None else str(row['zoom'])
  document.xref_set_key(row['xref'],'A',f'<< /S /GoTo /D [{row["target_page_xref"]} 0 R /XYZ {x:.8f} {y:.8f} {zoom}] >>')

def verify(before,after,plan):
 if len(before)!=len(after):raise ValueError('saved_page_count_changed')
 owned={r['xref']:r for r in plan['bindings']};counts={'reference':0,'figure':0,'equation':0}
 page_xrefs={after.page_xref(p):p for p in range(len(after))}
 for p in range(len(after)):
  aa=before[p].get_links();bb=after[p].get_links()
  if {l['xref'] for l in aa}!={l['xref'] for l in bb}:raise ValueError('saved_annotation_inventory_changed')
  for l in aa:
   x=l['xref'];a=before.xref_object(x);b=after.xref_object(x)
   if x not in owned:
    if a!=b:raise ValueError('unowned_annotation_changed')
    continue
   row=owned[x]
   if before.xref_get_key(x,'Rect')!=after.xref_get_key(x,'Rect') or before.xref_get_key(x,'NM')!=after.xref_get_key(x,'NM'):raise ValueError('owned_click_frame_or_name_changed')
   # Compare every other raw field, not only the reader's flattened link dictionary.
   keys=set(before.xref_get_keys(x))|set(after.xref_get_keys(x))
   if any(before.xref_get_key(x,k)!=after.xref_get_key(x,k) for k in keys-{'A'}):raise ValueError('other_annotation_field_changed')
   raw=after.xref_get_key(x,'A')[1]
   if len(raw.encode())>65536:raise ValueError('saved_action_budget_exceeded')
   action=read_object(BytesIO(raw.encode()),object())
   if not isinstance(action,DictionaryObject) or set(action)!={'/S','/D'}:raise ValueError('saved_direct_single_internal_action_required')
   actual=xyz(action['/D'],page_xrefs)
   expected={'page_index':row['target_page']-1,'view':'XYZ','left':row['native_point'][0],'top':row['native_point'][1],'zoom':row['zoom']}
   if str(action['/S'])!='/GoTo' or set(action)!= {'/S','/D'} or not equivalent(actual,expected):raise ValueError('saved_internal_destination_mismatch')
   counts[row['kind']]+=1
 if any(l['kind']==fitz.LINK_GOTOR for p in range(len(after)) for l in after[p].get_links()):raise ValueError('remote_action_remaining')
 return {'pass':True,'complete_internal_destinations':len(owned),'counts':counts,'click_frames_and_other_fields_exact':True,'remaining_remote_actions':0}
