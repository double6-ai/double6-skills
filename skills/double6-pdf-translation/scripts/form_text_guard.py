"""核查实际Form依赖；仅决定恢复资格，不授予PDF保护或质量接受。"""
from __future__ import annotations
from pypdf.generic import ContentStream, DecodedStreamObject, NameObject

TEXT_SHOW_OPERATORS = frozenset((b'Tj', b'TJ', b"'", b'"'))


def _positive_xref(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError('form_dependency_xref_invalid')
    return value


def has_text_descendant(document, owner, *, maximum_forms=256,
                        maximum_depth=32, maximum_stream_bytes=1024**2):
    """按实际Do资源递归，检测子Form文字；循环、未绑定资源和超限均阻断。"""
    _positive_xref(owner)
    for value, ceiling in ((maximum_forms, 256), (maximum_depth, 32),
                           (maximum_stream_bytes, 1024**2)):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= ceiling:
            raise ValueError('form_dependency_limit_invalid')
    if document.xref_get_key(owner, 'Subtype') != ('name', '/Form'):
        raise ValueError('form_dependency_root_not_form')
    states = {}; pending = [(owner, 0, False)]; examined = 0
    while pending:
        current, depth, closing = pending.pop()
        if closing:
            states[current] = 2
            continue
        if states.get(current) == 1:
            raise ValueError('form_dependency_cycle')
        if states.get(current) == 2:
            continue
        if depth > maximum_depth:
            raise ValueError('form_dependency_depth_limit')
        examined += 1
        if examined > maximum_forms:
            raise ValueError('form_dependency_count_limit')
        subtype = document.xref_get_key(current, 'Subtype')
        if subtype == ('name', '/Image'):
            states[current] = 2
            continue
        if subtype != ('name', '/Form'):
            raise ValueError('form_dependency_child_not_form_or_image')
        raw = document.xref_stream(current)
        if not isinstance(raw, bytes) or len(raw) > maximum_stream_bytes:
            raise ValueError('form_dependency_stream_missing_or_oversize')
        stream = DecodedStreamObject(); stream.set_data(raw)
        operations = ContentStream(stream, None).operations
        if current != owner and any(op in TEXT_SHOW_OPERATORS for _, op in operations):
            return True
        states[current] = 1
        pending.append((current, depth, True))
        children = []
        for operands, operator in operations:
            if operator != b'Do':
                continue
            if len(operands) != 1:
                raise ValueError('form_dependency_do_operand_invalid')
            if not isinstance(operands[0], NameObject):
                raise ValueError('form_dependency_do_name_object_required')
            name = str(operands[0])
            if not name.startswith('/') or len(name) > 256:
                raise ValueError('form_dependency_resource_name_invalid')
            kind, value = document.xref_get_key(current, 'Resources/XObject/'+name[1:])
            parts = value.split()
            if kind != 'xref' or len(parts) != 3 or parts[2] != 'R':
                raise ValueError('form_dependency_do_resource_unbound')
            try:
                child = _positive_xref(int(parts[0]))
                generation = int(parts[1])
            except (TypeError, ValueError) as error:
                raise ValueError('form_dependency_do_reference_invalid') from error
            if generation != 0:
                raise ValueError('form_dependency_nonzero_generation_requires_adapter')
            children.append(child)
        for child in reversed(children):
            pending.append((child, depth+1, False))
    return False


def require_leaf_restore_pair(document, source_owner, target_owner,
                             *, source_invocation_count, target_invocation_count):
    """两端资格分别核验；重复调用需独立适配，不能由名称相同推导保护。"""
    for count in (source_invocation_count, target_invocation_count):
        if isinstance(count, bool) or not isinstance(count, int) or count != 1:
            raise ValueError('form_restore_repeated_invocation_requires_adapter')
    if has_text_descendant(document, source_owner):
        raise ValueError('form_restore_source_contains_descendant_text')
    if has_text_descendant(document, target_owner):
        raise ValueError('form_restore_target_contains_descendant_text')
    return {'source_owner': source_owner, 'target_owner': target_owner,
            'both_actual_dependencies_checked': True,
            'font_program_payload_geometry_binding_still_required': True,
            'protected_native_fields_and_outside_ink_checks_still_required': True,
            'quality_pass': False}
