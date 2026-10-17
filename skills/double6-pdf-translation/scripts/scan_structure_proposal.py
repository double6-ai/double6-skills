# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""从现有OCR提出有限扫描排版草案；人工审核与跨页语义确认仍必需。"""
from pathlib import Path
import argparse,hashlib,json,re,statistics,copy
import fitz

POLICY={'version':2,'body_min_width_fraction':.70,'body_min_chars':70,
        'body_min_lines':3,'closing_min_top_fraction':.80,
        'protected_padding_pt':[10,6],'first_indent_min_fraction':.015,
        'body_indent_pt':21,'metadata_indent_pt':21,'heading_alignment':'center',
        'typography':{'body':{'font_size_pt':10.5,'baseline_step_pt':18},
                      'heading':{'font_size_pt':11,'baseline_step_pt':15},
                      'single_line_metadata':{'font_size_pt':10,'baseline_step_pt':14}}}

def ref(path):
 path=Path(path).resolve()
 return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def classify(block):
 text=''.join(item.get('content','') for item in block.get('content',[]))
 kind=block.get('type','');box=block['bbox'];lines=block.get('lines',[])
 # OCR sometimes calls the centered all-capitals document title a header.
 letters=[c for c in text if c.isalpha()]
 centered=abs((box[0]+box[2])/2-.5)<.12
 if kind=='header' and box[1]<.25 and .25<box[2]-box[0]<.9 and centered and len(letters)>=8 and len(text.split())<=16 and all(c.isupper() for c in letters):
  return 'heading','centered_uppercase_top_heading'
 if kind in {'page_number','header','footer','image','figure','table','equation'}:
  return 'protected','upstream_nonbody_or_margin_role'
 if kind=='doc_title':return 'heading','upstream_document_title'
 if re.search(r'\b(prepared|written|edited|compiled|radio\s+talk|address|lecture|report)\s+by\b|^\s*by\b',text,re.I):
  return 'single_line_metadata','generic_authorship_pattern'
 if len(lines)>=POLICY['body_min_lines'] or (box[2]-box[0]>=POLICY['body_min_width_fraction'] and len(text)>=POLICY['body_min_chars']):
  return 'body','multiline_or_wide_prose'
 if box[1]>=POLICY['closing_min_top_fraction']:
  return 'single_line_metadata','short_closing_block'
 return 'heading','short_nonbody_block_REQUIRES_REVIEW'

def propose(raw,dimensions):
 assert len(raw['pages'])==len(dimensions),'OCR/source page count mismatch'
 roles=[];inventory=[]
 for pi,(blocks,(width,height)) in enumerate(zip(raw['pages'],dimensions,strict=True)):
  inventory.append({'page':pi+1,'ocr_region_count':len(blocks),'proposed_role':'blank_scan_requires_source_confirmation' if not blocks else 'content_and_protected_regions'})
  for bi,block in enumerate(blocks):
   assert len(block['bbox'])==4 and all(0<=v<=1 for v in block['bbox']),'invalid normalized OCR geometry'
   role,reason=classify(block);box=[v*[width,height,width,height][j] for j,v in enumerate(block['bbox'])];original=list(box)
   if role=='protected':
    xpad,ypad=POLICY['protected_padding_pt'];box=[max(0,box[0]-xpad),max(0,box[1]-ypad),min(width,box[2]+xpad),min(height,box[3]+ypad)]
   bottom=min([other['bbox'][1]*height-3 for other in blocks if other['bbox'][1]>block['bbox'][1]+.001 and other['bbox'][0]<block['bbox'][2] and other['bbox'][2]>block['bbox'][0]]+[height-4])
   layout=[box[0],box[1],box[2],min(max(box[3],box[1]+30),bottom)]
   lines=block.get('lines',[]);indent=None
   delta=0
   if role in {'body','single_line_metadata'}:
    delta=(lines[0]['bbox'][0]-statistics.median(line['bbox'][0] for line in lines[1:])) if len(lines)>1 else 0
    indent=POLICY['body_indent_pt' if role=='body' else 'metadata_indent_pt'] if delta>POLICY['first_indent_min_fraction'] else 0
   if role=='heading':indent=0
   alignment='center' if role=='heading' or (reason=='generic_authorship_pattern' and len(lines)<=1) else 'left'
   roles.append({'id':f'P{pi+1}B{bi}','role':role,'source_page':pi+1,'physical_source_page':pi+1,'source_column':1,'source_bbox':box,'raw_ocr_bbox':original,'original_layout_bbox':layout,'alignment':alignment,'first_line_indent_pt':indent,'source_first_indent_estimate_pt':delta*width,'source_indent_basis':'OCR printed-line geometry; not native font measurement','y_shift_pt':0,'derivation':reason,'requires_review':True,'manual_override':False})
 return {'policy':'raw_ocr_structure_proposal_v1','parameters':POLICY,'roles':roles,'complete_page_inventory':inventory,'automatic_semantic_grouping':False,'automatic_crosspage_confirmation':False,'claim':'proposals only; source fullpage coverage, roles, geometry, blank pages and semantic boundaries require review'}

def checked_preparation_ref(value):
 """复用的每个文件仍须与冻结SHA一致，不静默重新绑定。"""
 if not isinstance(value,dict) or set(value)!={'path','sha256'}:
  raise ValueError('scan_prepare_reuse_invalid_ref')
 path=Path(value['path'])
 if not path.is_file() or ref(path)!=value:
  raise ValueError('scan_prepare_reuse_evidence_changed:'+str(path))
 return path

def reused_preparation_inputs(source,contract_path,explicit):
 """只复用同源已冻结输入；更换目标须另给语义审校，不继承接受。"""
 if any(explicit[k] is not None for k in ('ocr','groups','roles','font','ink','raw_targets')):
  raise ValueError('scan_prepare_reuse_conflicting_explicit_inputs')
 if (explicit['targets'] is None)!=(explicit['review'] is None):
  raise ValueError('scan_prepare_reuse_new_targets_require_semantic_review')
 contract_path=Path(contract_path);contract=json.loads(contract_path.read_text())
 if contract.get('kind')!='scan' or contract.get('policy')!='explicit_source_roles_and_anchors_v1':
  raise ValueError('scan_prepare_reuse_requires_scan_trial_contract')
 if contract.get('source_pdf_ref')!=ref(source):raise ValueError('scan_prepare_reuse_source_changed')
 for key,value in contract.items():
  if key.endswith('_ref'):checked_preparation_ref(value)
 for value in contract['code_refs']:checked_preparation_ref(value)
 # role_evidence predates the *_ref naming convention.
 checked_preparation_ref(contract['role_evidence'])
 frozen=json.loads(checked_preparation_ref(contract['preparation_inputs_ref']).read_text())
 for key in ('source','rawOCR','groups','roles','targets','semantic_review','font'):
  checked_preparation_ref(frozen[key])
 if frozen['source']!=contract['source_pdf_ref'] or frozen['font']!=contract['font_ref']:
  raise ValueError('scan_prepare_reuse_contract_input_mismatch')
 materialization_ref=contract.get('source_plan_materialization_ref')
 if frozen.get('source_plan_materialization_ref')!=materialization_ref:raise ValueError('scan_prepare_reuse_source_plan_binding_mismatch')
 if materialization_ref is not None:
  material=json.loads(checked_preparation_ref(materialization_ref).read_text())
  for key in ('source','original_rawOCR','source_plan','materializer_code','grouped_OCR','groups','roles'):checked_preparation_ref(material[key])
  if material['source']!=frozen['source'] or any(material[k]!=frozen[v]for k,v in [('grouped_OCR','rawOCR'),('groups','groups'),('roles','roles')]):raise ValueError('scan_prepare_reuse_materialized_inputs_mismatch')
 optional_packet=None
 raw_ref=frozen.get('raw_targets')
 if 'raw_targets' not in frozen:
  # Legacy manifests omitted RAW. Only the matching sibling review packet
  # can supply its own hash-bound RAW reference; absent RAW remains UNKNOWN.
  packet_path=contract_path.parent/'SOURCE_TARGET_REVIEW_PACKET.json'
  if packet_path.is_file():
   packet=json.loads(packet_path.read_text())
   if any(packet.get(k)!=frozen[v] for k,v in [('source','source'),('groups','groups'),('current_targets_ref','targets')]):
    raise ValueError('scan_prepare_reuse_legacy_packet_mismatch')
   raw_ref=packet.get('raw_targets_ref');optional_packet=ref(packet_path)
 if raw_ref is not None:checked_preparation_ref(raw_ref)
 ink_ref=contract.get('source_ink_protection_ref')
 if 'ink_protection' in frozen and frozen['ink_protection']!=ink_ref:
  raise ValueError('scan_prepare_reuse_ink_mismatch')
 paths={k:Path(frozen[v]['path']) for k,v in [('ocr','rawOCR'),('groups','groups'),('roles','roles'),('font','font'),('targets','targets'),('review','semantic_review')]}
 paths.update(ink=Path(ink_ref['path']) if ink_ref else None,raw_targets=Path(raw_ref['path']) if raw_ref else None)
 if explicit['targets'] is not None:
  paths.update(targets=Path(explicit['targets']),review=Path(explicit['review']))
  # A changed target cannot silently borrow the old target's review identity.
  current_target=ref(paths['targets']);review=json.loads(paths['review'].read_text())
  if review.get('source')!=ref(source) or review.get('current_target')!=current_target:
   raise ValueError('scan_prepare_reuse_new_review_target_binding_required')
 evidence={'policy':'same_source_reviewed_preparation_reuse_v1','previous_contract':ref(contract_path),'previous_inputs':contract['preparation_inputs_ref'],'source_plan_materialization_ref':materialization_ref,'legacy_optional_packet':optional_packet,'original_raw_targets_ref':raw_ref,'targets_replaced':explicit['targets'] is not None,'semantic_acceptance_inherited':False,'human_acceptance':False,'strict_delivery':False,'first_time_structure_work_reduced':False}
 return paths,evidence

def materialize_source_plan(source,ocr,plan_path,output,*,max_pages=5,draft_only=False):
 """把具名人工确认的原OCR分组计划转成现有输入；不识别或确认语义边界。"""
 import math
 source,ocr,plan_path,output=map(Path,(source,ocr,plan_path,output))
 if output.exists():raise ValueError('scan_plan_requires_new_output')
 plan=json.loads(plan_path.read_text());raw=json.loads(ocr.read_text());sr=ref(source)
 if plan.get('source')!=sr or plan.get('rawOCR')!=ref(ocr):raise ValueError('scan_plan_source_or_OCR_changed')
 if not draft_only and plan.get('complete_source_review_confirmed')is not True:raise ValueError('scan_plan_source_confirmation_required')
 with fitz.open(source)as doc:
  if not 1<=len(doc)<=max_pages<=20 or len(raw['pages'])!=len(doc):raise ValueError('scan_plan_page_scope')
  dims=[(p.rect.width,p.rect.height)for p in doc]
 adapted=copy.deepcopy(raw);adapted['pages']=[[]for _ in dims];seen=set();records=[];joins=[];last_page=-1
 for item in plan['regions']:
  pi=item['page']-1;indices=item['raw_blocks'];role=item['role']
  if not 0<=pi<len(dims) or role not in {'body','heading','single_line_metadata','protected'} or (not draft_only and not item.get('confirmation')):
   raise ValueError('scan_plan_role_or_confirmation')
  if pi<last_page:raise ValueError('scan_plan_page_order')
  last_page=pi
  if not indices or any(type(i)is not int or not 0<=i<len(raw['pages'][pi])for i in indices) or indices!=list(range(indices[0],indices[-1]+1)):
   raise ValueError('scan_plan_contiguous_fragment_scope')
  if any((pi,i)in seen for i in indices):raise ValueError('scan_plan_duplicate_fragment')
  if not draft_only and len(indices)>1 and not item.get('join_confirmation'):raise ValueError('scan_plan_join_confirmation_required')
  if indices[0]!=len([i for p,i in seen if p==pi]):raise ValueError('scan_plan_reading_order')
  seen.update((pi,i)for i in indices);parts=[raw['pages'][pi][i]for i in indices];joined='';preserve=item.get('preserve_hyphen_before_raw_blocks',[]);used_preserve=set()
  if not isinstance(preserve,list)or any(type(i)is not int or i not in indices[1:]for i in preserve):raise ValueError('scan_plan_hyphen_directive_scope')
  for i,b in zip(indices,parts,strict=True):
   text=''.join(x.get('content','')for x in b.get('content',[]))
   if role=='single_line_metadata':joined+=('\n'if joined else'')+text
   elif len(joined)>=2 and joined.endswith('-') and joined[-2].isalpha() and text[:1].islower():
    keep=i in preserve
    joins.append({'page':pi+1,'next_raw_block':i,'before_tail':joined[-24:],'next_head':text[:24],'policy':'explicit_compound_hyphen_preserved'if keep else'reviewed_printed_word_wrap_only'})
    if keep:joined+=text;used_preserve.add(i)
    else:joined=joined[:-1]+text
   else:joined+=(' 'if joined else'')+text
  if set(preserve)!=used_preserve:raise ValueError('scan_plan_unused_hyphen_directive')
  if not draft_only and ' '.join(joined.split())!=' '.join(item.get('complete_source','').split()):raise ValueError('scan_plan_complete_source_mismatch')
  # Explicit full-source confirmation, not punctuation or a page ID, authorizes joins.
  box=[min(b['bbox'][0]for b in parts),min(b['bbox'][1]for b in parts),max(b['bbox'][2]for b in parts),max(b['bbox'][3]for b in parts)]
  block=copy.deepcopy(parts[0]);block.update(bbox=box,type='text'if role!='protected'else parts[0]['type'],content=[{'type':'text','content':joined}],lines=[l for b in parts for l in b.get('lines',[])])
  bi=len(adapted['pages'][pi]);adapted['pages'][pi].append(block);records.append((f'P{pi+1}B{bi}',item,joined,box))
 if seen!={(pi,bi)for pi,page in enumerate(raw['pages'])for bi in range(len(page))}:raise ValueError('scan_plan_incomplete_raw_coverage')
 if draft_only:
  output.mkdir(parents=True);draft=copy.deepcopy(plan);draft.update(source=sr,rawOCR=ref(ocr),complete_source_review_confirmed=False,complete_semantic_scope_confirmed=False,source_confirmation=None,source_role_confirmation=None,source_group_confirmation=None,blank_page_confirmations=[],human_acceptance=False,human_accepted=False,strict_delivery=False,semantic_acceptance=False,draft_derivation={'manual_seed':ref(plan_path),'materializer_code':ref(__file__),'automatic_grouping':False},regions=[])
  for gid,item,text,_ in records:
   proposed=copy.deepcopy(item);proposed.update(id=gid,complete_source=text,confirmation=None,source_group_confirmation=None,source_role_confirmation=None,role_confirmation=None,boundary_confirmation=None,join_confirmation=None,geometry_confirmation=None,human_acceptance=False,strict_delivery=False,semantic_acceptance=False,requires_review=True);draft['regions'].append(proposed)
  path=output/'SOURCE_PLAN.draft.json';path.write_text(json.dumps(draft,ensure_ascii=False,indent=2)+'\n');return {'draft':path,'records':records,'joins':joins}
 accepted=propose(adapted,dims);byid={e['id']:e for e in accepted['roles']};groups=[];geometry_rows=0
 for gid,item,text,box in records:
  e=byid[gid];e.update(role=item['role'],manual_override=e['role']!=item['role'],source_role_confirmation=item['confirmation'])
  if e['role']=='single_line_metadata':e.update(alignment='left',first_line_indent_pt=0)
  if 'alignment'in item:e['alignment']=item['alignment']
  if 'first_line_indent_pt'in item:e['first_line_indent_pt']=item['first_line_indent_pt']
  for key in ('source_bbox','original_layout_bbox'):
   if key not in item:continue
   rect=item[key];w,h=dims[e['source_page']-1]
   if not item.get('geometry_confirmation') or len(rect)!=4 or any(type(v)not in (int,float)or not math.isfinite(v)for v in rect) or not (0<=rect[0]<rect[2]<=w and 0<=rect[1]<rect[3]<=h):raise ValueError('scan_plan_geometry_confirmation_or_bounds')
   e[key]=list(rect)
  if any(k in item for k in ('source_bbox','original_layout_bbox')):geometry_rows+=1;e['geometry_adaptation']=item['geometry_confirmation']
  if e['role']!='protected':groups.append({'id':gid,'role':e['role'],'source':text,'fragments':[{'id':gid,'page':e['source_page'],'block':int(gid.split('B')[1]),'bbox':box,'source_text':text}],'source_group_confirmation':item['confirmation'],'source_join_evidence':{'original_raw_blocks':item['raw_blocks'],'confirmation':item.get('join_confirmation'),'source_plan':ref(plan_path)}})
 # Reject explicit protection mistakes before rendering, using the declared boxes.
 protected=[e for e in accepted['roles']if e['role']=='protected']
 for e in accepted['roles']:
  if e['role']=='protected':continue
  for other in protected:
   if e['source_page']==other['source_page'] and any((fitz.Rect(e[k])&fitz.Rect(other['source_bbox'])).get_area()>.001 for k in ('source_bbox','original_layout_bbox')):
    raise ValueError('scan_plan_protected_overlap:'+e['id']+':'+other['id'])
 output.mkdir(parents=True)
 def save(n,v):
  q=output/n;q.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');return q
 adapted['manual_input_assistance']={'original_RAW_OCR':ref(ocr),'reviewed_source_plan':ref(plan_path),'materializer_code':ref(__file__),'automatic_paragraph_recognition':False}
 ap=save('GROUPED_OCR.json',adapted);gp=save('SOURCE_GROUPS.json',{'source':sr,'rawOCR':ref(ap),'complete_semantic_scope_confirmed':True,'groups':groups,'OCR_edits':[],'blank_page_confirmations':plan.get('blank_page_confirmations',[])})
 accepted.update(source=sr,rawOCR=ref(ap),source_role_confirmation=plan.get('source_confirmation')or'per-region explicit source-plan confirmations')
 rp=save('ROLES_CONFIRMED.json',accepted);receipt=save('MATERIALIZATION_RECEIPT.json',{'source':sr,'original_rawOCR':ref(ocr),'source_plan':ref(plan_path),'materializer_code':ref(__file__),'grouped_OCR':ref(ap),'groups':ref(gp),'roles':ref(rp),'raw_blocks':len(seen),'regions':len(records),'groups_count':len(groups),'explicit_confirmations':len(records),'explicit_join_confirmations':sum(len(item['raw_blocks'])>1 for _,item,_,_ in records),'geometry_rows':geometry_rows,'word_wrap_joins':joins,'automatic_grouping':False,'human_acceptance':False,'strict_delivery':False})
 return {'ocr':ap,'groups':gp,'roles':rp,'receipt':receipt}

def prepare_scan(source,ocr,output,*,groups_path=None,roles_path=None,targets_path=None,font_path=None,review_path=None,ink_path=None,raw_targets_path=None,reuse_path=None,source_plan_path=None,draft_source_plan=False,max_pages=5):
 """从已审完整源组准备既有trial；源语义分组与审校不自动晋升。"""
 from scanned_raster.schema import validate_scan_region
 from stable_page_raster import stable_get_pixmap
 reuse_evidence=None;source_plan_evidence=None
 if draft_source_plan:
  if source_plan_path is None or ocr is None or any(v is not None for v in (reuse_path,groups_path,roles_path,targets_path,font_path,review_path,ink_path)):raise ValueError('scan_plan_draft_requires_only_raw_source_seed')
  result=materialize_source_plan(source,ocr,source_plan_path,output,max_pages=max_pages,draft_only=True)
  rt={v['id']:v['text']for v in json.loads(Path(raw_targets_path).read_text())['translations']}if raw_targets_path else{}
  packet={'source':ref(source),'original_rawOCR':ref(ocr),'draft_plan':ref(result['draft']),'raw_targets_ref':ref(raw_targets_path)if raw_targets_path else None,'items':[{'id':gid,'complete_source':text,'raw_target':rt.get(gid),'current_complete_target':None,'semantic_review':'UNREVIEWED'}for gid,item,text,box in result['records']if item['role']!='protected'],'join_proposals':result['joins'],'source_group_role_geometry_confirmations':'ALL_UNCONFIRMED','human_acceptance':False,'strict_delivery':False}
  (Path(output)/'SOURCE_TARGET_REVIEW_PACKET.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n')
  return {'status':'SOURCE_PLAN_DRAFT_REQUIRES_ALL_CONFIRMATIONS','source':ref(source),'draft_plan':ref(result['draft']),'automatic_grouping':False,'model_calls':0,'human_accepted':False,'strict_delivery':False}
 if source_plan_path is not None:
  if reuse_path is not None or groups_path is not None or roles_path is not None:raise ValueError('scan_plan_conflicting_prepared_inputs')
  if ocr is None or Path(output).exists():raise ValueError('scan_plan_rawOCR_and_new_output_required')
  companion=Path(output).with_name(Path(output).name+'.source-inputs')
  material=materialize_source_plan(source,ocr,source_plan_path,companion,max_pages=max_pages)
  ocr,groups_path,roles_path=material['ocr'],material['groups'],material['roles'];source_plan_evidence=ref(material['receipt'])
 if reuse_path is not None:
  paths,reuse_evidence=reused_preparation_inputs(source,reuse_path,dict(ocr=ocr,groups=groups_path,roles=roles_path,targets=targets_path,font=font_path,review=review_path,ink=ink_path,raw_targets=raw_targets_path))
  ocr,groups_path,roles_path,targets_path,font_path,review_path,ink_path,raw_targets_path=[paths[k] for k in ('ocr','groups','roles','targets','font','review','ink','raw_targets')]
  source_plan_evidence=reuse_evidence.get('source_plan_materialization_ref')
 if ocr is None:raise ValueError('scan_prepare_OCR_or_reuse_required')
 source,ocr,output=map(Path,(source,ocr,output));raw=json.loads(ocr.read_text());sr=ref(source)
 if output.exists():raise ValueError('scan_prepare_requires_new_output')
 with fitz.open(source)as doc:
  if not 1<=len(doc)<=max_pages<=20:raise ValueError('scan_prepare_page_limit')
  dims=[(p.rect.width,p.rect.height)for p in doc]
  for p in doc:
   cover=max([fitz.Rect(x['bbox']).get_area()/p.rect.get_area()for x in p.get_image_info()]+[0]);visible=sum(len(s['chars'])for s in p.get_texttrace()if s['type']==0)
   if cover<.85 or visible>=30:raise ValueError('scan_prepare_requires_real_scan_not_native_or_mixed')
 proposal=propose(raw,dims);proposal.update(source=sr,rawOCR=ref(ocr),code=ref(__file__))
 supplied=[groups_path,roles_path,targets_path,font_path,review_path];complete=all(p is not None for p in supplied)
 source_plan_only=source_plan_path is not None and all(p is None for p in (targets_path,font_path,review_path))
 if any(p is not None for p in supplied)and not complete and not source_plan_only:raise ValueError('scan_prepare_complete_reviewed_inputs_required')
 gd=None;accepted=None;targets={};byfrag={}
 if complete:
  gd=json.loads(Path(groups_path).read_text());accepted=json.loads(Path(roles_path).read_text())
  if gd.get('source')!=sr or gd.get('complete_semantic_scope_confirmed')is not True:raise ValueError('scan_prepare_complete_source_groups_not_confirmed')
  if accepted.get('source')!=sr or not accepted.get('source_role_confirmation'):raise ValueError('scan_prepare_source_roles_not_confirmed')
  if accepted.get('rawOCR')!=ref(ocr):raise ValueError('scan_prepare_OCR_identity_changed')
  expected={r['id']for r in proposal['roles']}
  if {r['id']for r in accepted['roles']}!=expected or len(accepted['roles'])!=len(expected):raise ValueError('scan_prepare_role_scope_changed')
  ids=set();edits=gd.get('OCR_edits',[]);role_by_id={r['id']:r['role']for r in accepted['roles']}
  for g in gd['groups']:
   if not g.get('source_group_confirmation')or not g.get('fragments')or g['id']in ids:raise ValueError('scan_prepare_ambiguous_complete_group')
   ids.add(g['id']);joined=[]
   for f in g['fragments']:
    fid=f['id'];pi,bi=f['page']-1,f['block']
    if fid in byfrag or fid!=f'P{pi+1}B{bi}':raise ValueError('scan_prepare_fragment_identity_or_duplicate')
    b=raw['pages'][pi][bi];text=''.join(x.get('content','')for x in b.get('content',[]));declared=f['source_text']
    if ''.join(text.split())!=''.join(declared.split())and not any(e.get('id')in {fid,g['id']}and e.get('before')==text and e.get('after')==declared and e.get('source_actual_evidence')for e in edits):raise ValueError('scan_prepare_unbound_OCR_source_edit')
    if f.get('bbox')!=b['bbox']:raise ValueError('scan_prepare_fragment_geometry_changed')
    if g.get('role')!=role_by_id.get(fid):raise ValueError('scan_prepare_group_source_role_changed')
    byfrag[fid]=g;joined.append(declared)
   if ''.join(' '.join(joined).split())!=''.join(g['source'].split())and not g.get('source_join_evidence'):raise ValueError('scan_prepare_source_join_requires_evidence')
  if set(byfrag)!={r['id']for r in accepted['roles']if r['role']!='protected'}:raise ValueError('scan_prepare_translatable_source_coverage')
  ts=json.loads(Path(targets_path).read_text())['translations'];targets={r['id']:r['text']for r in ts}
  if set(targets)!=ids or len(ts)!=len(ids)or any(not isinstance(t,str)or not t.strip()for t in targets.values()):raise ValueError('scan_prepare_target_group_coverage')
  blank={p['page']for p in proposal['complete_page_inventory']if p['ocr_region_count']==0}
  if blank-set(gd.get('blank_page_confirmations',[])):raise ValueError('scan_prepare_blank_page_confirmation_required')
 output.mkdir(parents=True)
 def save(n,v):
  p=output/n;p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');return p
 pp=save('STRUCTURE_PROPOSAL.json',proposal);images=[]
 with fitz.open(source)as doc:
  for i,p in enumerate(doc,1):
   q=output/f'source_p{i}.png';pix=stable_get_pixmap(p,matrix=fitz.Matrix(2,2),alpha=False);pix.save(q);del pix;images.append(ref(q))
 if not complete:
  if source_plan_only:
   confirmed=json.loads(Path(groups_path).read_text());raw_targets={v['id']:v['text']for v in json.loads(Path(raw_targets_path).read_text())['translations']}if raw_targets_path else{}
   save('SOURCE_PLAN_INPUTS.json',{'source':sr,'original_rawOCR':json.loads(Path(source_plan_path).read_text())['rawOCR'],'grouped_OCR':ref(ocr),'groups':ref(groups_path),'roles':ref(roles_path),'materialization_ref':source_plan_evidence})
   save('SOURCE_TARGET_REVIEW_PACKET.json',{'source':sr,'page_images':images,'groups':ref(groups_path),'raw_targets_ref':ref(raw_targets_path)if raw_targets_path else None,'items':[{'id':g['id'],'complete_source':g['source'],'raw_target':raw_targets.get(g['id']),'current_complete_target':None}for g in confirmed['groups']],'semantic_review':'REQUIRED; source plan does not accept RAW','human_acceptance':False,'strict_delivery':False})
   result={'status':'REVIEWED_SOURCE_MATERIALIZED_TARGET_REVIEW_REQUIRED','source':sr,'materialization_ref':source_plan_evidence,'groups':len(confirmed['groups']),'automatic_semantic_grouping':False,'model_calls':0};save('PREPARATION_RECEIPT.json',result);return result
  draft=[]
  for r in proposal['roles']:
   if r['role']=='protected':continue
   pi=r['source_page']-1;bi=int(r['id'].split('B')[1]);b=raw['pages'][pi][bi];text=''.join(x.get('content','')for x in b.get('content',[]))
   draft.append({'id':r['id'],'source':text,'role':r['role'],'fragments':[{'id':r['id'],'page':pi+1,'block':bi,'bbox':b['bbox'],'source_text':text}],'source_group_confirmation':None})
  save('SOURCE_GROUPS.draft.json',{'source':sr,'rawOCR':ref(ocr),'complete_semantic_scope_confirmed':False,'source_confirmation':None,'groups':draft,'OCR_edits':[],'blank_page_confirmations':[]})
  result={'status':'SOURCE_ONLY_PROPOSAL_REQUIRES_CONFIRMATION','source':sr,'rawOCR':ref(ocr),'proposal':ref(pp),'page_images':images,'automatic_semantic_grouping':False,'model_calls':0};save('PREPARATION_RECEIPT.json',result);return result
 roles=copy.deepcopy(accepted['roles']);rp=save('ROLE_BINDING.json',{'source':sr,'proposal':ref(pp),'accepted_input':ref(roles_path),'roles':roles,'complete_page_inventory':proposal['complete_page_inventory'],'review_required':True})
 ip=save('FROZEN_PREPARATION_INPUTS.json',{'source':sr,'rawOCR':ref(ocr),'groups':ref(groups_path),'roles':ref(roles_path),'targets':ref(targets_path),'semantic_review':ref(review_path),'font':ref(font_path),'ink_protection':ref(ink_path)if ink_path else None,'raw_targets':ref(raw_targets_path)if raw_targets_path else None,'source_plan_materialization_ref':source_plan_evidence});rows=[]
 if reuse_evidence is not None:save('REUSE_RECEIPT.json',reuse_evidence)
 if source_plan_evidence is not None:save('SOURCE_PLAN_RECEIPT.json',{'materialization_ref':source_plan_evidence,'automatic_grouping':False,'semantic_acceptance':False})
 for e in roles:
  pi=e['source_page']-1;bi=int(e['id'].split('B')[1]);b=raw['pages'][pi][bi];w,h=dims[pi];g=byfrag.get(e['id']);protected=e['role']=='protected';box=e['source_bbox'];poly=[[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]];lines=[{'bbox':[v*[w,h,w,h][j]for j,v in enumerate(l['bbox'])]}for l in b.get('lines',[])];text=''.join(x.get('content','')for x in b.get('content',[]))
  r={'region_id':e['id'],'page':pi+1,'bbox':box,'source_bbox':box,'reading_order':bi,'source_page_idx':pi,'polygon':poly,'layout_role':'text','ocr_text':text,'normalized_text':text,'confidence':None,'confidence_source':'upstream_not_provided','engine':'mineru','engine_version':raw.get('engine_version','upstream_not_provided'),'source_pdf_sha256':sr['sha256'],'source_page_image_sha256':images[pi]['sha256'],'config_sha256':ref(ip)['sha256'],'preprocess':{'none':True},'translation_group_id':g['id']if g else e['id'],'status':'protected'if protected else'translated','in_destroke_mask':not protected,'mask_geometry':{'type':'polygon','points':poly},'mask_overlap_ratio':0,'source_line_evidence':lines,'source_line_height':statistics.median([l['bbox'][3]-l['bbox'][1]for l in lines])if lines else None,'translation':None if protected else targets[g['id']],'translation_source':ref(targets_path),'semantic_review':ref(review_path),'original_layout_bbox':e['original_layout_bbox']}
  if e['role']=='body':r.update(typography_class='body',chinese_uniform_body_indent_pt=e.get('first_line_indent_pt',0),paragraph_band_index=1 if len(g['fragments'])>1 and e['id']!=g['fragments'][0]['id']else 0)
  if protected:r['protected_reason']=e.get('derivation','source-reviewed protected role')
  errors=validate_scan_region(r)
  if errors:raise ValueError('scan_prepare_region_schema:'+str(errors))
  rows.append(r)
 reg=output/'regions.jsonl';reg.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n'for r in rows));contract={'schema_version':1,'policy':'explicit_source_roles_and_anchors_v1','kind':'scan','source_pdf_ref':sr,'role_evidence':ref(rp),'regions_ref':ref(reg),'font_ref':ref(font_path),'code_refs':__import__('runtime_source_manifest').implementation_refs(),'typography':accepted['parameters']['typography'],'preparation_inputs_ref':ref(ip),'source_scale_basis':'declared finite same-class profile; source/actual review stillrequired'}
 if source_plan_evidence is not None:contract['source_plan_materialization_ref']=source_plan_evidence
 if ink_path:
  ink=json.loads(Path(ink_path).read_text())
  if ink['source']!=sr:raise ValueError('scan_prepare_ink_source_changed')
  contract['source_ink_protection_ref']=ref(ink_path)
 cross=[g for g in gd['groups']if len(g['fragments'])>1]
 if cross:
  fp=save('SCAN_FLOW.json',{'source':sr,'groups':[{'id':g['id'],'region_ids':[f['id']for f in g['fragments']],'target_text':targets[g['id']],'boundary_evidence':g['source_group_confirmation']}for g in cross],'blank_source_pages':[{'page':n,'image_ref':images[n-1],'review_ref':ref(review_path)}for n in gd.get('blank_page_confirmations',[])]});contract['scan_semantic_flow_ref']=ref(fp)
 cp=save('TRIAL_CONTRACT.json',contract);rt={r['id']:r['text']for r in json.loads(Path(raw_targets_path).read_text())['translations']}if raw_targets_path else {}
 save('SOURCE_TARGET_REVIEW_PACKET.json',{'source':sr,'page_images':images,'rawOCR':ref(ocr),'groups':ref(groups_path),'raw_targets_ref':ref(raw_targets_path)if raw_targets_path else None,'current_targets_ref':ref(targets_path),'items':[{'id':g['id'],'complete_source':g['source'],'source_fragments':g['fragments'],'raw_target':rt.get(g['id']),'current_complete_target':targets[g['id']],'numeric_relationships':'reviewer must read source image/full paragraph; unreadable=UNKNOWN; summaries not gold'}for g in gd['groups']],'actual_PDFs':'bind current saved mono/dual SHA during existing independent review; no automatic semantic PASS'})
 result={'status':'PREPARED_NOT_QUALITY_ACCEPTED','source':sr,'contract':ref(cp),'groups':len(gd['groups']),'regions':len(rows),'role_manual_overrides':sum(r['role']!=next(p['role']for p in proposal['roles']if p['id']==r['id'])for r in roles),'geometry_overrides':sum(r['source_bbox']!=next(p['source_bbox']for p in proposal['roles']if p['id']==r['id'])or r['original_layout_bbox']!=next(p['original_layout_bbox']for p in proposal['roles']if p['id']==r['id'])for r in roles),'explicit_ink_boxes':len(json.loads(Path(ink_path).read_text())['assets'])if ink_path else 0,'Y_overrides':len([r for r in roles if r.get('y_shift_pt',0)]),'OCR_edit_groups':len(gd.get('OCR_edits',[])),'model_calls':0,'automatic_semantic_grouping':False};save('PREPARATION_RECEIPT.json',result);return result

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--ocr',type=Path);parser.add_argument('--output',type=Path);parser.add_argument('--prepare-directory',type=Path);parser.add_argument('--reuse-preparation',type=Path);parser.add_argument('--source-plan',type=Path);parser.add_argument('--draft-source-plan',action='store_true')
 for n in ('groups','roles','targets','font','semantic-review','ink-protection','raw-targets'):parser.add_argument('--'+n,type=Path)
 parser.add_argument('--max-pages',type=int,default=5);args=parser.parse_args()
 if args.prepare_directory:
  print(json.dumps(prepare_scan(args.source,args.ocr,args.prepare_directory,groups_path=args.groups,roles_path=args.roles,targets_path=args.targets,font_path=args.font,review_path=args.semantic_review,ink_path=args.ink_protection,raw_targets_path=args.raw_targets,reuse_path=args.reuse_preparation,source_plan_path=args.source_plan,draft_source_plan=args.draft_source_plan,max_pages=args.max_pages),ensure_ascii=False));return
 if args.ocr is None or args.reuse_preparation is not None or args.source_plan is not None or args.draft_source_plan:parser.error('proposal requires --ocr; prepared input options require --prepare-directory')
 if not args.output:parser.error('--output or --prepare-directory required')
 with fitz.open(args.source) as doc:
  assert 1<=len(doc)<=20,'finite proposal page cap'
  result=propose(json.loads(args.ocr.read_text()),[(p.rect.width,p.rect.height) for p in doc])
 result.update(source=ref(args.source),rawOCR=ref(args.ocr),code=ref(__file__))
 with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
 print(json.dumps({'status':'proposed_NOT_accepted','regions':len(result['roles']),'role_counts':{role:sum(v['role']==role for v in result['roles']) for role in ['body','heading','single_line_metadata','protected']}}))
if __name__=='__main__':main()
