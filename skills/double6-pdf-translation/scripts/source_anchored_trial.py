"""显式源角色和锚点的有限试用写回；不推断源结构，不授予质量接受。"""
from pathlib import Path
import argparse,copy,hashlib,json,math,os
import fitz

POLICY='explicit_source_roles_and_anchors_v1'
ROLES={'body','heading','single_line_metadata','protected'}
def ref(path):
 p=Path(path).resolve();return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def bound(row):
 p=Path(row['path']);assert ref(p)==row,'trial_frozen_identity_changed';return p
def load(row):return json.loads(bound(row).read_text())
def role_policy(contract,records,id_key):
 evidence=load(contract['role_evidence']);assert evidence['source']==contract['source_pdf_ref'],'trial_role_source_changed'
 roles={r['id']:r for r in evidence['roles']};assert len(roles)==len(evidence['roles'])and set(roles)=={r[id_key]for r in records},'trial_role_scope_incomplete'
 classes=contract['typography'];active=[r for r in evidence['roles']if r['role']!='protected'];shifted=[]
 for r in evidence['roles']:
  assert r['role']in ROLES and isinstance(r['source_page'],int)and isinstance(r['source_column'],int)and r['source_page']>0 and r['source_column']>0,'trial_source_role_or_anchor_missing'
  dy=r.get('y_shift_pt',0);assert isinstance(dy,(int,float))and not isinstance(dy,bool)and math.isfinite(dy)and abs(dy)<=9,'trial_y_shift_bound'
  if dy:shifted.append(r)
  if r['role']=='protected':continue
  class_id=r.get('typography_class',r['role']);p=classes[class_id];assert p.get('source_role',r['role'])==r['role'],'trial_class_source_role_changed';fs,step=p['font_size_pt'],p['baseline_step_pt'];assert all(isinstance(x,(int,float))and not isinstance(x,bool)and math.isfinite(x)for x in [fs,step])and 3<=fs<=40 and 1<=step/fs<=3,'trial_typography_invalid'
 body=[r for r in active if r['role']=='body'];body_shifted=[r for r in shifted if r['role']=='body'];heading_shifted=[r for r in shifted if r['role']=='heading']
 assert all(r['role'] in {'body','heading'} for r in shifted)and len(body_shifted)<=math.floor(len(body)*.2),'trial_y_shift_scope'
 assert len(heading_shifted)<=1 and all(abs(r['y_shift_pt'])<=3 and isinstance(r.get('source_rule_clearance_evidence'),dict) and r['source_rule_clearance_evidence'] for r in heading_shifted),'trial_heading_rule_clearance_evidence'
 return roles

def scan_regions(contract,rows):
 rows=copy.deepcopy(rows);roles=role_policy(contract,rows,'region_id')
 for r in rows:
  e=roles[r['region_id']];role=e['role'];assert r['page']==e['source_page']and max(abs(a-b)for a,b in zip(r['source_bbox'],e['source_bbox']))<.001,'trial_scan_source_anchor_changed'
  if role=='protected':assert r['status']=='protected';continue
  p=contract['typography'][role];r['uniform_typography']={'class_id':role,'member_ids':[x['id']for x in roles.values()if x['role']==role],'font_size_pt':p['font_size_pt'],'baseline_step_pt':p['baseline_step_pt'],'source_ref':contract['source_pdf_ref'],'role_evidence_ref':contract['role_evidence']}
  dy=e.get('y_shift_pt',0);box=list(r.get('original_layout_bbox')or r['source_bbox']);box[1]+=dy;box[3]+=dy;r['original_layout_bbox']=box
  r['trial_alignment']=e.get('alignment')
  if role=='heading':
   indent=e.get('first_line_indent_pt',0)
   assert isinstance(indent,(int,float))and not isinstance(indent,bool)and math.isfinite(indent)and abs(indent)<=80,'trial_heading_source_indent_bound'
   r['trial_heading_indent_pt']=indent
  if role=='single_line_metadata':
   indent=e.get('first_line_indent_pt',0)
   assert isinstance(indent,(int,float))and not isinstance(indent,bool)and math.isfinite(indent)and abs(indent)<=80,'trial_metadata_source_indent_bound'
   r['trial_metadata_indent_pt']=indent
  r['trial_source_policy']={'policy':POLICY,'source_role':role,'source_page':e['source_page'],'source_column':e['source_column'],'y_shift_pt':dy,'source_bbox_unchanged':True}
 return rows

def native_plan(contract,plan):
 plan=copy.deepcopy(plan);roles=role_policy(contract,plan['items'],'id');plan.update(layout_policy='source_anchored',maximum_drift_pt=0,preserve_complete_source_page=True)
 # Fixed items use explicit source columns; no continuous packing or balancing.
 plan['frames']=[{'page':i+1,'column':1,'bbox':[0,0,t['width'],t['height']]}for i,t in enumerate(plan['templates'])]
 for item in plan['items']:
  e=roles[item['id']];assert e['role']!='protected','trial_native_protected_use_template';p=contract['typography'][e.get('typography_class',e['role'])]
  item.update(font_size=p['font_size_pt'],lineheight=p['baseline_step_pt']/p['font_size_pt'],fixed=True,fixed_x=e['source_x'],anchor={'page':e['source_page'],'baseline_y':e['source_baseline']+e.get('y_shift_pt',0)},source_column=e['source_column'])
 return plan

def synthetic_prepare(base,item):
 original,row=base(item);angle=item.get('synthetic_italic_degrees')
 if angle is None:return original,row
 assert item['kind'] in ['heading','paragraph'] and row['line_records'] and 0<angle<=20,'trial_synthetic_italic_scope'
 if len(row['line_records'])!=1 or item['kind']!='heading':
  shear=math.tan(math.radians(angle));font=fitz.Font(fontfile=item['font']);fresh=fitz.open();page=fresh.new_page(width=item['width'],height=original[0].rect.height)
  for span in original[0].get_texttrace():
   for char in span['chars']:
    point=fitz.Point(*char[2]);pivot=fitz.Point(0,point.y)
    page.insert_text(point,chr(char[0]),fontname='PTSyntheticItalic',fontfile=item['font'],fontsize=span['size'],morph=(pivot,fitz.Matrix(1,0,shear,1,0,0)),color=span['color'])
  fresh[0].set_cropbox(fitz.Rect(0,0,min(item['width'],fresh[0].rect.width),min(row['height'],fresh[0].rect.height)));original.close();row['synthetic_italic']={'degrees':angle,'real_italic_font':False,'scope':'all saved line glyph origins preserved'};return fresh,row
 fs=item['font_size'];baseline=row['line_records'][0]['baseline'];shear=math.tan(math.radians(angle));font=fitz.Font(fontfile=item['font']);xpad=max(0,-font.descender*fs*shear)+.05
 fresh=fitz.open();page=fresh.new_page(width=item['width'],height=original[0].rect.height);point=fitz.Point(xpad,baseline);page.insert_text(point,item['expected_text'],fontname='PTSyntheticItalic',fontfile=item['font'],fontsize=fs,morph=(point,fitz.Matrix(1,0,shear,1,0,0)),color=(0,0,0));fresh[0].set_cropbox(fitz.Rect(0,0,min(item['width'],fresh[0].rect.width),min(row['height'],fresh[0].rect.height)));original.close();row['synthetic_italic']={'degrees':angle,'real_italic_font':False};return fresh,row

def render(contract_path,output):
 contract=json.loads(Path(contract_path).read_text());assert contract['policy']==POLICY and contract['kind']in['scan','native'],'trial_contract_policy';source=bound(contract['source_pdf_ref']);font=bound(contract['font_ref'])
 for dep in contract.get('code_refs',[]):bound(dep)
 for dep in contract.get('additional_font_refs',[]):bound(dep)
 out=Path(output);out.mkdir(parents=True,exist_ok=False)
 with fitz.open(source)as d:assert 1<=len(d)<=20,'trial_input_page_limit'
 if contract['kind']=='scan':
  original=[json.loads(l)for l in bound(contract['regions_ref']).read_text().splitlines()];rows=scan_regions(contract,original);(out/'regions.frozen.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n'for r in rows));os.environ['PAPER_TRANSLATION_SCANNED_CJK_FONT']=str(font)
  import scanned_raster.pipeline as pipeline
  base=pipeline._render_text_style;original_insert=pipeline._insert_fitted_textbox
  class_fonts={role:fitz.Font(fontfile=str(bound(policy['font_ref'])))for role,policy in contract['typography'].items()if policy.get('font_ref')}
  from scan_semantic_flow import prepare_scan_flows
  flows,banks,flow_reports=prepare_scan_flows(contract,rows,font,original_insert,bound,out)
  active={}
  def style(region,text,*,page_width):
   active['role']=region['trial_source_policy']['source_role']
   active['region_id']=region['region_id']
   text,result=base(region,text,page_width=page_width)
   if region['trial_source_policy']['source_role']in {'single_line_metadata','heading'}:
    result.update(first_line_indent_pt=region.get('trial_heading_indent_pt',region.get('trial_metadata_indent_pt',0)),first_line_indent_em=0)
   if 'chinese_uniform_body_indent_pt'in region:
    assert region['trial_source_policy']['source_role']=='body','trial_metadata_body_indent'
    result.update(first_line_indent_pt=float(region['chinese_uniform_body_indent_pt']),align=0)
   if region.get('trial_alignment') is not None:
    result['align']={'left':0,'center':1,'right':2,'justify':3}[region['trial_alignment']]
   return text,result
  def insert(page,rect,text,**kwargs):
   if active.get('region_id') in flows:
    bank,place,size=flows[active['region_id']]
    from ink_preserving_copy import copy_text_with_true_ink
    place['actual_copy']=copy_text_with_true_ink(page,bank,0,place['bank_clip'],place['destination'])
    return size,0.
   if active.get('role')in class_fonts:kwargs['font_metrics']=class_fonts[active['role']]
   return original_insert(page,rect,text,**kwargs)
  pipeline._render_text_style=style;pipeline._insert_fitted_textbox=insert
  ink=[]
  if contract.get('source_ink_protection_ref'):
   evidence=load(contract['source_ink_protection_ref']);assert evidence['source']==contract['source_pdf_ref'],'trial_ink_source_changed';ink=evidence['assets']
  try:pipeline._render_translated_pdf(source,out/'page.mono.pdf',rows,dpi=144,source_ink_protection=ink)
  finally:
   pipeline._render_text_style=base;pipeline._insert_fitted_textbox=original_insert
   for bank in banks:bank.close()
  (out/'SEMANTIC_FLOW_REPORT.json').write_text(json.dumps(flow_reports,ensure_ascii=False,indent=2)+'\n')
  (out/'rendered_regions.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n'for r in rows));assert all(r.get('writeback_status')=='translated_text_committed'for r in rows if r.get('status')=='translated'),'trial_incomplete_writeback'
 else:
  import adaptive_document_renderer as renderer
  plan=native_plan(contract,load(contract['native_plan_ref']));base=renderer.prepare_html_item;renderer.prepare_html_item=lambda item:synthetic_prepare(base,item)
  try:m=renderer.render_plan(plan,out/'page.mono.pdf')
  finally:renderer.prepare_html_item=base
  (out/'RENDER_MANIFEST.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
 from build_bilingual_pdf import build_en_left_zh_right_pdf_pypdf
 dual=build_en_left_zh_right_pdf_pypdf(source,out/'page.mono.pdf',out/'page.dual.pdf');(out/'DUAL_MANIFEST.json').write_text(json.dumps(dual,ensure_ascii=False,indent=2)+'\n');result={'status':'candidate','policy':POLICY,'contract':ref(contract_path),'source':ref(source),'font':ref(font),'mono':ref(out/'page.mono.pdf'),'dual':ref(out/'page.dual.pdf'),'new_OCR_MT_calls':0,'human_accepted':False,'strict_delivery':False,'input_adaptation':'explicit reviewed source roles/geometry and complete frozen targets remain required'};(out/'TRIAL_RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--contract',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(render(a.contract,a.output),ensure_ascii=False))
if __name__=='__main__':main()
