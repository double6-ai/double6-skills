"""保留独立登记的源 PDF 身份角色；隔离真实源字形后绑定唯一题名宿主页。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import fitz
import independent_latex as latex
from latex_editorial_revision import checked_ref, load, file_ref

PROTOCOL = 'source_bound_protected_pdf_role_v1'
AUTHOR_PROTOCOL = 'source_bound_author_replacement_v1'


def _glyph_rows(page, box=None):
    rows=[]
    for span in page.get_texttrace():
        for c in span['chars']:
            rect=fitz.Rect(c[3])
            if box is not None:
                if not rect.intersects(box): continue
                if not (box+(-.01,-.01,.01,.01)).contains(rect):
                    raise ValueError('source role cuts a glyph')
            rows.append({'codepoint':c[0],'glyph_id':c[1],'origin':list(c[2]),'bbox':list(c[3]),
                         **{k:list(span[k]) if isinstance(span[k],tuple) else span[k]
                            for k in ('font','size','type','opacity','color','dir')}})
    return rows


def role_glyph_evidence(page, box, expected_text):
    """逐字、逐位置核对真实字形；只登记由相邻字形间隙证明的推断空格。"""
    candidates=[l for b in page.get_text('rawdict')['blocks'] if 'lines' in b for l in b['lines']
                if close_rect(list(l['bbox']),list(box))]
    if len(candidates)!=1: raise ValueError('unique complete raw source line required')
    line=candidates[0]
    raw=[{**c,'font':s['font'],'size':s['size']} for s in line['spans'] for c in s['chars']]
    if ''.join(c['c'] for c in raw)!=expected_text:
        raise ValueError('source role raw text changed')
    trace=_glyph_rows(page,box); j=0; spaces=[]
    if any(t['codepoint'] in (0,0xfffd) or t['glyph_id']<=0
           or (t['codepoint']<32 and not chr(t['codepoint']).isspace()) for t in trace):
        raise ValueError('unknown source glyph cannot prove author identity')
    near=lambda a,b:len(a)==len(b) and all(abs(x-y)<=.01 for x,y in zip(a,b))
    for i,c in enumerate(raw):
        if j<len(trace) and ord(c['c'])==trace[j]['codepoint'] and near(c['origin'],trace[j]['origin']):
            t=trace[j]
            if c['font']!=t['font'] or abs(c['size']-t['size'])>.01:
                raise ValueError('source role glyph style changed')
            if c['c'].isspace(): spaces.append({'raw_index':i,'kind':'encoded_glyph','trace_index':j,'origin':c['origin']})
            j+=1; continue
        # MuPDF may synthesize ASCII space for a positive same-baseline gap. It
        # must be bounded by the immediately preceding and following real glyphs.
        if c['c']!=' ' or not (0<i<len(raw)-1 and 0<j<len(trace)) or tuple(line['dir'])!=(1.,0.):
            raise ValueError('source role non-whitespace glyph mismatch')
        left,right=trace[j-1],trace[j]; r=fitz.Rect(c['bbox'])
        if (raw[i-1]['c'].isspace() or raw[i+1]['c'].isspace()
            or ord(raw[i+1]['c'])!=right['codepoint'] or not near(raw[i+1]['origin'],right['origin'])
            or abs(left['origin'][1]-right['origin'][1])>.01
            or abs(r.x0-left['bbox'][2])>.01 or abs(r.x1-right['origin'][0])>.01
            or not .01<r.width<=2*c['size'] or not near(c['origin'],[r.x0,right['origin'][1]])):
            raise ValueError('unproven inferred source whitespace')
        spaces.append({'raw_index':i,'kind':'inferred_positive_glyph_gap','bbox':list(r),
                       'left_trace_index':j-1,'right_trace_index':j,'gap_points':r.width})
    if j!=len(trace): raise ValueError('source role extra glyph commands')
    return {'protocol':'source_raw_trace_geometry_v1','text':expected_text,'raw_chars':raw,
            'trace_glyphs':trace,'whitespace':spaces,'role_box':list(box)}


def validate_isolated_glyphs(page, evidence):
    if _glyph_rows(page)!=evidence['trace_glyphs']:
        raise ValueError('source isolation retained off-role glyph commands')


def normalize(text):
    return re.sub(r'\s+', '', text.replace('’', "'")).casefold()


def lines(page):
    return [line for block in page.get_text('dict')['blocks'] if 'lines' in block for line in block['lines']]


def geometry(page):
    return {'media': list(page.mediabox), 'crop': list(page.cropbox), 'rect': list(page.rect), 'rotation': page.rotation}


def object_boxes(page):
    boxes=[fitz.Rect(line['bbox']) for line in lines(page)]
    boxes.extend(fitz.Rect(char[3]) for span in page.get_texttrace() for char in span['chars'])
    boxes.extend(fitz.Rect(image['bbox']) for image in page.get_image_info())
    boxes.extend(drawing['rect'] for drawing in page.get_drawings())
    boxes.extend(link['from'] for link in page.get_links())
    return boxes


def qualify_geometry(source, target, role_box):
    """仅容许≤1pt空白边界差；原target画布和字形坐标均不改变。"""
    a,b=geometry(source),geometry(target)
    if a['rotation'] != b['rotation']:
        raise ValueError('target/source rotation differs')
    for field in ('media','crop','rect'):
        if any(abs(x-y)>1 for x,y in zip(a[field],b[field])):
            raise ValueError('target/source bounds differ by more than1pt')
    common=source.rect & target.rect
    if not common.contains(role_box):
        raise ValueError('source role outside shared effective page bounds')
    if a!=b:
        for page in (source,target):
            if any(not common.contains(box) for box in object_boxes(page)):
                raise ValueError('page difference band contains glyph/image/drawing/action')
    return {'rule':'source_target_empty_boundary_difference_at_most_1pt_v1',
            'source_geometry':a,'target_geometry':b,'exact_bounds_equal':a==b,
            'target_canvas_modified':False,'source_role_scale':1,'source_role_offset':[0,0]}


def action_identity(links):
    return [{key:list(value) if isinstance(value,(fitz.Rect,fitz.Point)) else value
             for key,value in link.items() if key!='xref'} for link in links]


def title_argument(text):
    matches = list(re.finditer(r'\\title\s*', text))
    if len(matches) != 1:
        raise ValueError('exactly one explicit title command required')
    value, _ = latex.group(text, matches[0].end())
    if any(character in value for character in '\\${}'):
        raise ValueError('protected-role host requires a finite plain title argument')
    return value


def close_rect(left, right):
    return len(left) == len(right) and all(abs(a-b) <= 1e-5 for a,b in zip(left,right))


def verify_source(page, ledger):
    if geometry(page) != ledger['page_geometry']:
        raise ValueError('source role page geometry changed')
    expected = ledger['native_line_object']
    if latex.digest(expected['text']) != expected['text_sha256']:
        raise ValueError('source role literal digest changed')
    source_lines = lines(page)
    matches = [line for line in source_lines if ''.join(span['text'] for span in line['spans']) == expected['text']]
    if len(matches) != 1:
        raise ValueError('source role glyph object must be unique')
    actual = matches[0]
    if list(actual['bbox']) != expected['bbox'] or list(actual['dir']) != expected['dir']:
        raise ValueError('source role glyph geometry changed')
    fields = ('text','font','size','flags','color','origin','bbox')
    observed = [{key:list(span[key]) if key in {'origin','bbox'} else span[key] for key in fields} for span in actual['spans']]
    if observed != expected['spans']:
        raise ValueError('source role font/style/glyph object changed')
    box = fitz.Rect(expected['bbox'])
    other = [line for line in source_lines if line is not actual and fitz.Rect(line['bbox']).intersects(box)]
    if other:
        raise ValueError('source role region overlaps ordinary source text')
    action = ledger['source_uri_annotation']
    if action.get('kind') != fitz.LINK_URI or not isinstance(action.get('uri'),str) or not action['uri'].startswith(('https://','http://')):
        raise ValueError('only explicit source HTTP URI role supported')
    matches = [link for link in page.get_links() if link.get('kind') == action['kind'] and link.get('uri') == action['uri'] and close_rect(list(link['from']),action['from'])]
    if len(matches) != 1:
        raise ValueError('source role action must be unique and unchanged')
    if not fitz.Rect(action['from']).contains(box):
        raise ValueError('source URI must contain complete registered role')
    return box


def isolated_source(source, page_number, box, path, expected_text):
    """实际删除角色框外对象，避免 full-page Form 的 off-clip 英文内容存留。"""
    evidence=role_glyph_evidence(source[page_number],box,expected_text)
    original = source[page_number].get_pixmap(matrix=fitz.Matrix(2,2),clip=box,alpha=False)
    with fitz.open() as isolated:
        isolated.insert_pdf(source,from_page=page_number,to_page=page_number)
        page=isolated[0]; extent=page.rect
        outside=[fitz.Rect(extent.x0,extent.y0,extent.x1,box.y0),
                 fitz.Rect(extent.x0,box.y1,extent.x1,extent.y1),
                 fitz.Rect(extent.x0,box.y0,box.x0,box.y1),
                 fitz.Rect(box.x1,box.y0,extent.x1,box.y1)]
        for rectangle in outside:
            if not rectangle.is_empty: page.add_redact_annot(rectangle,fill=None)
        page.apply_redactions(images=2,graphics=2,text=0)
        for link in page.get_links(): page.delete_link(link)
        isolated.save(path,garbage=4,deflate=True)
    with fitz.open(path) as isolated:
        page=isolated[0]
        if page.get_text().strip() != expected_text:
            raise ValueError('source isolation lost glyphs or retained off-role text')
        # 文本层与trace分别核：clip隐藏的额外glyph也不能留在form中。
        validate_isolated_glyphs(page,evidence)
        actual=page.get_pixmap(matrix=fitz.Matrix(2,2),clip=box,alpha=False)
        if (original.width,original.height,original.samples) != (actual.width,actual.height,actual.samples):
            raise ValueError('source isolated role pixels changed')
    Path(str(path)+'.glyph_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    return hashlib.sha256(original.samples).hexdigest()


def apply_role(contract_path, output):
    contract=load(file_ref(contract_path))
    if contract.get('protocol')==AUTHOR_PROTOCOL:
        return apply_author_replacement(contract_path,output)
    if contract.get('schema_version') != 1 or contract.get('protocol') != PROTOCOL:
        raise ValueError('unknown protected PDF role protocol')
    frozen={str(checked_ref(row)) for row in contract['implementation_refs']}
    if str(Path(__file__).resolve()) not in frozen:
        raise ValueError('actual protected-role implementation must be frozen')
    ledger=load(contract['role_ledger_ref'])
    if ledger.get('source_only') is not True or ledger.get('target_text_or_findings_included') is not False:
        raise ValueError('independent pure source role evidence required')
    for key in ('source_page_ref','source_raster_ref'): checked_ref(ledger[key])
    for item in ledger.get('standards',[]):checked_ref(item)
    if contract['source_pdf_ref'] != ledger['source_pdf_ref']:
        raise ValueError('protected role source identity mismatch')
    source_path=checked_ref(contract['source_pdf_ref']); target_path=checked_ref(contract['target_pdf_ref'])
    target_tex=checked_ref(contract['target_tex_ref']).read_text()
    plan=load(contract['plan_ref']); host=load(contract['host_unit_ref'])
    units=[unit for unit in plan['units'] if unit['id'] == contract['host_unit_id']]
    if len(units) != 1 or host['source_sha256'] != units[0]['source_sha256']:
        raise ValueError('title host complete source unit mismatch')
    restored=latex.validate_translation(units[0],host['masked_translation'])
    if host['translation'] != restored or title_argument(target_tex) != title_argument(restored):
        raise ValueError('actual compiled title differs from source-bound unit')
    title=title_argument(restored)
    source_title=title_argument(units[0]['source_text'])
    if normalize(source_title) != normalize(ledger['source_title_host_relation']['title_line_object']['text']):
        raise ValueError('paired source title host mismatch')
    output=latex.reject_symlink_ancestors(Path(output)).resolve()
    if output.exists():raise ValueError('protected-role output must be fresh')
    output.mkdir(parents=True)
    with fitz.open(source_path) as source, fitz.open(target_path) as target:
        if not 1 <= len(source) <= 5 or not 1 <= len(target) <= 5:
            raise ValueError('protected role stage limited to complete1–5 page PDFs')
        source_index=ledger['physical_page']-1
        source_page=source[source_index];box=verify_source(source_page,ledger)
        hosts=[page.number for page in target if normalize(page.get_text()).count(normalize(title)) == 1]
        total=sum(normalize(page.get_text()).count(normalize(title)) for page in target)
        if len(hosts) != 1 or total != 1:raise ValueError('actual target title host must be unique')
        page=target[hosts[0]]
        action=ledger['source_uri_annotation']; region=fitz.Rect(action['from']) | box
        geometry_audit=qualify_geometry(source_page,page,region)
        objects=object_boxes(page)
        if any(rect.intersects(region) for rect in objects):raise ValueError('target role region collision')
        prior_traces=[''.join(chr(c[0]) for span in p.get_texttrace() for c in span['chars']) for p in target]
        prior_glyphs=[p.get_texttrace() for p in target]
        prior_actions=[action_identity(p.get_links()) for p in target]
        prior_geometry=[geometry(p) for p in target]
        role_trace=role_glyph_evidence(source_page,box,ledger['native_line_object']['text'])['trace_glyphs']
        role_trace_text=''.join(chr(row['codepoint']) for row in role_trace)
        pixel_sha=isolated_source(source,source_index,box,output/'isolated_role.pdf',ledger['native_line_object']['text'])
        with fitz.open(output/'isolated_role.pdf') as isolated:
            page.show_pdf_page(box,isolated,0,clip=box,keep_proportion=False)
        page.insert_link({'kind':fitz.LINK_URI,'from':fitz.Rect(action['from']),'uri':action['uri']})
        final=output/'candidate.pdf';target.save(final,garbage=4,deflate=True)
    with fitz.open(final) as actual:
        for index,page in enumerate(actual):
            trace=''.join(chr(c[0]) for span in page.get_texttrace() for c in span['chars'])
            expected=prior_traces[index]+(role_trace_text if index==hosts[0] else '')
            if trace != expected:raise ValueError('output gained off-role glyphs or changed ordinary text')
            if geometry(page)!=prior_geometry[index]:raise ValueError('original target canvas changed')
            if page.get_texttrace()[:len(prior_glyphs[index])]!=prior_glyphs[index]:
                raise ValueError('original target glyph/font/origin/bbox changed')
            expected_actions=prior_actions[index]
            if action_identity(page.get_links())[:len(expected_actions)]!=expected_actions:
                raise ValueError('original target named/URI actions changed')
        page=actual[hosts[0]];verify_source(page,{**ledger,'page_geometry':geometry(page)})
        pixels=page.get_pixmap(matrix=fitz.Matrix(2,2),clip=box,alpha=False)
        if hashlib.sha256(pixels.samples).hexdigest() != pixel_sha:raise ValueError('actual target role pixels changed')
    result={'status':'candidate','protocol':PROTOCOL,'contract_ref':file_ref(contract_path),
            'source_role_ref':contract['role_ledger_ref'],'pre_role_pdf_ref':contract['target_pdf_ref'],
            'translated_pdf':file_ref(final),'isolated_role_ref':file_ref(output/'isolated_role.pdf'),
            'derived_target_host_page':hosts[0]+1,'source_role_page':source_index+1,'role_pixels_sha256':pixel_sha,
            'geometry_qualification':geometry_audit,'prior_target_glyphs_and_actions_unchanged':True,
            'role_glyphs_and_action_verified':True,'ordinary_text_trace_unchanged':True,'new_model_calls':0,
            'whole_pdf_verified':False,'human_accepted':False,'strict_delivery':False}
    latex.write_new(output/'PROTECTED_ROLE_RESULT.json',result);return result


def apply_author_replacement(contract_path, output):
    """显式完整作者行返修；源角色与错误目标行分别冻结，不自动识别作者。"""
    c=load(file_ref(contract_path))
    if c.get('schema_version')!=1 or c.get('protocol')!=AUTHOR_PROTOCOL:
        raise ValueError('unknown author replacement protocol')
    if str(Path(__file__).resolve()) not in {str(checked_ref(r)) for r in c['implementation_refs']}:
        raise ValueError('actual author implementation must be frozen')
    ledger=load(c['role_ledger_ref']); finding=load(c['target_role_ref'])
    if (ledger.get('source_only') is not True or ledger.get('target_text_or_findings_included') is not False
        or ledger.get('role')!='author_identity' or ledger['source_pdf_ref']!=c['source_pdf_ref']
        or finding['target_pdf_ref']!=c['target_pdf_ref']):
        raise ValueError('complete source author / target identity required')
    output=latex.reject_symlink_ancestors(Path(output)).resolve()
    if output.exists():raise ValueError('author replacement output must be fresh')
    output.mkdir(parents=True)
    def bound_line(page, item):
        if geometry(page)!=item['page_geometry']:raise ValueError('role page geometry changed')
        expected=item['native_line_object']; text=expected['text']
        if latex.digest(text)!=expected['text_sha256']:raise ValueError('role text SHA changed')
        matches=[l for l in lines(page) if ''.join(s['text'] for s in l['spans'])==text]
        if len(matches)!=1:raise ValueError('unique complete role line required')
        line=matches[0]; fields=('text','font','size','flags','color','origin','bbox')
        spans=[{k:list(s[k]) if k in {'origin','bbox'} else s[k] for k in fields} for s in line['spans']]
        if spans!=expected['spans'] or list(line['bbox'])!=expected['bbox'] or list(line['dir'])!=expected['dir']:
            raise ValueError('role glyph/style/geometry changed')
        return line,fitz.Rect(line['bbox'])
    with fitz.open(checked_ref(c['source_pdf_ref'])) as source, fitz.open(checked_ref(c['target_pdf_ref'])) as target:
        if not 1<=len(source)==len(target)<=5:raise ValueError('complete paired 1–5 page PDFs required')
        if (type(ledger['physical_page']) is not int or type(finding['physical_page']) is not int
            or not 1<=ledger['physical_page']<=len(source) or not 1<=finding['physical_page']<=len(target)):
            raise ValueError('role physical page outside complete PDF')
        index=ledger['physical_page']-1
        if index!=finding['physical_page']-1:raise ValueError('author source page must remain paired')
        sl,box=bound_line(source[index],ledger); tl,bad=bound_line(target[index],finding)
        # The declared erroneous target may itself have broken Unicode mapping.
        # Freeze its raw text AND exact actual trace; never apply this exception
        # to the correct source. Every target raw character still binds one real
        # glyph by origin/font/size, so hidden or additional commands fail.
        bad_trace=_glyph_rows(target[index],bad)
        if bad_trace!=finding.get('trace_glyphs'):
            raise ValueError('frozen erroneous target trace changed')
        raw=[{**ch,'font':sp['font'],'size':sp['size']} for b in target[index].get_text('rawdict')['blocks']
             if 'lines' in b for ln in b['lines'] if close_rect(list(ln['bbox']),list(bad))
             for sp in ln['spans'] for ch in sp['chars']]
        if len(raw)!=len(bad_trace) or any(ch['font']!=g['font'] or abs(ch['size']-g['size'])>.01
            or any(abs(a-b)>.01 for a,b in zip(ch['origin'],g['origin']))
            or not (fitz.Rect(ch['bbox'])+(-.01,-.01,.01,.01)).contains(fitz.Rect(g['bbox']))
            for ch,g in zip(raw,bad_trace)):
            raise ValueError('erroneous target raw/trace geometry is not one to one')
        union=box|bad; qualify_geometry(source[index],target[index],union)
        for page,excluded in [(source[index],sl),(target[index],tl)]:
            if any(l!=excluded and fitz.Rect(l['bbox']).intersects(union) for l in lines(page)):
                raise ValueError('author replacement collides with ordinary text')
            if any(fitz.Rect(o['bbox']).intersects(union) for o in page.get_image_info()) or any(r['rect'].intersects(union) for r in page.get_drawings()):
                raise ValueError('author replacement collides with image/drawing')
            if any(l['from'].intersects(union) for l in page.get_links()):
                raise ValueError('author replacement action collision')
        prior_geometry=[geometry(p) for p in target];prior_actions=[action_identity(p.get_links()) for p in target]
        prior=[_glyph_rows(p) for p in target]
        ordinary=[r for r in prior[index] if not bad.intersects(fitz.Rect(r['bbox']))]
        text=ledger['native_line_object']['text'];pixels=isolated_source(source,index,box,output/'isolated_author.pdf',text)
        source_glyphs=role_glyph_evidence(source[index],box,text)['trace_glyphs']
        target[index].add_redact_annot(bad,fill=(1,1,1));target[index].apply_redactions(images=0,graphics=0,text=0)
        with fitz.open(output/'isolated_author.pdf') as isolated:
            target[index].show_pdf_page(box,isolated,0,clip=box,keep_proportion=False)
        final=output/'candidate.pdf';target.save(final,garbage=4,deflate=True)
    with fitz.open(final) as actual:
        for i,p in enumerate(actual):
            expected=ordinary+source_glyphs if i==index else prior[i]
            if _glyph_rows(p)!=expected:raise ValueError('author replacement changed ordinary or added off-role glyphs')
            if geometry(p)!=prior_geometry[i] or action_identity(p.get_links())!=prior_actions[i]:
                raise ValueError('author replacement changed page/action identity')
        p=actual[index]
        if p.get_text().count(text)!=1:raise ValueError('author is not uniquely extractable')
        pix=p.get_pixmap(matrix=fitz.Matrix(2,2),clip=box,alpha=False)
        if hashlib.sha256(pix.samples).hexdigest()!=pixels:raise ValueError('author source pixels changed')
    result={'status':'candidate','protocol':AUTHOR_PROTOCOL,'translated_pdf':file_ref(final),
            'contract_ref':file_ref(contract_path),'role_ledger_ref':c['role_ledger_ref'],'target_role_ref':c['target_role_ref'],
            'glyph_evidence_ref':file_ref(Path(str(output/'isolated_author.pdf')+'.glyph_evidence.json')),
            'ordinary_glyphs_styles_geometry_actions_unchanged':True,'source_author_pixels_identical':True,
            'new_model_calls':0,'manual_source_role_bindings':1,'human_accepted':False,'strict_delivery':False}
    latex.write_new(output/'PROTECTED_ROLE_RESULT.json',result);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(apply_role(args.contract,args.output)));return 0


if __name__=='__main__':raise SystemExit(main())
