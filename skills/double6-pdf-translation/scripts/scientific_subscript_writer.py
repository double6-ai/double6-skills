"""将有源证据的 Unicode 下标改为真实字体的普通字符下标。"""
from io import BytesIO
import math,unicodedata
from pypdf.generic import ContentStream,DecodedStreamObject,FloatObject,ByteStringObject,ArrayObject,read_object
import fitz

POLICY={'id':'source_class_scientific_subscript_v1','maximum_glyphs':50000,'maximum_forms':128,
        'source_class_tolerance':.002,'normalized_precision':2,'saved_tolerance_pt':.001,'serialization_scalar_tolerance':.000001,
        'case_overrides_allowed':False,'preserve_unowned_glyphs':True}

def raw_string(v):
 if hasattr(v,'original_bytes'):v=v.original_bytes
 if not isinstance(v,bytes) or len(v)%2:raise ValueError('two_byte_identity_cid_required')
 return v

def codes(operands,op):
 if op==b'Tj':values=[operands[0]]
 elif op==b'TJ':values=operands[0]
 else:return []
 return [int.from_bytes(b[i:i+2],'big') for v in values if not isinstance(v,(int,float)) for b in [raw_string(v)] for i in range(0,len(b),2)]

def width(doc,font_xref,cid):
 kind,value=doc.xref_get_key(font_xref,'DescendantFonts')
 if kind!='array':raise ValueError('descendant_font_required')
 descendants=read_object(BytesIO(value.encode()),object())
 if len(descendants)!=1 or not hasattr(descendants[0],'idnum'):raise ValueError('one_indirect_descendant_required')
 descendant=descendants[0].idnum;kind,value=doc.xref_get_key(descendant,'W')
 if kind=='xref':
  value=doc.xref_object(int(value.split()[0]),compressed=True);kind='array' if value.startswith('[') else 'unsupported'
 if kind!='array':raise ValueError('explicit_widths_required')
 values=read_object(BytesIO(value.encode()),object());i=0
 while i<len(values):
  start=int(values[i]);next_=values[i+1]
  if isinstance(next_,list):
   if start<=cid<start+len(next_):return float(next_[cid-start])
   i+=2
  else:
   if start<=cid<=int(next_):return float(values[i+2])
   i+=3
 kind,v=doc.xref_get_key(descendant,'DW');return float(v) if kind!='null' else 1000.

def plan_classes(source,target,bindings):
 if max(len(source),len(target))>POLICY['maximum_glyphs'] or not bindings:raise ValueError('binding_budget_or_scope_missing')
 classes={};owned=set();out=[]
 for b in bindings:
  if set(b)!={'id','class','source_index','source_host_index','target_index','target_host_index'}:raise ValueError('explicit_binding_schema_required')
  s,sh=source[b['source_index']],source[b['source_host_index']];t,th=target[b['target_index']],target[b['target_host_index']]
  if b['target_index'] in owned:raise ValueError('duplicate_owned_glyph')
  owned.add(b['target_index'])
  literal=unicodedata.normalize('NFKC',chr(t['unicode']))
  if len(literal)!=1 or literal!=chr(s['unicode']) or not literal.isascii() or not literal.isalnum():raise ValueError('scientific_literal_mismatch')
  if t['direction']!=[1.,0.] or s['direction']!=[1.,0.] or th['direction']!=[1.,0.]:raise ValueError('horizontal_binding_required')
  ratio=s['size']/sh['size'];lower=(s['origin'][1]-sh['origin'][1])/sh['size']
  if not .3<ratio<.85 or not .05<lower<.8:raise ValueError('source_not_supported_subscript')
  canonical=(round(ratio,POLICY['normalized_precision']),round(lower,POLICY['normalized_precision']))
  if max(abs(ratio-canonical[0]),abs(lower-canonical[1]))>POLICY['source_class_tolerance']:raise ValueError('source_class_quantization_exceeds_tolerance')
  if b['class'] in classes and classes[b['class']]!=canonical:raise ValueError('source_class_not_uniform')
  classes[b['class']]=canonical
  out.append({**b,'unicode':ord(literal),'size':th['size']*canonical[0],
              'baseline':th['origin'][1]+th['size']*canonical[1],'source_ratio':ratio,'source_lower':lower})
 if any(b['target_host_index'] in owned for b in bindings):raise ValueError('host_owned_by_another_label')
 return {'policy':POLICY,'classes':classes,'changes':out}

def apply(document,page,target,plan):
 """绑定整条 Form 的真实 CID/GID 序列；混合 TJ 拆分后补偿字宽。"""
 if plan['policy']!=POLICY:raise ValueError('frozen_policy_required')
 forms=page.get_xobjects()
 if len(forms)>POLICY['maximum_forms']:raise ValueError('form_budget_exceeded')
 gids=[g['gid'] for g in target];owned={r['target_index']:r for r in plan['changes']};found={};rewrites=[]
 for f in forms:
  xref=f[0];raw=document.xref_stream(xref)
  if not raw or len(raw)>1024**2:continue
  font_resources={f'/{font[4]}':font[0] for font in page.get_fonts(full=True) if font[6]==xref}
  if not font_resources or any(document.xref_get_key(fx,'Encoding')!=('name','/Identity-H') for fx in font_resources.values()):continue
  stream=DecodedStreamObject();stream.set_data(raw);content=ContentStream(stream,None)
  cidseq=[cid for args,op in content.operations for cid in codes(args,op)]
  if not cidseq:continue
  hits=[i for i in range(len(gids)-len(cidseq)+1) if gids[i:i+len(cidseq)]==cidseq]
  relevant=[h for h in hits if set(range(h,h+len(cidseq))).intersection(owned)]
  if not relevant:continue
  if len(hits)!=1:raise ValueError('form_native_sequence_missing_or_ambiguous')
  start=hits[0]
  cursor=start;current_font=None;current_size=None;rise=0.;output=[];font_cache={}
  for args,op in content.operations:
   if op==b'Tf':current_font=str(args[0]);current_size=float(args[1])
   if op==b'Ts':rise=float(args[0])
   if op not in (b'Tj',b'TJ'):
    output.append((args,op));continue
   seq=codes(args,op);indices=list(range(cursor,cursor+len(seq)))
   if not set(indices).intersection(owned):output.append((args,op));cursor+=len(seq);continue
   if current_font not in font_resources or not current_size or rise!=0.:raise ValueError('owned_text_font_or_rise_unsupported')
   fx=font_resources[current_font]
   if document.xref_get_key(fx,'Encoding')!=('name','/Identity-H'):raise ValueError('identity_h_required')
   if fx not in font_cache:
    _,_,_,data=document.extract_font(fx)
    if not data:raise ValueError('real_embedded_font_required')
    font_cache[fx]=fitz.Font(fontbuffer=data)
   values=[args[0]] if op==b'Tj' else args[0]
   for value in values:
    if isinstance(value,(int,float)):output.append(([ArrayObject([value])],b'TJ'));continue
    raw=raw_string(value)
    for j in range(0,len(raw),2):
     cid=int.from_bytes(raw[j:j+2],'big');glyph=target[cursor]
     if abs(glyph['size']-current_size)>.001:raise ValueError('actual_font_size_disagrees')
     if cursor not in owned:output.append(([ByteStringObject(raw[j:j+2])],b'Tj'))
     else:
      row=owned[cursor];newcid=font_cache[fx].has_glyph(row['unicode'])
      if not newcid:raise ValueError('ordinary_character_missing_in_real_font')
      delta=row['baseline']-glyph['origin'][1]
      if abs(delta)>glyph['size']*.8:raise ValueError('baseline_change_exceeds_source_bound')
      output.extend([([args[0] if op==b'Tf' else next(a[0] for a,o in reversed(output) if o==b'Tf'),FloatObject(row['size'])],b'Tf'),
                     ([FloatObject(-delta)],b'Ts'),([ByteStringObject(newcid.to_bytes(2,'big'))],b'Tj'),
                     ([FloatObject(0)],b'Ts')])
      # Font name remains the existing resource. Restore before compensating text advance.
      output.append(([next(a[0] for a,o in reversed(output) if o==b'Tf'),FloatObject(current_size)],b'Tf'))
      adjustment=(width(document,fx,newcid)*row['size']-width(document,fx,cid)*current_size)/current_size
      output.append(([ArrayObject([FloatObject(adjustment)])],b'TJ'))
      found[cursor]={'font_xref':fx,'new_cid':newcid,'form_xref':xref,'before':glyph,**row}
     cursor+=1
  content.operations=output;rewrites.append((xref,content.get_data()))
 if set(found)!=set(owned):raise ValueError('complete_owned_form_coverage_required')
 for xref,raw in rewrites:document.update_stream(xref,raw)
 return list(found.values())

def verify(before,after,plan):
 if len(before)!=len(after):raise ValueError('saved_glyph_count_changed')
 owned={r['target_index']:r for r in plan['changes']};tol=POLICY['saved_tolerance_pt'];changed=[]
 for i,(a,b) in enumerate(zip(before,after)):
  if i in owned:
   row=owned[i]
   if b['unicode']!=row['unicode'] or b['font']!=a['font'] or b['color']!=a['color']:raise ValueError('saved_character_font_or_color_changed')
   if abs(b['size']-row['size'])>tol or abs(b['origin'][1]-row['baseline'])>tol or abs(b['origin'][0]-a['origin'][0])>tol:raise ValueError('saved_subscript_geometry_mismatch')
   changed.append(i)
  else:
   for k in ('unicode','gid','font','type'):
    if a[k]!=b[k]:raise ValueError('unowned_glyph_style_changed')
   for k in ('size','opacity'):
    if abs(a[k]-b[k])>POLICY['serialization_scalar_tolerance']:raise ValueError('unowned_glyph_style_changed')
   for k in ('color','direction'):
    if len(a[k])!=len(b[k]) or any(abs(x-y)>POLICY['serialization_scalar_tolerance'] for x,y in zip(a[k],b[k])):raise ValueError('unowned_glyph_style_changed')
   if any(abs(x-y)>tol for k in ('origin','bbox') for x,y in zip(a[k],b[k])):raise ValueError('unowned_glyph_position_changed')
 return {'changed_indices':changed,'unowned_glyphs_verified':len(before)-len(owned),'pass':True}
