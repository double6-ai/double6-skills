function policyPack(){return (typeof COMPOSITION_PACK==='object'&&COMPOSITION_PACK)?COMPOSITION_PACK:null}
function policyById(id){return (policyPack()?.runtime_policies||[]).find(row=>row.policy_id===id)||null}
function policyCapacityValues(policy){return (policy&&Array.isArray(policy.committed_values)&&policy.committed_values.length)?policy.committed_values:['Top 1','Top 2','Top 3']}
function policyCapacityMax(policy){const value=Number(policy?.max_committed);return Number.isFinite(value)&&value>0?value:3}
function policyOverflowValue(policy){return String(policy?.overflow_value||'候补')}
function policyFsmStates(policy){return (policy&&Array.isArray(policy.states)&&policy.states.length)?policy.states:[]}
function policyFsmStatus(row,policy){const states=policyFsmStates(policy),field=policy?.status_field||'notes',raw=String(row?.values?.[field]||'');if(policy?.status_tag){const match=raw.match(new RegExp('\\['+policy.status_tag+':([^\\]]+)\\]'));return match?match[1]:(states[0]||'')}return states.includes(raw)?raw:(states[0]||raw)}
function policySetFsmStatus(row,policy,status){const field=policy?.status_field||'notes';if(policy?.status_tag){row.values[field]=String(row.values[field]||'').replace(new RegExp('\\s*\\['+policy.status_tag+':[^\\]]+\\]','g'),'').trim()+` [${policy.status_tag}:${status}]`}else row.values[field]=status;row.updatedAt=new Date().toISOString()}
function policyFsmConfirmed(row,policy){return policyFsmStatus(row,policy)===(policy?.confirmed_state||'')}
function policyExternalLabel(row,policy){return policyFsmConfirmed(row,policy)?'由用户确认':'尚未执行'}
function policyPromoteAllowed(row,policy){if(!policy)return true;const missing=(policy.required_fields||[]).some(key=>!String(row.values?.[key]||'').trim());const blocked=(policy.blocked_values||[]).includes(String(row.values?.[policy.blocked_field]||''));return !missing&&!blocked}
function policyModuleByType(type){return (policyPack()?.modules||[]).find(row=>row.object_type_id===type)||null}
function policyHop(fromType,toType){const rel=(policyPack()?.object_graph?.relations||[]).find(row=>row.from===fromType&&(!toType||row.to===toType));if(!rel)return null;const fromMod=policyModuleByType(fromType),toMod=policyModuleByType(rel.to);return fromMod&&toMod?{from:rel.from,to:rel.to,relation:rel.link_relation||rel.relation,graph_relation:rel.relation,from_module_id:fromMod.module_id,module_id:toMod.module_id}:null}
function policyCaptureModuleId(fallback){return (policyPack()?.attention_model?.regions||[]).find(row=>row.region_id==='capture')?.source_module_ids?.[0]||fallback||''}
function policyModuleById(id){return (policyPack()?.modules||[]).find(row=>row.module_id===id)||null}
function policyTitleFields(id){const fields=policyModuleById(id)?.title_fields;return Array.isArray(fields)&&fields.length?fields:[]}
function policyRecordTitle(id,record,fallback){const keys=policyTitleFields(id);return keys.map(key=>record?.values?.[key]).find(value=>String(value||'').trim())||(typeof recordText==='function'?recordText(record):'')||fallback||'未命名'}
function policyLinkLabel(record,extraNames){const link=record?.links?.[0];if(!link)return'';const name=policyModuleById(link.sourceModuleId)?.link_label||extraNames?.[link.sourceModuleId];return name?`来自：${name}`:''}
function policyStageField(id,fallback){return String(policyModuleById(id)?.stage_field||fallback||'stage')}
function policyStageValues(id,fallback){const values=policyModuleById(id)?.stage_values;return Array.isArray(values)&&values.length?values.slice():(fallback||[])}
function policyDefaultStage(id,fallback){return String(policyModuleById(id)?.default_stage||policyStageValues(id)[0]||fallback||'')}
function policyPromoteReadyStage(id,fallback){return String(policyModuleById(id)?.promote_ready_stage||fallback||'')}
function policyTerminalStages(id,fallback){const values=policyModuleById(id)?.terminal_stages;return Array.isArray(values)?values.slice():(fallback||[])}
function policyGateFields(id,fallback){const fields=policyModuleById(id)?.gate_fields;return Array.isArray(fields)&&fields.length?fields.slice():(fallback||[])}
function policyGateMissing(id,row,fallback){return policyGateFields(id,fallback).filter(key=>!String(row?.values?.[key]||'').trim())}
function policyStageOf(id,row,fallback){return String(row?.values?.[policyStageField(id)]||policyDefaultStage(id,fallback)||'')}
