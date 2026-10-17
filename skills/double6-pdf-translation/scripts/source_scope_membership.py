"""独立源成员清单与执行范围的集合检查；非空范围也必须完整。"""
from collections import Counter

def audit_scope_membership(required_members,items,exclusions,complete_groups=()):
    """required_members须来自绑定实际源页、标准与审校员的完整独立枚举。

    本函数核对成员，不生成源范围、不授予字体/视觉或整件接受。
    """
    result={'status':'unverified','issues':[],'pending':[], 'quality_pass':False}
    try:
        def member(value):
            if not isinstance(value,(list,tuple)) or len(value)!=2 or any(type(x) is not int for x in value) or value[0]<1 or value[1]<0:
                raise ValueError('source_member_identity_invalid')
            return tuple(value)
        required=[member(v) for v in required_members]
        if not required or len(required)!=len(set(required)):raise ValueError('complete_independent_source_member_manifest_missing_or_duplicate')
        owned=[];by_id={}
        for row in items:
            if row['id'] in by_id:raise ValueError('source_item_id_duplicate')
            values=[member((row['page'],i)) for i in row['source_label_indices']]
            if not values:raise ValueError('empty_source_item')
            owned+=values;by_id[row['id']]=set(values)
        counts=Counter(owned)
        for value,count in sorted(counts.items()):
            if count>1:result['issues'].append({'rule':'source_member_owned_more_than_once','member':value})
        excluded=set()
        for row in exclusions:
            if row.get('exclusion_decision')!='pass' or not row.get('reason'):
                raise ValueError('exclusion_requires_independent_finite_acceptance')
            excluded.update(member((row['page'],i)) for i in row['indices'])
        for value in sorted(excluded.intersection(counts)):
            result['issues'].append({'rule':'source_member_owned_and_excluded','member':value})
        missing=set(required)-set(counts)-excluded
        for value in sorted(missing):result['issues'].append({'rule':'complete_source_marker_missing_from_execution_scope','member':value})
        for group in complete_groups:
            members=set(member(v) for v in group['members'])
            # 科学负指数或分数指数的成员必须归属同一个完整样式项。
            candidates=[key for key,values in by_id.items() if members.issubset(values)]
            if len(candidates)!=1:
                result['issues'].append({'rule':'complete_semantic_marker_split_or_missing','group_id':group['id'],'members':sorted(members)})
        result.update(required_member_count=len(required),owned_unique_member_count=len(counts),
          excluded_unique_member_count=len(excluded),missing_members=sorted(missing))
    except (ValueError,TypeError,KeyError) as error:result['pending'].append({'rule':'source_scope_membership_unverified','reason':str(error)})
    result['status']='fail' if result['issues'] else 'unverified' if result['pending'] else 'pass'
    return result


def audit_frozen_source_members(scope,freeze,*,source_ref,standard_ref,expected_pages):
    from qa_source_contract import read_bound_json
    try:
        manifest=read_bound_json(scope['source_members_ref'])
        if (manifest.get('source')!=source_ref or manifest.get('standard')!=standard_ref or
            manifest.get('reviewer_id')!=freeze['reviewer_id'] or manifest.get('method')!='source_first' or
            manifest.get('pages')!=expected_pages or manifest.get('source_scope_status')!='pass'):
            raise ValueError('complete_independent_source_member_identity_or_acceptance_changed')
        if manifest.get('source_scope_item_ids')!=[r['id'] for r in scope['items']]:
            raise ValueError('independent_complete_source_item_order_or_scope_changed')
        return audit_scope_membership(manifest['required_members'],scope['items'],
            manifest['excluded_source_items'],manifest['complete_groups'])
    except (KeyError,ValueError,TypeError,OSError) as error:
        return {'status':'unverified','issues':[],'pending':[{'rule':'complete_source_member_manifest_missing_invalid_changed',
            'reason':str(error)}],'quality_pass':False}
