"""同URI完整标签：从源实际字形推导点击留量，统一投影到译文宿主。"""
from __future__ import annotations
from collections import defaultdict
import argparse,json,re
from pathlib import Path
import fitz
from native_line_spacing import glyphs,identity,compare_glyphs
from paragraph_link_rebind import reference,checked_ref,nonspace,centre,union
from raw_link_actions import _parsed_action
POLICY={'id':'source-uri-label-padding-v1','maximum_pages':5,'maximum_padding_pt':3.,
        'continuous_fragment_tolerance_pt':.03,'saved_position_tolerance_pt':.03,'case_overrides_allowed':False}

def groups(doc,page):
    result=defaultdict(list)
    for link in page.get_links():
        if link['kind']!=fitz.LINK_URI:raise ValueError('uri_host_non_uri_annotation_requires_separate_route')
        raw=doc.xref_get_key(link['xref'],'A')
        if raw[0]!='dict' or doc.xref_get_key(link['xref'],'AA')!=('null','null'):raise ValueError('uri_host_direct_action_required')
        action=_parsed_action(raw[1])
        if '/Next' in action or str(action.get('/S'))!='/URI' or str(action.get('/URI'))!=link['uri']:
            raise ValueError('uri_host_action_is_not_single_uri')
        result[link['uri']].append(link)
    return result

def label_members(gs,links):
    return [g for g in nonspace(gs) if g['type']==0 and any(fitz.Rect(l['from']).contains(centre(g)) for l in links)]

def contiguous_rect(links):
    boxes=sorted((fitz.Rect(l['from']) for l in links),key=lambda r:r.x0)
    tolerance=POLICY['continuous_fragment_tolerance_pt']
    if len(boxes)>1:
        if any(abs(r.y0-boxes[0].y0)>tolerance or abs(r.y1-boxes[0].y1)>tolerance for r in boxes):raise ValueError('uri_host_fragment_multirow_not_supported')
        if any(abs(b.x0-a.x1)>tolerance for a,b in zip(boxes,boxes[1:])):raise ValueError('uri_host_fragments_gap_overlap_or_duplicate')
    return fitz.Rect(min(r.x0 for r in boxes),min(r.y0 for r in boxes),max(r.x1 for r in boxes),max(r.y1 for r in boxes))

def apply_uri_plan(plan,output):
    if set(plan)!={'schema_version','source','target','pages','policy'} or plan['schema_version']!='native-uri-host-rebind@1' or plan['policy']!=POLICY:
        raise ValueError('uri_host_frozen_policy_required')
    src=checked_ref(plan['source']);target=checked_ref(plan['target']);pages=plan['pages']
    if not pages or len(pages)>POLICY['maximum_pages'] or pages!=sorted(set(pages)):raise ValueError('uri_host_page_budget')
    output=Path(output);output.mkdir(exist_ok=False);records=[];snapshots={};expected_actions={};total_before=0
    with fitz.open(src) as source,fitz.open(target) as doc:
        if len(doc)!=len(source):raise ValueError('uri_host_source_target_page_count_changed')
        for number in pages:
            page=doc[number-1];sp=source[number-1]
            if page.rotation or sp.rotation:raise ValueError('uri_host_rotated_page_not_supported')
            old=glyphs(page);snapshots[number]=old;sg=glyphs(sp);slinks=groups(source,sp);tlinks=groups(doc,page)
            if set(slinks)!=set(tlinks):raise ValueError('uri_host_source_target_uri_set_changed')
            total_before+=sum(len(g) for g in tlinks.values());removed=set()
            expected_actions[number]={uri:source.xref_get_key(ls[0]['xref'],'A') for uri,ls in slinks.items()}
            for uri,links in tlinks.items():
                src_links=slinks[uri];sbox=contiguous_rect(src_links);oldbox=contiguous_rect(links)
                raw=source.xref_get_key(src_links[0]['xref'],'A')
                if any(source.xref_get_key(l['xref'],'A')!=raw for l in src_links) or any(doc.xref_get_key(l['xref'],'A')!=raw for l in links):raise ValueError('uri_host_full_action_changed_or_ambiguous')
                sm=label_members(sg,src_links);tm=label_members(old,links)
                if not sm or not tm:
                    if sm or tm or len(links)!=len(src_links) or max(abs(x-y) for x,y in zip(sbox,oldbox))>.03:
                        raise ValueError('uri_host_nontext_asset_binding_changed')
                    records.append({'page':number,'uri':uri,'role':'unchanged_nontext_asset','annotations_before':len(links),'annotations_after':len(links),'raw_action_exact':True});continue
                # 来源与目标允许翻译标签，但全部现有宿主必须唯一且为单行。
                if len({identity(g) for g in tm})!=len(tm) or max(g['origin'][1] for g in tm)-min(g['origin'][1] for g in tm)>.03:
                    raise ValueError('uri_host_target_label_ambiguous_or_multirow')
                sb=union(sm);tb=union(tm);padding=[sb[0]-sbox[0],sb[1]-sbox[1],sbox[2]-sb[2],sbox[3]-sb[3]]
                if any(abs(x)>POLICY['maximum_padding_pt'] for x in padding):raise ValueError('uri_host_source_padding_unbounded')
                new=fitz.Rect(tb[0]-padding[0],tb[1]-padding[1],tb[2]+padding[2],tb[3]+padding[3]);keys={identity(g) for g in tm}
                if not page.rect.contains(new) or not all(new.contains(centre(g)) for g in tm):raise ValueError('uri_host_new_box_misses_host_or_page')
                if any(new.contains(centre(g)) and identity(g) not in keys for g in nonspace(old) if g['type']==0):raise ValueError('uri_host_new_box_contains_unrelated_text')
                first=links[0]['xref'];pdfrect=new*~page.transformation_matrix
                doc.xref_set_key(first,'Rect','['+' '.join(format(v,'.9f') for v in pdfrect)+']')
                removed.update(l['xref'] for l in links[1:])
                records.append({'page':number,'uri':uri,'role':'text_label','source_label':''.join(chr(g['unicode']) for g in sm),'target_label':''.join(chr(g['unicode']) for g in tm),'source_padding_pt':padding,'old_rect':list(oldbox),'new_rect':list(new),'retained_xref':first,'removed_redundant_xrefs':[l['xref'] for l in links[1:]],'annotations_before':len(links),'annotations_after':1,'raw_action_exact':True})
            if removed:
                typ,array=doc.xref_get_key(page.xref,'Annots')
                if typ!='array':raise ValueError('uri_host_annotation_array_not_direct')
                # 只移除已核验的同动作冗余框，其它注释引用原位保留。
                tokens=re.findall(r'(\d+)\s+(\d+)\s+R',array)
                if len(tokens)!=len(page.get_links()):raise ValueError('uri_host_annotation_array_has_other_objects')
                doc.xref_set_key(page.xref,'Annots','['+' '.join(f'{x} {generation} R' for x,generation in tokens if int(x) not in removed)+']')
            compare_glyphs(glyphs(doc.reload_page(page)),old,.03)
        candidate=output/'candidate.pdf';doc.save(candidate,garbage=0,deflate=True)
    with fitz.open(candidate) as doc:
        total_after=0
        for number in pages:
            page=doc[number-1];actual=glyphs(page);compare_glyphs(actual,snapshots[number],.03);current=groups(doc,page)
            total_after+=sum(len(g) for g in current.values())
            if set(current)!=set(expected_actions[number]):raise ValueError('uri_host_saved_uri_set_changed')
            if any(doc.xref_get_key(l['xref'],'A')!=expected_actions[number][uri] for uri,ls in current.items() for l in ls):raise ValueError('uri_host_saved_raw_action_changed')
            for r in [r for r in records if r['page']==number]:
                ls=current[r['uri']];assert len(ls)==r['annotations_after']
                if r['role']=='text_label':
                    assert max(abs(x-y) for x,y in zip(ls[0]['from'],r['new_rect']))<.03
                    assert ''.join(chr(g['unicode']) for g in label_members(actual,ls))==r['target_label']
    report={'schema_version':'native-uri-host-rebind-result@1','source':plan['source'],'before':plan['target'],'candidate':reference(candidate),'policy':POLICY,'rows':records,'annotations_before':total_before,'annotations_after':total_after,'all_saved_glyph_positions_and_styles_preserved':True,'all_saved_raw_A_exact_to_source':True,'case_overrides':0,'quality_pass':False,'human_acceptance':False}
    (output/'REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');return report

def main():
    p=argparse.ArgumentParser();p.add_argument('plan',type=Path);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();r=apply_uri_plan(json.loads(a.plan.read_text()),a.output_dir)
    print(json.dumps({k:v for k,v in r.items() if k!='rows'},ensure_ascii=False))
if __name__=='__main__':main()
