"""独立源结构与成品测量比较；不按生产计划正确与否授予质量接受。"""
from __future__ import annotations
import math

def _report(issues, **extra):
    return {'status':'fail' if issues else 'pass','issues':issues,'quality_pass':False,**extra}

def audit_paragraph_flow(source, actual, *, maximum_baseline_drift_pt):
    issues=[]
    def fail(rule):issues.append({'id':source['id'],'rule':rule})
    if not math.isfinite(maximum_baseline_drift_pt) or maximum_baseline_drift_pt<0:
        raise ValueError('paragraph_declared_drift_required')
    fragments=source['fragments'];placements=actual['placements']
    expected=[line for f in fragments for line in f['source_line_ids']]
    if not fragments or len(expected)!=len(set(expected)) or actual.get('source_line_ids')!=expected:
        fail('paragraph_complete_source_context_or_order')
    if actual.get('source_text_sha256')!=source.get('source_text_sha256') or actual.get('target_text_sha256')!=source.get('reviewed_target_text_sha256'):
        fail('paragraph_source_or_reviewed_target_identity')
    if actual.get('source_fragment_breaks_enforced') is not False or actual.get('typesetting_calls')!=1:
        fail('paragraph_source_fragments_forced_separate_typesetting')
    cursor=0;order=[]
    for placement in placements:
        start,end=placement['line_range'];order.append((placement['page'],placement['column']))
        if start!=cursor or not isinstance(end,int) or end<=start:fail('paragraph_line_gap_overlap_or_empty')
        cursor=end
        if placement.get('fit_scale')!=1:fail('paragraph_automatic_shrink')
        if not math.isfinite(placement['first_baseline']) or abs(placement['first_baseline']-placement['source_baseline'])>maximum_baseline_drift_pt:
            fail('paragraph_start_baseline_drift')
    if cursor!=actual.get('host_line_count') or not placements:fail('paragraph_target_lines_incomplete')
    if order!=sorted(set(order)):fail('paragraph_target_reading_order')
    if placements and source.get('complete_new_paragraph') and placements[0]['page']!=fragments[0]['page']:
        fail('complete_new_paragraph_moved_from_source_page')
    return _report(issues,source_fragments=len(fragments),actual_parts=len(placements))

def audit_caption_structure(source, actual, *, edge_tolerance_pt=.25):
    """源列分别绑定；只在明确政策下要求栏高平衡。"""
    if not 0<edge_tolerance_pt<=1:raise ValueError('caption_edge_tolerance')
    issues=[]
    def fail(rule):issues.append({'id':source['id'],'rule':rule})
    expected=source['columns'];columns=actual['columns']
    source_numbers=[source['lower_rule'],source['clearance']]+[v for c in expected for v in (c['left'],c['right'])]
    actual_numbers=[v for c in columns for v in (c['frame_left'],c['frame_right'],c['ink_left'],c['ink_right'],c['ink_bottom'],c['lines'])]
    if not expected or not columns or any(not isinstance(v,(float,int)) or isinstance(v,bool) or not math.isfinite(v) for v in source_numbers+actual_numbers):
        return _report([{'id':source['id'],'rule':'caption_actual_geometry_unverified'}])
    if actual.get('figure_id')!=source['figure_id']:fail('caption_wrong_figure_association')
    if actual.get('page')!=source['page']:fail('caption_source_page_changed')
    if actual.get('structure')!=source['structure'] or len(columns)!=len(expected):fail('caption_source_column_structure_changed')
    for declared,column in zip(expected,columns):
        if abs(column['frame_left']-declared['left'])>edge_tolerance_pt or abs(column['frame_right']-declared['right'])>edge_tolerance_pt:
            fail('caption_source_column_footprint_changed')
        if column['ink_left']<declared['left']-edge_tolerance_pt or column['ink_right']>declared['right']+edge_tolerance_pt:
            fail('caption_ink_outside_source_column')
        if column['ink_bottom']>source['lower_rule']-source['clearance']+edge_tolerance_pt:
            fail('caption_lower_rule_clearance')
    if any(a['ink_right']>=b['ink_left'] for a,b in zip(columns,columns[1:])):fail('caption_gutter_occupied')
    if source.get('balanced_continuous_flow') and len(columns)>1:
        if max(c['lines'] for c in columns)-min(c['lines'] for c in columns)>source['maximum_line_difference']:
            fail('caption_declared_column_balance')
    if actual.get('text_complete') is not True or actual.get('line_order_complete') is not True:
        fail('caption_missing_duplicate_or_reordered_text')
    if actual.get('typesetting_calls')!=1 or actual.get('fit_scale')!=1:fail('caption_split_translation_or_shrink')
    return _report(issues,source_structure=source['structure'],actual_structure=actual.get('structure'))

def audit_reading_spacing(classes, actual_rows, whitespace_regions):
    issues=[];pending=[]
    if classes and not actual_rows:pending.append({'rule':'actual_typography_rows_missing'})
    for row in actual_rows:
        policy=classes.get(row['class'])
        if not policy:
            pending.append({'id':row['id'],'rule':'typography_class_without_policy'});continue
        for field in ('font_size_pt','baseline_step_pt','tracking_pt'):
            value=row.get(field)
            if value is None or not math.isfinite(value):pending.append({'id':row['id'],'rule':'actual_typography_measurement_missing','field':field})
            elif abs(value-policy[field])>policy['tolerance_pt']:issues.append({'id':row['id'],'rule':'same_class_typography_not_uniform','field':field})
        if row.get('overflow') is not False:issues.append({'id':row['id'],'rule':'reading_region_overflow'})
    allowed={'source_whitespace','shorter_translation','source_anchor_constraint','structural_gap','missing_translation'}
    for region in whitespace_regions:
        if region.get('cause') not in allowed or not region.get('evidence'):
            pending.append({'id':region['id'],'rule':'whitespace_cause_unverified'})
        elif region['cause'] in {'structural_gap','missing_translation'}:
            issues.append({'id':region['id'],'rule':'unresolved_reading_whitespace_defect'})
    return {'status':'fail' if issues else 'unverified' if pending else 'pass','issues':issues,
            'pending':pending,'measured_units':len(actual_rows),'quality_pass':False}
