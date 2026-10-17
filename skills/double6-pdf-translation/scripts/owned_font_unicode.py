# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：将既有新字体Unicode绑定复用于普通电子PDF写出。
"""为调用方明确拥有的新字体绑定实际使用CID的精确Unicode。"""
def bind_owned_font_unicode(doc, font_xref, mapping, *, owned_font_xrefs):
    if font_xref not in owned_font_xrefs:
        raise ValueError('font_unicode_target_not_owned')
    if not mapping or any(not isinstance(k,int) or not 0<=k<=65535 or
                          not isinstance(v,str) or not v or any(0xd800<=ord(c)<=0xdfff for c in v)
                          for k,v in mapping.items()):
        raise ValueError('invalid_actual_cid_unicode_mapping')
    lines=['/CIDInit /ProcSet findresource begin','12 dict begin','begincmap',
           '/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def',
           '/CMapName /OwnedActualUnicode def','/CMapType 2 def','1 begincodespacerange',
           '<0000> <ffff>','endcodespacerange']
    pairs=sorted(mapping.items())
    for start in range(0,len(pairs),100):
        part=pairs[start:start+100];lines.append(str(len(part))+' beginbfchar')
        lines.extend('<%04x> <%s>'%(gid,text.encode('utf-16-be').hex())for gid,text in part)
        lines.append('endbfchar')
    lines+=['endcmap','CMapName currentdict /CMap defineresource pop','end','end']
    xref=doc.get_new_xref();doc.update_object(xref,'<<>>')
    doc.update_stream(xref,('\n'.join(lines)+'\n').encode('ascii'))
    doc.xref_set_key(font_xref,'ToUnicode',str(xref)+' 0 R')
    # 后续兼容性cmap清理不能丢弃无墨迹空格，或归一调用方要求的精确Unicode。
    doc.xref_set_key(font_xref,'Double6OwnedActualUnicode','true')
    return {'font_xref_before_save':font_xref,'actual_used_cids':len(mapping)}


def bind_typeset_owned_font_unicode(doc, il, *, owned_font_ids, source_font_xrefs,
                                   paragraph_characters):
    """由实际排版字符绑定新字体；绝不改原PDF的字体、科学字符或内容流。"""
    maps={};names={}
    for page in il.page:
        resources={}
        for font in doc[page.page_number].get_fonts(full=True):
            if font[4] in owned_font_ids:
                resources.setdefault(font[4],set()).add(font[0])
        chars=list(page.pdf_character or [])
        for paragraph in page.pdf_paragraph:
            chars.extend(paragraph_characters(paragraph))
        for char in chars:
            font_id=char.pdf_style.font_id
            if font_id not in owned_font_ids or char.pdf_character_id is None or char.char_unicode=='\n':
                continue
            xrefs=resources.get(font_id,set())
            if len(xrefs)!=1:
                raise ValueError('typeset_owned_font_resource_ambiguous')
            xref=next(iter(xrefs))
            if xref in source_font_xrefs:
                raise ValueError('typeset_unicode_would_change_source_font')
            text=char.char_unicode;code=char.pdf_character_id
            if not isinstance(text,str) or not text:
                raise ValueError('typeset_owned_character_unicode_missing')
            mapping=maps.setdefault(xref,{})
            if code in mapping and mapping[code]!=text:
                raise ValueError('typeset_owned_CID_has_ambiguous_unicode')
            mapping[code]=text;names[xref]=font_id
    result=[]
    for xref,mapping in maps.items():
        row=bind_owned_font_unicode(doc,xref,mapping,owned_font_xrefs=set(maps))
        row['font_resource']=names[xref];row['actual_space_cids']=[c for c,u in mapping.items()if u==' ']
        result.append(row)
    return result
