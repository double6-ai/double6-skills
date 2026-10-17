"""固定行内绑定规则；不含页码、目标词串或某个 PDF 的坐标。"""
import re,unicodedata

POLICY={'small_script_ratio':.85,'preceding_cjk_char_limit':4,
        'maximum_script_characters':32,'maximum_added_spacing_em':.3,
        'maximum_compression_em':.05,'case_specific_overrides_allowed':False}
def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',text)if not c.isspace()and c not in '\u200b\u2028')
def cjk(ch):
    return any('\u3400'<=c<='\u9fff'for c in unicodedata.normalize('NFKC',ch))
def attachment_groups(glyphs,body_size):
    text=''.join(chr(g['unicode'])for g in glyphs);groups=[]
    # 完整中文图表编号；图号本身可使用正文大小，不能只依赖小字号识别。
    for m in re.finditer(r'(?:[（(]\s*)?(?:(?:补充|扩展数据)\s*)?[图表]\s*[0-9]+[A-Za-z]?(?:\s*[）)])?',text):
        groups.append({'start':m.start(),'end':m.end(),'kind':'figure_table_identifier'})
    for m in re.finditer(r'[（(]文献\s*[0-9]+(?:\s*[、,，–−-]\s*[0-9]+)*[）)]',text):
        groups.append({'start':m.start(),'end':m.end(),'kind':'parenthesized_reference'})
    # 数字型小字号片段。科学字母下标不在本规则的自动语义声明中。
    allowed=set('0123456789０１２３４５６７８９[]［］,，、–−-')
    i=0
    while i<len(glyphs):
        if glyphs[i]['size']>=body_size*POLICY['small_script_ratio'] or text[i]not in allowed:
            i+=1;continue
        j=i+1
        while j<len(glyphs)and glyphs[j]['size']<body_size*POLICY['small_script_ratio']and text[j]in allowed:j+=1
        if j-i>POLICY['maximum_script_characters']:raise ValueError('numeric_script_budget')
        if not any(c.isdigit()for c in text[i:j]):i=j;continue
        k=i
        while k>0 and text[k-1].isspace():k-=1
        host_end=k
        if k>0 and cjk(text[k-1]):
            count=0
            while k>0 and cjk(text[k-1])and count<POLICY['preceding_cjk_char_limit']:k-=1;count+=1
        else:
            while k>0 and re.fullmatch(r'[A-Za-z0-9_$€µμ.%+−-]',text[k-1]):k-=1
        if k==host_end:raise ValueError('numeric_script_missing_preceding_host')
        groups.append({'start':k,'end':j,'kind':'numeric_script_and_preceding_text'})
        i=j
    # 采用保守的四字绑定，不能冒称自动中文分词或完整语义词识别。
    merged=[]
    for g in sorted(groups,key=lambda x:(x['start'],x['end'])):
        if merged and g['start']<merged[-1]['end']:
            merged[-1]['end']=max(g['end'],merged[-1]['end']);merged[-1]['kinds'].append(g['kind'])
        else:merged.append({'start':g['start'],'end':g['end'],'kinds':[g['kind']]})
    return merged


POLICY_ID = 'numeric-and-figure-v1'
