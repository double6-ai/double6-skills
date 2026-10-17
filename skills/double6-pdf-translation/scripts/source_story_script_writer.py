"""资格有限的单页Story银行写回；完整字段失败时恢复原流。"""
from pathlib import Path
import hashlib,importlib.util,math
from pypdf.generic import ContentStream,DecodedStreamObject,FloatObject

_path=Path(__file__).resolve().parent/'source_script_binding.py'
_sha='4001e02107b587401497b0c3ac9eed718ec5a5d1f23ef9646bc285319e6a60ff'
if hashlib.sha256(_path.read_bytes()).hexdigest()!=_sha:raise ValueError('story_binding_runtime_identity_changed')
_spec=importlib.util.spec_from_file_location('bound_source_script709',_path)
binding=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(binding)

def _raw(value):
    if hasattr(value,'original_bytes'):value=value.original_bytes
    if not isinstance(value,bytes)or len(value)%2:raise ValueError('story_script_two_byte_cid_binding_required')
    return value

def rewrite_story_operations(operations,plan,expected_glyph_count):
    """只改拥有完整Tj/TJ的Ts；其它文字操作符和混合所有权须另行适配。"""
    if isinstance(expected_glyph_count,bool)or not isinstance(expected_glyph_count,int)or not 0<expected_glyph_count<=50000:
        raise ValueError('story_script_glyph_count_invalid')
    if not isinstance(operations,list)or len(operations)>100000:raise ValueError('story_script_operator_count_limit')
    if binding._digest({k:v for k,v in plan.items()if k!='plan_sha256'})!=plan.get('plan_sha256'):
        raise ValueError('story_script_plan_identity_changed')
    changes={row['glyph_index']:row['y_delta_pt']for row in plan['changes']}
    if len(changes)!=len(plan['changes']):raise ValueError('story_script_duplicate_owned_index')
    output=[];cursor=0;rise=0.;stack=[];changed=[];text_active=False
    for operands,operator in operations:
        if not isinstance(operator,bytes)or not isinstance(operands,list):raise ValueError('story_script_operation_schema_invalid')
        if operator in(b"'",b'"',b'Do'):raise ValueError('story_script_operator_requires_separate_adapter')
        if operator==b'q':
            if operands or len(stack)>=32:raise ValueError('story_script_graphics_stack_invalid')
            stack.append(rise)
        elif operator==b'Q':
            if operands or not stack:raise ValueError('story_script_graphics_stack_invalid')
            rise=stack.pop()
        elif operator==b'BT':
            if text_active or operands:raise ValueError('story_script_text_object_invalid')
            text_active=True
        elif operator==b'ET':
            if not text_active or operands:raise ValueError('story_script_text_object_invalid')
            text_active=False
        elif operator==b'Ts':
            if len(operands)!=1 or isinstance(operands[0],bool):raise ValueError('story_script_rise_operand_invalid')
            try:rise=float(operands[0])
            except(TypeError,ValueError)as error:raise ValueError('story_script_rise_operand_invalid')from error
            if not math.isfinite(rise):raise ValueError('story_script_rise_operand_invalid')
        if operator in(b'Tj',b'TJ'):
            if not text_active or len(operands)!=1:raise ValueError('story_script_show_outside_bound_text_object')
            if operator==b'Tj':values=[_raw(operands[0])]
            else:
                if not isinstance(operands[0],list):raise ValueError('story_script_array_binding_invalid')
                values=[]
                for value in operands[0]:
                    if isinstance(value,(int,float))and not isinstance(value,bool):
                        if not math.isfinite(value):raise ValueError('story_script_kerning_invalid')
                    else:values.append(_raw(value))
            count=sum(len(value)//2 for value in values);indices=list(range(cursor,cursor+count))
            owned=set(indices).intersection(changes)
            if owned:
                if owned!=set(indices):raise ValueError('story_script_mixed_show_ownership')
                deltas={changes[i]for i in indices}
                if len(deltas)!=1:raise ValueError('story_script_mixed_show_deltas')
                delta=deltas.pop()
                if not binding._number(delta,-.2,.2):raise ValueError('story_script_delta_invalid')
                output.extend([([FloatObject(rise-delta)],b'Ts'),(operands,operator),([FloatObject(rise)],b'Ts')])
                changed.extend(indices)
            else:output.append((operands,operator))
            cursor+=count
            if cursor>expected_glyph_count:raise ValueError('story_script_actual_glyph_count_mismatch')
        else:output.append((operands,operator))
    if text_active or stack:raise ValueError('story_script_unbalanced_state')
    if cursor!=expected_glyph_count or sorted(changed)!=sorted(changes):raise ValueError('story_script_actual_glyph_count_mismatch')
    return output

def apply_bound_baselines(document,*,text_form_xref,source_native,target_native,bindings,required_source_ids,native_reader):
    """实际银行是唯一一页；调用方还须另做保存重开、字体程序、墨迹与点击核验。"""
    if len(document)!=1:raise ValueError('story_script_single_bank_page_required')
    if isinstance(text_form_xref,bool)or not isinstance(text_form_xref,int)or text_form_xref<=0:
        raise ValueError('story_script_form_identity_invalid')
    if document.xref_get_key(text_form_xref,'Subtype')!=('name','/Form'):raise ValueError('story_script_explicit_form_required')
    original=document.xref_stream(text_form_xref)
    if not isinstance(original,bytes)or len(original)>1024**2:raise ValueError('story_script_stream_missing_or_oversize')
    before=native_reader(document[0])
    if before!=target_native:raise ValueError('story_script_actual_input_native_mismatch')
    plan=binding.plan_source_script_bindings(source_native,before,bindings,required_source_ids=required_source_ids)
    frozen_context={'source_native_sha256':binding._digest(source_native),'target_native_sha256':binding._digest(before),
        'bindings_sha256':binding._digest(bindings),'source_inventory_sha256':binding._digest(required_source_ids),'plan_sha256':plan['plan_sha256']}
    stream=DecodedStreamObject();stream.set_data(original);content=ContentStream(stream,None)
    content.operations=rewrite_story_operations(content.operations,plan,len(before))
    attempted=False
    try:
        attempted=True;document.update_stream(text_form_xref,content.get_data())
        actual=native_reader(document[0]);verification=binding.verify_native_baseline_changes(before,actual,plan,
            source_native=source_native,bindings=bindings,required_source_ids=required_source_ids,verification_context=frozen_context)
    except Exception:
        if attempted:
            document.update_stream(text_form_xref,original)
            if native_reader(document[0])!=before:raise RuntimeError('story_script_rollback_native_verification_failed')
        raise
    return {'plan':plan,'verification':verification,'binding_runtime_sha256':_sha,'in_memory_native_fields_verified':True,
        'actual_saved_pdf_font_program_ink_navigation_and_independent_review_still_required':True,'quality_pass':False}
