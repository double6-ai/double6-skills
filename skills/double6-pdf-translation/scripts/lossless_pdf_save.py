"""采用 MuPDF 对象去重/Flate 保存候选；逐页核验，不授予独立接受。"""
from pathlib import Path
from io import BytesIO
import hashlib,math,inspect,json
import fitz
from pypdf.generic import read_object,IndirectObject,DictionaryObject,ArrayObject,ByteStringObject
from native_line_spacing import glyphs,reference
from stable_page_raster import stable_get_pixmap

POLICY={'id':'lossless_object_save_v1','maximum_pages':20,'maximum_glyphs_per_page':100000,
 'maximum_reference_depth':24,'pixel_dpi':144,'case_overrides_allowed':False,
 'parameters':{'garbage':4,'clean':False,'deflate':True,'deflate_images':True,'deflate_fonts':True,'no_new_id':True,'use_objstms':1,'preserve_metadata':True}}

def digest(value):return hashlib.sha256(value).hexdigest()

def save_candidate(input_path,output_path,expected_sha256):
 before=Path(input_path);after=Path(output_path)
 if after.exists() or before.resolve()==after.resolve():raise ValueError('fresh_distinct_candidate_required')
 if reference(before)['sha256']!=expected_sha256:raise ValueError('input_identity_changed')
 if not set(POLICY['parameters']).issubset(inspect.signature(fitz.Document.save).parameters):raise ValueError('runtime_save_profile_unsupported')
 with fitz.open(before)as document:
  if not document.is_pdf or document.needs_pass or document.is_encrypted or document.is_repaired:raise ValueError('unrepaired_unencrypted_pdf_required')
  if not 0<len(document)<=POLICY['maximum_pages']:raise ValueError('page_budget_exceeded')
  if document.get_sigflags()>0 or document.is_form_pdf:raise ValueError('signatures_or_forms_not_supported')
  document.save(after,**POLICY['parameters'])
 return {'before':reference(before),'after':reference(after),'before_bytes':before.stat().st_size,'after_bytes':after.stat().st_size,'quality_verified':False}

def save_plan(plan):
 """校验冻结计划及声明页数；调用者负责资源锁与随后完整验收。"""
 from jsonschema import Draft202012Validator
 schema=Path(__file__).resolve().parents[1]/'schemas/lossless-pdf-save.schema.json'
 Draft202012Validator(json.loads(schema.read_text())).validate(plan)
 with fitz.open(plan['input_path'])as document:
  if len(document)!=plan['expected_pages']:raise ValueError('declared_page_scope_changed')
 return save_candidate(plan['input_path'],plan['output_path'],plan['input_sha256'])

def primitive(value):
 if isinstance(value,dict):return {k:primitive(v)for k,v in value.items()if k!='xref'}
 if isinstance(value,(list,tuple,fitz.Rect,fitz.Point,fitz.Quad)):return [primitive(v)for v in value]
 if isinstance(value,float) and not math.isfinite(value):raise ValueError('finite_geometry_required')
 return value

def pdf_value(document,value,page_xrefs,active=None,depth=0):
 if depth>POLICY['maximum_reference_depth']:raise ValueError('annotation_reference_depth_exceeded')
 active=set()if active is None else active
 if isinstance(value,IndirectObject):
  if value.generation!=0:raise ValueError('unsupported_reference_generation')
  if value.idnum in page_xrefs:return ['page',page_xrefs[value.idnum]]
  if value.idnum in active:raise ValueError('cyclic_annotation_reference')
  raw=document.xref_object(value.idnum)
  return pdf_value(document,read_object(BytesIO(raw.encode()),object()),page_xrefs,active|{value.idnum},depth+1)
 if isinstance(value,DictionaryObject):return {str(k):pdf_value(document,v,page_xrefs,active,depth+1)for k,v in value.items()}
 if isinstance(value,ArrayObject):return [pdf_value(document,v,page_xrefs,active,depth+1)for v in value]
 if isinstance(value,ByteStringObject):return ['bytes',bytes(value).hex()]
 if isinstance(value,(int,float)):return float(value)
 if value.__class__.__name__=='NullObject':return None
 return str(value)

def annotations(document,page):
 pages={document.page_xref(i):i+1 for i in range(len(document))};out=[]
 for xref,kind,name in document.page_annot_xrefs(page.number):
  raw=document.xref_object(xref);value=read_object(BytesIO(raw.encode()),object())
  out.append({'kind':kind,'name':name,'dictionary':pdf_value(document,value,pages)})
 return out

def assets(document,page):
 fonts=set();images=set();forms=set();seen={}
 for row in page.get_fonts(full=True):
  xref=row[0]
  if xref not in seen:seen[xref]=digest(document.extract_font(xref)[3])
  fonts.add((*row[1:6],seen[xref]))
 for row in page.get_images(full=True):
  xref,mask=row[:2];images.add((tuple(row[2:8]),digest(document.xref_stream(xref)),digest(document.xref_stream(mask))if mask else None))
 for row in page.get_xobjects():forms.add((row[1],tuple(row[3]),digest(document.xref_stream(row[0]))))
 return {'fonts':sorted(fonts),'images':sorted(images,key=str),'forms':sorted(forms)}

def verify_page(before,after,page_number,dpi=None):
 if len(before)!=len(after) or not 1<=page_number<=len(before):raise ValueError('page_scope_mismatch')
 a,b=before[page_number-1],after[page_number-1]
 if any(getattr(a,k)!=getattr(b,k)for k in ['mediabox','cropbox','rect','rotation']):raise ValueError('page_geometry_changed')
 ga,gb=glyphs(a),glyphs(b)
 if len(ga)>POLICY['maximum_glyphs_per_page'] or ga!=gb:raise ValueError('actual_glyph_or_budget_changed')
 if [digest(before.xref_stream(x))for x in a.get_contents()]!=[digest(after.xref_stream(x))for x in b.get_contents()]:raise ValueError('decoded_content_stream_changed')
 aa,bb=assets(before,a),assets(after,b)
 if aa!=bb:raise ValueError('actual_asset_or_font_payload_changed')
 if annotations(before,a)!=annotations(after,b):raise ValueError('annotation_semantics_or_frame_changed')
 if primitive(a.get_links())!=primitive(b.get_links()):raise ValueError('reader_link_destination_changed')
 if primitive(a.get_drawings())!=primitive(b.get_drawings()):raise ValueError('vector_drawing_changed')
 dpi=POLICY['pixel_dpi']if dpi is None else dpi
 pa=stable_get_pixmap(a,dpi=dpi);ha=digest(pa.samples);size=(pa.width,pa.height,pa.n);del pa
 pb=stable_get_pixmap(b,dpi=dpi);hb=digest(pb.samples)
 if size!=(pb.width,pb.height,pb.n) or ha!=hb:raise ValueError('saved_page_pixels_changed')
 return {'page':page_number,'pass':True,'glyphs':len(ga),'actual_fonts':len(aa['fonts']),'actual_images':len(aa['images']),'forms':len(aa['forms']),'links':len(a.get_links()),'dpi':dpi,'pixel_sha256':ha,'font_image_and_form_payloads_equal':True,'normalized_full_annotation_fields_equal':True}

def verify_document_metadata(before,after):
 if len(before)!=len(after) or before.metadata!=after.metadata or before.get_xml_metadata()!=after.get_xml_metadata():raise ValueError('document_metadata_changed')
 if before.get_page_labels()!=after.get_page_labels() or primitive(before.get_toc(False))!=primitive(after.get_toc(False)):raise ValueError('document_navigation_changed')
 if before.embfile_names()!=after.embfile_names():raise ValueError('embedded_file_inventory_changed')
 for name in before.embfile_names():
  if before.embfile_get(name)!=after.embfile_get(name):raise ValueError('embedded_file_changed')
 return {'pass':True,'metadata_labels_toc_and_embedded_files_equal':True}
