"""报告须符合schema且由冻结实际字形重新算出；不相信自报pass。"""
from pathlib import Path
import hashlib,importlib.util,json
from jsonschema import Draft202012Validator,ValidationError
W=Path(__file__).resolve().parent
RUNTIME=W/'source_script_audit.py'
SCHEMA=W.parent/'schemas/source-script-audit.schema.json'

def validate_bound_script_report(report,*,source_native,target_native,bindings,required_source_ids,
        normalized_tolerance,size_ratio_tolerance,policy_scope_id,expected_runtime_sha256,expected_schema_sha256):
    for path,expected in((RUNTIME,expected_runtime_sha256),(SCHEMA,expected_schema_sha256)):
        if not isinstance(expected,str)or len(expected)!=64 or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('script_report_frozen_runtime_or_schema_changed')
    schema=json.loads(SCHEMA.read_text());Draft202012Validator.check_schema(schema)
    try:Draft202012Validator(schema).validate(report)
    except ValidationError as error:raise ValueError('script_report_schema_invalid')from error
    spec=importlib.util.spec_from_file_location('report_gate_audit717',RUNTIME)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    expected=module.assess_bound_script_styles(source_native,target_native,bindings,required_source_ids=required_source_ids,
        normalized_tolerance=normalized_tolerance,size_ratio_tolerance=size_ratio_tolerance,policy_scope_id=policy_scope_id)
    if report!=expected:raise ValueError('script_report_actual_bound_recalculation_mismatch')
    return {'component_gate_decision':expected['component_decision'],'schema_and_actual_inputs_recomputed':True,
        'source_qa_unverified_does_not_pass':expected['component_decision']=='unverified','quality_pass':False}
