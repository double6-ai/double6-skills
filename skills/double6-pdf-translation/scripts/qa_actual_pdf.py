"""逐页重新绑定成品实际字形；冻结快照的文字不能冒充新PDF测量。"""
from collections import defaultdict
import re
import fitz
from qa_source_contract import file_ref,text_digest
from native_line_spacing import glyphs,identity
from translation_coverage import normalized

def measure_unit_texts(target_ref, bindings, *, pages, maximum_glyphs=200000):
    if not pages or len(pages)>5 or pages!=sorted(set(pages)) or not 1<=maximum_glyphs<=500000:
        raise ValueError('actual_pdf_measurement_bounds')
    if file_ref(target_ref['path'])!=target_ref:raise ValueError('actual_pdf_identity_changed')
    if len({b['id'] for b in bindings})!=len(bindings):raise ValueError('actual_unit_duplicate')
    issues=[];units=[];used=set();total=0
    with fitz.open(target_ref['path']) as doc:
        if any(type(p) is not int or not 1<=p<=len(doc) for p in pages):raise ValueError('actual_pdf_page_scope')
        for page_number in pages:
            actual=glyphs(doc[page_number-1]);total+=len(actual)
            if total>maximum_glyphs:raise ValueError('actual_pdf_glyph_budget')
            by_key=defaultdict(list)
            for index,g in enumerate(actual):
                if g['type']!=3 and g.get('opacity',1)>0:by_key[identity(g)].append((index,g))
            for binding in bindings:
                for part_index,part in enumerate(binding['actual_placements']):
                    if part['page']!=page_number:continue
                    matched=[]
                    for expected in part['glyphs']:
                        candidates=by_key.get(identity(expected),[])
                        if len(candidates)!=1:
                            issues.append({'id':binding['id'],'page':page_number,'rule':'actual_target_glyph_missing_or_ambiguous'});continue
                        index,g=candidates[0];key=(page_number,index)
                        if key in used:issues.append({'id':binding['id'],'rule':'actual_target_glyph_duplicate_binding'})
                        used.add(key);matched.append(g)
                    units.append({'id':binding['id'],'part_index':part_index,'page':page_number,
                        'text':''.join(chr(g['unicode']) for g in matched),'glyphs':matched,
                        'placement':{k:v for k,v in part['placement'].items() if k!='glyphs'},
                        'matched_glyphs':len(matched),'expected_glyphs':len(part['glyphs'])})
    if file_ref(target_ref['path'])!=target_ref:raise ValueError('actual_pdf_changed_during_measurement')
    return {'target':target_ref,'pages':pages,'parts':units,'issues':issues,
            'status':'fail' if issues else 'pass','quality_pass':False,'visibility_proven':False,
            'scope':'实际绘制记录身份与位置；clip/遮挡及墨迹可见性仍需独立审查'}

def close_unit_texts(bindings, batch_reports, *, target_ref):
    issues=[];by_id=defaultdict(list);pages=[]
    for report in batch_reports:
        if report['target']!=target_ref:issues.append({'rule':'actual_text_batch_identity_changed'})
        pages+=report['pages'];issues+=report['issues']
        for part in report['parts']:by_id[part['id']].append(part)
    if len(set(pages))!=len(pages):issues.append({'rule':'actual_text_batch_duplicate_page'})
    texts={}
    for binding in bindings:
        parts=sorted(by_id.get(binding['id'],[]),key=lambda r:r['part_index'])
        if [p['part_index'] for p in parts]!=list(range(len(binding['actual_placements']))):
            issues.append({'id':binding['id'],'rule':'actual_target_part_missing_or_repeated'})
        actual=''.join(p['text'] for p in parts);texts[binding['id']]=actual
        expected=re.sub(r'\{(?:cite|aff):([^}]+)\}',r'\1',binding['target_text'])
        if normalized(actual)!=normalized(expected):issues.append({'id':binding['id'],'rule':'actual_target_complete_translation_missing'})
    return {'target':target_ref,'pages':sorted(set(pages)),'actual_texts':texts,'issues':issues,
            'status':'fail' if issues else 'pass','quality_pass':False}

def audit_target_content_roles(target_ref,bindings,units,*,pages,maximum_glyphs=200000):
    """整页可印刷文字逐字归属；真实像素、扫描文字和遮挡仍由视觉/OCR检查。"""
    if not pages or len(pages)>5 or pages!=sorted(set(pages)) or not 1<=maximum_glyphs<=500000:raise ValueError('target_content_role_batch_limits')
    if file_ref(target_ref['path'])!=target_ref:raise ValueError('target_content_role_identity_changed')
    expected=defaultdict(set)
    for binding in bindings:
        for part in binding['actual_placements']:
            for g in part['glyphs']:expected[part['page']].add(identity(g))
    issues=[];pending=[];records=[];total=0
    with fitz.open(target_ref['path']) as doc:
        for number in pages:
            if type(number)is not int or not 1<=number<=len(doc):raise ValueError('target_content_role_page_scope')
            native=[g for g in glyphs(doc[number-1]) if g['type']!=3 and g.get('opacity',1)>0 and not chr(g['unicode']).isspace()]
            total+=len(native)
            if total>maximum_glyphs:raise ValueError('target_content_role_glyph_budget')
            own=[g for g in native if identity(g) not in expected[number]]
            if own:
                text=''.join(chr(g['unicode']) for g in own);norm=normalized(text);literal=[]
                for unit in units:
                    source=unit['source_text']
                    # 仅完整源文字仍以未绑定的原生字形出现时裁决；单个科学符号不作英语残留。
                    if re.search(r'[A-Za-z]{4}',source) and normalized(source) in norm and re.search(r'[\u3400-\u9fff]',unit['target_text']):
                        literal.append(unit['id']);issues.append({'page':number,'id':unit['id'],'rule':'translated_source_text_still_present_in_target'})
                if not literal:pending.append({'page':number,'rule':'target_visible_text_without_content_role_binding','glyph_count':len(own)})
                records.append({'page':number,'unassigned_glyphs':len(own),'unassigned_text':text,'unassigned_text_sha256':text_digest(text),'literal_unit_ids':literal})
            else:records.append({'page':number,'unassigned_glyphs':0})
    if file_ref(target_ref['path'])!=target_ref:raise ValueError('target_content_role_pdf_changed_during_audit')
    return {'status':'fail' if issues else 'unverified' if pending else 'pass','issues':issues,'pending':pending,'pages':pages,'records':records,'quality_pass':False}
