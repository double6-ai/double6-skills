"""自然语言翻译覆盖门：源字形有归属不等于已有可见译文。"""
from __future__ import annotations
import re
import unicodedata

NATURAL_ROLES={'body','abstract','title','heading','subheading','caption','chart_label','table_text','metadata','footer','label','affiliation','equation_label','acknowledgements','license','prose'}
PROTECTED_ROLES={'identifier','scientific_identity','page_number','journal_brand','author_identity','bibliographic_record','layout_whitespace'}
UNIT_WORDS={'m','mm','cm','nm','µm','μm','kg','g','s','h','yr','l','Wh','kWh','GWh','mAh','Ah','V','kW','W','US','CE','Li','Li2CO3','CO2','gCO2','Rs','IntCapEx','CapEx','N','P','CR','Pa','kPa','MPa','GPa','bar','mbar','Hz','kHz','MHz','GHz','K','mol','mmol','MW','GW','J','kJ','MJ','kN','mN','T','mT','A','mA','C','ppm','Li6PS5Cl'}
def normalized(value):
 return ''.join(c for c in unicodedata.normalize('NFKC',value)if not c.isspace())

def _whole_identifier(source, context):
 """完整无协议头URL须有已核定标识语境；普通句段继续拒绝。"""
 token=source.strip()
 if re.fullmatch(r'(?:https?://\S+|www\.\S+|[\w.+-]+@[\w.-]+|(?:doi:)?10\.\d{4,9}/\S+)',token):
  return True
 return bool(isinstance(context,dict) and context.get('kind') in {'url','doi','identifier'} and
  re.fullmatch(r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,63}/\S+',token))

def assess_translation_coverage(elements,translations,*,declared_pages,expected_pages,
                                actual_targets=None,independent_role_review=False,
                                require_source_bindings=False, role_review_ref=None,
                                source_ref=None, inventory_ref=None, mixed_review_ref=None,
                                target_ref=None, standard_ref=None, producer_id=None,
                                authorized_reviewer_id=None, reviewer_authorization_ref=None):
 """elements须由完整源页清单生成；actual_targets是按单位绑定的实际字形文本。"""
 declared=set(declared_pages);expected=set(expected_pages);issues=[];covered=[];protected=[]
 if not declared or not declared<=expected:raise ValueError('coverage_page_scope')
 ids=[v['id']for v in elements]
 if len(ids)!=len(set(ids)):raise ValueError('duplicate_source_element')
 if {v['page']for v in elements}!=declared:issues.append({'rule':'source_page_inventory_incomplete'})
 units={v['id']:v for v in translations}
 if len(units)!=len(translations):raise ValueError('duplicate_translation_unit')
 from qa_mixed_source_treatment import audit_bound_mixed_treatment
 mixed=audit_bound_mixed_treatment(elements,translations,actual_targets,review_ref=mixed_review_ref,
  source_ref=source_ref,target_ref=target_ref,standard_ref=standard_ref,producer_id=producer_id,
  authorized_reviewer_id=authorized_reviewer_id,source_role_review_ref=role_review_ref,
  reviewer_authorization_ref=reviewer_authorization_ref,inventory_ref=inventory_ref)
 issues.extend(mixed["issues"]);issues.extend(mixed["pending"])
 mixed_ids=set(mixed["accepted_source_ids"])
 bindings={}
 if require_source_bindings:
  for u in translations:
   refs=[]
   for fragment in u.get('fragments',[]):
    own=[r['id']for r in fragment.get('source_line_refs',[])];refs+=own
    nested=fragment.get('source_fragments')
    if nested is not None:
     children=[r['id']for f in nested for r in f.get('source_line_refs',[])]
     if children!=own or len(children)!=len(set(children)):
      issues.append({'unit_id':u['id'],'rule':'nested_source_fragment_binding_inconsistent'})
   if not refs or len(refs)!=len(set(refs)):issues.append({'unit_id':u['id'],'rule':'source_line_binding_missing_or_duplicate'})
   bindings[u['id']]=set(refs)
 for e in elements:
  role=e.get('role');status=e.get('status');source=e.get('source_text','');key=e['id']
  if e['page']not in declared:raise ValueError('source_element_outside_scope')
  if key in mixed_ids:
   covered.append(key);continue
  if status=='protected':
   if role in NATURAL_ROLES or role not in PROTECTED_ROLES:
    issues.append({'id':key,'rule':'natural_language_protected_or_context_exemption'});continue
   if not e.get('reason'):
    issues.append({'id':key,'rule':'unproven_protection'});continue
   if role=='identifier'and not _whole_identifier(source,e.get('protection_context')):
    issues.append({'id':key,'rule':'identifier_exemption_includes_prose'});continue
   if role=='scientific_identity':
    words=re.findall(r'[A-Za-z]+\d*(?:[A-Za-z]+\d*)*',unicodedata.normalize('NFKC',source))
    if any(w not in UNIT_WORDS and len(w)>2 for w in words):
     issues.append({'id':key,'rule':'scientific_exemption_includes_natural_language'});continue
   protected.append(key);continue
  if status not in ('translate','translated')or role not in NATURAL_ROLES:
   issues.append({'id':key,'rule':'unresolved_source_role'});continue
  u=units.get(e.get('unit_id'));target=u.get('target_text','')if u else ''
  if require_source_bindings and key not in bindings.get(e.get('unit_id'),set()):
   issues.append({'id':key,'unit_id':e.get('unit_id'),'rule':'source_element_not_bound_to_translation'});continue
  if not target or not re.search(r'[\u3400-\u9fff]',target)or normalized(target)==normalized(source):
   issues.append({'id':key,'rule':'missing_or_unchanged_translation','unit_id':e.get('unit_id')});continue
  if actual_targets is not None:
   actual=actual_targets.get(e.get('unit_id'),'')
   target=re.sub(r'\{(?:cite|aff):([^}]+)\}',r'\1',target)
   if normalized(actual)!=normalized(target):
    issues.append({'id':key,'rule':'translation_not_completely_visible','unit_id':e.get('unit_id')});continue
  covered.append(key)
 if require_source_bindings:
  expected_ids={e['id']for e in elements if e.get('status')in('translate','translated')}|mixed_ids
  bound_ids={key for keys in bindings.values()for key in keys}
  if bound_ids!=expected_ids:issues.append({'rule':'translation_bindings_do_not_equal_complete_source_inventory','extra':sorted(bound_ids-expected_ids),'missing':sorted(expected_ids-bound_ids)})
 from qa_source_contract import validate_role_review
 role_audit=validate_role_review(elements,review_ref=role_review_ref,source_ref=source_ref,inventory_ref=inventory_ref)
 issues.extend(role_audit['issues'])
 if not independent_role_review:issues.append({'rule':'independent_role_review_required'})
 complete=bool(elements)and not issues
 return {'schema_version':1,'declared_pages':sorted(declared),'expected_pages':sorted(expected),
  'source_elements':len(elements),'translated_elements':len(covered),'protected_elements':len(protected),
  'unresolved_elements':len(elements)-len(covered)-len(protected),'issues':issues,
  'mixed_treatment_audit':mixed,'mixed_translated_elements':len(mixed_ids),
  'source_scope_translation_coverage_complete':complete,
  'full_document_translation_coverage_complete':complete and declared==expected,
  'actual_target_glyphs_verified':actual_targets is not None and complete,
  'independent_role_review':bool(independent_role_review)and role_audit['independent_role_review_verified'],
  'independent_role_review_declared':bool(independent_role_review),'role_evidence_audit':role_audit,
  'quality_pass':False,'scope':'覆盖门不替代语义、可见性、版式及独立质量接受；局部范围不能授予整册通过'}
