# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""第一方有限 LaTeX 翻译器：逐完整段落冻结/缓存，未知正文结构拒绝。"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import urllib.request

PROTECTION_PROTOCOL = "latex_typed_atoms_v1"
SYSTEM_PROMPT = "Translate the complete academic passage into Simplified Chinese, preserving all ordinary terms and mathematical argument roles. Preserve every PTPROTECTED token exactly once. Keep all fixed structural tokens in source order; only independent inline math tokens may change order within the same fixed-token boundaries, according to the source-bound atom ledger below. Return only the translation. Do not introduce TeX syntax."
GENERATION = {"temperature": 0.7, "top_p": 1.0, "top_k": -1, "repetition_penalty": 1.0, "max_tokens": 4096}
TRANSPORT = {'request_timeout_seconds':110,'max_attempts':1}
LOCALE_LABELS = {'Theorem':'定理','Lemma':'引理','Definition':'定义','Proposition':'命题',
                 'Corollary':'推论','Remark':'注','Example':'例','Assumption':'假设'}


def class_locale(prefix, document_class):
    """有限article/amsart具名中文locale；未知自定义标签不能算保护完成。"""
    if document_class not in {'article','amsart'}:raise ValueError('class locale unsupported')
    named={'proofname':'证明','refname':'参考文献','abstractname':'摘要','keywordsname':'关键词',
           'figurename':'图','tablename':'表','contentsname':'目录','appendixname':'附录',
           'partname':'部分','indexname':'索引','listfigurename':'插图目录','listtablename':'表格目录'}
    address_labels = {'curraddrname': '现地址', 'emailaddrname': '电子邮件地址', 'urladdrname': '网址'}
    if document_class == 'amsart':
        named.update(address_labels)
    for name in [*named,'subjclassname']:
        if re.search(r'\\(?:re)?newcommand\s*\{?\\'+name+r'\b|\\def\s*\\'+name+r'\b',prefix):
            raise ValueError('custom natural-language class label requires source review: '+name)
    records=[];replacements=[]
    for match in re.finditer(r'\\newtheorem\*?\s*',prefix):
        name,end=group(prefix,match.end())
        while end<len(prefix) and prefix[end].isspace():end+=1
        if end<len(prefix) and prefix[end]=='[':
            _,end=group(prefix,end,'[',']')
            while end<len(prefix) and prefix[end].isspace():end+=1
        label,stop=group(prefix,end)
        if label not in LOCALE_LABELS:
            raise ValueError('custom natural-language theorem label unsupported: '+label)
        replacements.append((end,stop,'{'+LOCALE_LABELS[label]+'}'))
        records.append({'environment':name,'source_label':label,'translation':LOCALE_LABELS[label],
                        'role':'translated_standard_locale','source_span':[end,stop]})
    for start,stop,value in reversed(replacements):prefix=prefix[:start]+value+prefix[stop:]
    commands='\n'.join('\\providecommand{\\'+k+'}{'+v+'}\\renewcommand{\\'+k+'}{'+v+'}' for k,v in named.items())
    if document_class=='amsart':
        # amsart.cls 的 @setaddresses 使用这些具名宏；保留原 itshape 声明。
        commands+='\n'+'\n'.join('\\renewcommand{\\'+k+'}{{\\itshape '+v+'}}' for k,v in address_labels.items())
        commands+='\n\\makeatletter\n'+ '\n'.join('\\expandafter\\def\\csname subjclassname@'+year+'\\endcsname{\\textup{'+year+'} 数学主题分类}' for year in ('1991','2000','2010','2020'))+'\n\\makeatother\n'
    return prefix,commands,{'rule':'article-amsart-zh-locale-v2','document_class':document_class,
                           'standard_macro_labels':named,'theorem_declarations':records,
                           'source_year_and_classification_codes':'preserved','pdf_review':'pending'}

from daily_skill_research.execution import run_command
from model_client import post_chat, extract_text

NATURAL_ARGS = {'title', 'section', 'subsection', 'subsubsection', 'paragraph', 'caption',
                'emph', 'textbf', 'textit', 'texttt', 'footnote', 'thanks', 'address', 'keywords'}
PROTECTED_ARGS = {'cite', 'citep', 'citet', 'ref', 'eqref', 'label', 'url', 'includegraphics',
                  'bibliography', 'bibliographystyle', 'author', 'email', 'date', 'subjclass'}
STRUCTURAL = {'maketitle', 'centering', 'newpage', 'clearpage', 'smallskip', 'medskip', 'bigskip',
              'noindent', 'item', 'quad', 'qquad', 'hfill', 'par', 'newline', 'vfill'}
ENVIRONMENTS = {'document', 'abstract', 'theorem', 'lemma', 'proof', 'definition', 'remark',
                'corollary', 'proposition', 'figure', 'center', 'enumerate', 'itemize'}
MATH_ENVS = {'equation', 'equation*', 'align', 'align*', 'aligned', 'gather', 'gather*',
             'multline', 'multline*', 'displaymath'}
TOKEN = re.compile(r'PTPROTECTED\d{4}TOKEN')
METADATA_ARGS = {'title', 'thanks', 'address', 'keywords'}
UNSUPPORTED_METADATA = {'subtitle', 'dedicatory', 'dedication', 'affiliation', 'institute',
                        'shorttitle', 'shortauthor', 'subject', 'subjectclass', 'classification'}


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path = Path(path)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def group(text, start, opening='{', closing='}'):
    if start >= len(text) or text[start] != opening:
        raise ValueError('expected balanced argument')
    depth = 1
    cursor = start + 1
    while cursor < len(text):
        if text[cursor] == '\\':
            cursor += 2
            continue
        if text[cursor] == opening:
            depth += 1
        if text[cursor] == closing:
            depth -= 1
            if depth == 0:
                return text[start + 1:cursor], cursor + 1
        cursor += 1
    raise ValueError('unbalanced argument')


def subject_class_locale(text):
    """只翻译标准MSC角色名；版本、代码、顺序和分隔符须可逐字保留。"""
    changes=[];replacements=[]
    for match in re.finditer(r'\\subjclass\b',text):
        start=match.end()
        while start<len(text) and text[start].isspace():start+=1
        version='2020'
        if start<len(text) and text[start]=='[':
            version,start=group(text,start,'[',']')
            while start<len(text) and text[start].isspace():start+=1
        if version not in {'1991','2000','2010','2020'}:
            raise ValueError('unsupported MSC version: '+version)
        argument,stop=group(text,start)
        item=r'\d{2}[A-Z]\d{2}(?:\s*\((?:Primary|Secondary)\))?'
        if not re.fullmatch(r'\s*'+item+r'(?:\s*[,;]\s*'+item+r')*\s*',argument):
            raise ValueError('unsupported MSC code or role')
        translated=argument.replace('(Primary)','(主要)').replace('(Secondary)','(次要)')
        replacements.append((start,stop,'{'+translated+'}'))
        changes.append({'source_span':[start,stop],'version':version,'source_argument':argument,
                        'localized_argument':translated,'codes':re.findall(r'\d{2}[A-Z]\d{2}',argument),
                        'role':'standard_MSC_roles_localized_codes_preserved'})
    for start,stop,value in reversed(replacements):text=text[:start]+value+text[stop:]
    return text,changes


def visible_date_policy(text,document_class):
    """有限日期身份：空或真实ISO值；动态/自然语句不能整体算保护完成。"""
    dates=[];cursor=0;depth=0
    while cursor<len(text):
        if text[cursor]=='%':
            stop=text.find('\n',cursor);cursor=len(text) if stop<0 else stop+1;continue
        if text[cursor]=='{':depth+=1;cursor+=1;continue
        if text[cursor]=='}':depth-=1;cursor+=1;continue
        if text[cursor]!='\\':cursor+=1;continue
        match=re.match(r'\\([A-Za-z]+|[^A-Za-z])',text[cursor:])
        if not match:raise ValueError('invalid date source syntax')
        command_start=cursor;cursor+=len(match[0])
        if match[1]!='date':continue
        if depth:
            raise ValueError('nested or macro-defined date is not an executable top-level date identity')
        start=cursor
        while start<len(text) and text[start].isspace():start+=1
        value,stop=group(text,start)
        if value.strip():
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
                raise ValueError('visible date must be empty or explicit ISO identity; dynamic/prose date unsupported')
            try:date.fromisoformat(value)
            except ValueError as exc:raise ValueError('invalid ISO date identity') from exc
        dates.append({'source_span':[start,stop],'source_value':value,'source_literal':text[command_start:stop],
                      'document_class':document_class,
                      'role':'explicit_date_identity' if value.strip() else 'explicit_empty_date'})
        cursor=stop
    if len(dates)>1:raise ValueError('multiple date declarations unsupported')
    if not dates and document_class=='article':
        raise ValueError('article implicit today unsupported; declare empty or ISO date identity')
    return dates or [{'role':'amsart_default_no_visible_date','source_value':None,'source_literal':None,
                      'source_span':None,'document_class':document_class}]


def prefix_metadata(prefix, symbol_commands):
    """自然语言metadata的完整参数进入源绑定单元，作者身份参数可含thanks。"""
    units=[];ranges=[]
    for match in re.finditer(r'\\([A-Za-z]+)\b',prefix):
        name=match[1]
        if name in UNSUPPORTED_METADATA:
            raise ValueError('unsupported visible metadata: '+name)
        if name not in METADATA_ARGS or any(a<=match.start()<b for a,b in ranges):continue
        start=match.end()
        while start<len(prefix) and prefix[start].isspace():start+=1
        if start<len(prefix) and prefix[start]=='[':
            raise ValueError('short metadata argument requires explicit review: '+name)
        argument,stop=group(prefix,start)
        ranges.append((start,stop))
        source='{'+argument+'}'
        masked,protected=mask_segment(source,symbol_commands)
        if not re.search('[A-Za-z]{2}',TOKEN.sub('',masked)):
            continue
        units.append({'id':'metadata-'+name+'-'+str(len(units)+1).zfill(4),
                      'metadata_command':name,'source_text':source,'masked_text':masked,
                      'protected':protected,'source_sha256':digest(source),'prefix_range':[start,stop],
                      'role':'complete_natural_language_metadata_argument'})
    return units


def validate_preamble(prefix):
    """只接受有限声明协议；不能把未知可见metadata藏在可信preamble中。"""
    cursor=0
    single={'documentclass','usepackage','pagestyle','theoremstyle','begin',
            'author','email','date','subjclass',*METADATA_ARGS}
    while cursor<len(prefix):
        if prefix[cursor].isspace():cursor+=1;continue
        if prefix[cursor]=='%':
            end=prefix.find('\n',cursor);cursor=len(prefix) if end<0 else end+1;continue
        match=re.match(r'\\([A-Za-z]+\*?)',prefix[cursor:])
        if not match:raise ValueError('unsupported preamble syntax')
        name=match[1].rstrip('*');start=cursor+len(match[0])
        while start<len(prefix) and prefix[start].isspace():start+=1
        if name in single:
            if start<len(prefix) and prefix[start]=='[':
                if name in METADATA_ARGS or name=='author':
                    raise ValueError('short metadata argument requires explicit review: '+name)
                _,start=group(prefix,start,'[',']')
                while start<len(prefix) and prefix[start].isspace():start+=1
            _,cursor=group(prefix,start)
        elif name=='newtheorem':
            _,start=group(prefix,start)
            while start<len(prefix) and prefix[start].isspace():start+=1
            if start<len(prefix) and prefix[start]=='[':_,start=group(prefix,start,'[',']')
            while start<len(prefix) and prefix[start].isspace():start+=1
            _,cursor=group(prefix,start)
            while cursor<len(prefix) and prefix[cursor].isspace():cursor+=1
            if cursor<len(prefix) and prefix[cursor]=='[':_,cursor=group(prefix,cursor,'[',']')
        elif name in {'newcommand','renewcommand','providecommand','DeclareMathOperator','DeclarePairedDelimiter'}:
            _,start=group(prefix,start)
            while start<len(prefix) and prefix[start].isspace():start+=1
            for _ in range(2):
                if start<len(prefix) and prefix[start]=='[':_,start=group(prefix,start,'[',']')
                while start<len(prefix) and prefix[start].isspace():start+=1
            _,cursor=group(prefix,start)
            if name=='DeclarePairedDelimiter':
                while cursor<len(prefix) and prefix[cursor].isspace():cursor+=1
                _,cursor=group(prefix,cursor)
        else:raise ValueError('unsupported preamble command: '+name)


def mask_segment(text, symbol_commands=frozenset(), atom_kinds=None):
    """保留数学和结构的精确字节，命令白名单只适用于正文。"""
    protected = []
    output = []
    kinds = [] if atom_kinds is None else atom_kinds
    def save(value, kind="fixed"):
        token = f'PTPROTECTED{len(protected):04d}TOKEN'
        protected.append(value)
        kinds.append(kind)
        output.append(token)
    cursor = 0
    while cursor < len(text):
        char = text[cursor]
        if char == '%':
            end = text.find('\n', cursor)
            end = len(text) if end < 0 else end
            save(text[cursor:end]); cursor = end; continue
        if char == '$':
            delim = '$$' if text.startswith('$$', cursor) else '$'
            end = text.find(delim, cursor + len(delim))
            if end < 0:
                raise ValueError('unclosed math')
            end += len(delim)
            value=text[cursor:end]
            if delim=="$" and ("$" in value[1:-1] or not value[1:-1].strip()):raise ValueError("invalid independent inline math")
            save(value,"inline_math" if delim=="$" else "display_math"); cursor = end; continue
        if text.startswith(('\\[', '\\('), cursor):
            delim = '\\]' if text[cursor+1] == '[' else '\\)'
            end = text.find(delim, cursor + 2)
            if end < 0: raise ValueError('unclosed display math')
            end += 2; save(text[cursor:end],"inline_math" if delim=="\\)" else "display_math"); cursor = end; continue
        if char == '\\':
            match = re.match(r'\\([A-Za-z]+\*?|[^A-Za-z])', text[cursor:])
            if not match: raise ValueError('invalid command')
            name = match[1]; end = cursor + len(match[0])
            if name in UNSUPPORTED_METADATA:
                raise ValueError('unsupported visible metadata: '+name)
            if name in {'begin', 'end'}:
                environment, end = group(text, end)
                if environment in MATH_ENVS and name == 'begin':
                    closing = '\\end{' + environment + '}'
                    stop = text.find(closing, end)
                    if stop < 0: raise ValueError('unclosed math environment')
                    end = stop + len(closing)
                elif environment not in ENVIRONMENTS:
                    raise ValueError('unsupported environment:' + environment)
                save(text[cursor:end],"display_math" if environment in MATH_ENVS else "fixed"); cursor = end; continue
            if name.rstrip('*') in NATURAL_ARGS:
                name = name.rstrip('*')
                if end < len(text) and text[end] == '[':
                    raise ValueError('short natural-language arguments require explicit review')
                argument, stop = group(text, end)
                save(text[cursor:end+1])
                nested_kinds=[]
                nested, nested_protected = mask_segment(argument, symbol_commands,nested_kinds)
                # 嵌套token重新编号，避免与外层保护片段混淆。
                for i, value in enumerate(nested_protected):
                    old = f'PTPROTECTED{i:04d}TOKEN'
                    new = f'PTNESTED{len(protected):04d}TOKEN'
                    protected.append(value); kinds.append(nested_kinds[i]); nested = nested.replace(old, new)
                output.append(nested)
                save('}'); cursor = stop; continue
            if name == 'href':
                _,url_stop=group(text,end)
                label,stop=group(text,url_stop)
                save(text[cursor:url_stop+1])
                nested_kinds=[]
                nested,nested_protected=mask_segment(label,symbol_commands,nested_kinds)
                for i,value in enumerate(nested_protected):
                    old=f'PTPROTECTED{i:04d}TOKEN';new=f'PTNESTED{len(protected):04d}TOKEN'
                    protected.append(value);kinds.append(nested_kinds[i]);nested=nested.replace(old,new)
                output.append(nested);save('}');cursor=stop;continue
            if name == 'nolinkurl':
                _,end=group(text,end);save(text[cursor:end]);cursor=end;continue
            if name in PROTECTED_ARGS:
                if end < len(text) and text[end] == '[':
                    _, end = group(text, end, '[', ']')
                argument,stop=group(text,end)
                if name=='author' and re.search(r'\\thanks\b',argument):
                    # 作者字节保护；嵌入的完整致谢参数进入同一完整单元。
                    save(text[cursor:end+1]);position=0
                    for thanks in re.finditer(r'\\thanks\b',argument):
                        if thanks.start()<position:continue
                        save(argument[position:thanks.start()])
                        _,thanks_stop=group(argument,thanks.end())
                        nested_kinds=[]
                        nested,nested_protected=mask_segment(argument[thanks.start():thanks_stop],symbol_commands,nested_kinds)
                        for i,value in enumerate(nested_protected):
                            old=f'PTPROTECTED{i:04d}TOKEN';new=f'PTNESTED{len(protected):04d}TOKEN'
                            protected.append(value);kinds.append(nested_kinds[i]);nested=nested.replace(old,new)
                        output.append(nested);position=thanks_stop
                    save(argument[position:]);save('}');cursor=stop;continue
                end=stop
                save(text[cursor:end]); cursor = end; continue
            if name in STRUCTURAL or name in symbol_commands or name in {'\\', '%', '&', '_', '#', '{', '}', ' ', ',', ';', '!'}:
                save(text[cursor:end]); cursor = end; continue
            raise ValueError('unsupported body command:' + name)
        if char in '{}&':
            save(char); cursor += 1; continue
        output.append(char); cursor += 1
    masked = ''.join(output)
    # 归一嵌套token编号只发生在内存中；源字节始终保存在protected列表。
    masked = masked.replace('PTNESTED', 'PTPROTECTED')
    return masked, protected


def source_atom_ledger(source, symbol_commands=frozenset()):
    kinds=[]
    masked,protected=mask_segment(source,symbol_commands,kinds)
    tokens=TOKEN.findall(masked)
    if not len(tokens)==len(kinds)==len(protected):raise ValueError('source atom ledger length mismatch')
    if tokens != [f'PTPROTECTED{i:04d}TOKEN' for i in range(len(protected))]:
        raise ValueError('source atom IDs not unique source order')
    fixed=[token for token,kind in zip(tokens,kinds) if kind!='inline_math']
    region=0;ledger=[]
    for token,kind,value in zip(tokens,kinds,protected):
        ledger.append({'id':token,'kind':kind,'source_bytes_sha256':digest(value),
                       'region':region,'left_fixed':fixed[region-1] if region else None,
                       'right_fixed':fixed[region] if region<len(fixed) else None})
        if kind!='inline_math':region+=1
    return masked,protected,ledger


def bind_source_atoms(unit,symbol_commands):
    masked,protected,ledger=source_atom_ledger(unit['source_text'],symbol_commands)
    if masked!=unit['masked_text'] or protected!=unit['protected']:
        raise ValueError('source parser and unit protection differ')
    unit.update(protection_protocol=PROTECTION_PROTOCOL,protected_atoms=ledger,
                symbol_commands=sorted(symbol_commands))


def verified_atom_ledger(unit):
    if 'protection_protocol' not in unit:
        if 'protected_atoms' in unit:raise ValueError('unversioned source ledger')
        return None
    if unit['protection_protocol']!=PROTECTION_PROTOCOL:raise ValueError('unknown protection protocol')
    masked,protected,ledger=source_atom_ledger(unit['source_text'],unit['symbol_commands'])
    if (unit['source_sha256']!=digest(unit['source_text']) or masked!=unit['masked_text']
        or protected!=unit['protected'] or ledger!=unit.get('protected_atoms')):
        raise ValueError('source-bound atom ledger changed')
    return ledger


def validate_marker_sequence(unit,actual):
    expected=TOKEN.findall(unit['masked_text'])
    if len(set(expected))!=len(expected) or sorted(actual)!=sorted(expected):
        raise ValueError('protected marker IDs missing, duplicated or unknown')
    ledger=verified_atom_ledger(unit)
    if ledger is None:
        if actual!=expected:raise ValueError('legacy protected marker order changed')
    else:
        by_id={row['id']:row for row in ledger}
        fixed=[row['id'] for row in ledger if row['kind']!='inline_math']
        if [token for token in actual if by_id[token]['kind']!='inline_math']!=fixed:
            raise ValueError('fixed structural atom order changed')
        region=0
        for token in actual:
            row=by_id[token]
            if row['kind']=='inline_math':
                if row['region']!=region:raise ValueError('inline math crossed fixed region boundary')
            else:region+=1
    return [{'id':token,'source_index':expected.index(token),'response_index':i}
            for i,token in enumerate(actual) if expected.index(token)!=i]


def unit_system_prompt(unit):
    ledger=verified_atom_ledger(unit)
    if ledger is None:
        return 'Translate the complete academic passage into Simplified Chinese. Preserve every PTPROTECTED token exactly once and in the same order. Return only the translation. Do not introduce TeX syntax.'
    system=SYSTEM_PROMPT+'\nSource-bound atom ledger: '+json.dumps([{k:row[k] for k in ('id','kind','region')} for row in ledger],separators=(',',':'))
    if unit.get('semantic_feedback'):
        feedback=unit['semantic_feedback']
        if feedback['source_sha256']!=unit['source_sha256'] or file_sha(feedback['review_ref']['path'])!=feedback['review_ref']['sha256']:
            raise ValueError('source-bound semantic feedback changed')
        system+='\nIndependent review feedback for this complete source unit: '+feedback['system_feedback']
    return system


def split_units(text):
    """空行界定完整语义段；数学环境跨空行时保留为同一个单元。"""
    begin = re.search(r'\\begin\{document\}', text)
    end = re.search(r'\\end\{document\}', text)
    if not begin or not end or begin.end() >= end.start():
        raise ValueError('single document environment required')
    cls = re.search(r'\\documentclass(?:\[[^]]*\])?\{([^}]+)\}', text[:begin.start()])
    if not cls or cls[1] not in {'article', 'amsart'}:
        raise ValueError('only article and amsart supported')
    if re.search(r'\\(?:write18|openout|read|catcode|input|include|special|directlua)\b', text):
        raise ValueError('execution commands or unresolved includes are unsupported')
    prefix = text[:begin.end()]
    validate_preamble(prefix)
    symbol_commands=set()
    for declaration in re.finditer(r'\\newcommand\{\\([A-Za-z]+)\}\{',prefix):
        replacement,_=group(prefix,declaration.end()-1)
        plain=re.sub(r'\\[A-Za-z]+','',replacement)
        plain=re.sub(r'[0-9.]+(?:pt|em|ex|cm|mm|in)', '', plain)
        if not re.search('[A-Za-z]',plain):symbol_commands.add(declaration[1])
    metadata_units=prefix_metadata(prefix,symbol_commands)
    _,classification_audit=subject_class_locale(text)
    date_audit=visible_date_policy(text,cls[1])
    body = text[begin.end():end.start()]
    if '\\begin{thebibliography}' in body:
        start = body.index('\\begin{thebibliography}')
        finish = body.find('\\end{thebibliography}', start)
        if finish < 0: raise ValueError('unclosed bibliography')
        finish += len('\\end{thebibliography}')
        bibliography = body[start:finish]
        body = body[:start] + '\\bibliography{PT_BIBLIOGRAPHY_ATOM}' + body[finish:]
    else:
        bibliography = None
    # 保护跨空行数学环境，避免段落切割破坏公式身份。
    math_atoms = []
    pattern = r'\\begin\{(' + '|'.join(re.escape(v) for v in MATH_ENVS) + r')\}.*?\\end\{\1\}'
    def math_save(match):
        math_atoms.append(match[0]); return f'\\url{{PT_MATH_ATOM_{len(math_atoms)-1}}}'
    body = re.sub(pattern, math_save, body, flags=re.S)
    units = []
    pieces = re.split(r'(\n\s*\n)', body)
    for i in range(0, len(pieces), 2):
        for n, value in enumerate(math_atoms):
            pieces[i] = pieces[i].replace(f'\\url{{PT_MATH_ATOM_{n}}}', value)
        if bibliography:
            pieces[i] = pieces[i].replace('\\bibliography{PT_BIBLIOGRAPHY_ATOM}', bibliography)
            if bibliography in pieces[i]:
                # 完整文献表保留英文；它不能混入待译正文单元。
                if pieces[i].strip() != bibliography:
                    raise ValueError('bibliography must be a separate source paragraph')
                continue
        masked, protected = mask_segment(pieces[i],symbol_commands)
        for n, value in enumerate(protected):
            m = re.fullmatch(r'\\url\{PT_MATH_ATOM_(\d+)\}', value)
            if m: protected[n] = math_atoms[int(m[1])]
            if value == '\\bibliography{PT_BIBLIOGRAPHY_ATOM}': protected[n] = bibliography
        prose = TOKEN.sub('', masked)
        if re.search('[A-Za-z]{2}', prose):
            identifier = f'unit-{len(units)+1:04d}'
            units.append({'id': identifier, 'source_text': pieces[i], 'masked_text': masked,
                          'protected': protected, 'source_sha256': digest(pieces[i]), 'piece_index': i})
    units=metadata_units+units
    for unit in units:bind_source_atoms(unit,symbol_commands)
    if not units or len(units) > 100: raise ValueError('1–100 complete units required')
    return {'prefix': prefix, 'suffix': text[end.start():], 'pieces': pieces, 'units': units,
            'metadata_units':[u['id'] for u in metadata_units], 'classification_locale':classification_audit,
            'date_policy':date_audit,'protection_protocol':PROTECTION_PROTOCOL,
            'source_sha256': digest(text), 'document_class': cls[1]}


def normalize_markers(unit, translated):
    """有限序列化变体恢复；完整ID、次数与顺序须与源完全相同。"""
    expected = TOKEN.findall(unit['masked_text'])
    variants = re.compile(r'PTPRO(?:PRO)?TECTED(\d{4})_?TOKEN', re.I)
    suspicious = re.compile(r'PT[A-Za-z_]*\d+_?TOKEN', re.I)
    matches = list(variants.finditer(translated))
    if [(m.start(),m.end()) for m in suspicious.finditer(translated)] != [(m.start(),m.end()) for m in matches]:
        raise ValueError('unknown protected marker serialization')
    canonical = [f'PTPROTECTED{m[1]}TOKEN' for m in matches]
    if any(m[0] != value for m,value in zip(matches,canonical)) and canonical != expected:
        raise ValueError('noncanonical serialization requires strict original order')
    validate_marker_sequence(unit,canonical)
    changes = [{'start':m.start(),'end':m.end(),'raw':m[0],'canonical':value}
               for m,value in zip(matches,canonical) if m[0] != value]
    normalized = variants.sub(lambda m:f'PTPROTECTED{m[1]}TOKEN', translated)
    return normalized, changes


def validate_translation(unit, translated):
    if [(m.start(),m.end()) for m in re.finditer(r'PT[A-Za-z_]*\d+_?TOKEN',translated,re.I)]!=[(m.start(),m.end()) for m in TOKEN.finditer(translated)]:
        raise ValueError('unknown canonical protected marker')
    expected = TOKEN.findall(unit['masked_text'])
    validate_marker_sequence(unit,TOKEN.findall(translated))
    if not re.search('[\u3400-\u9fff]', translated):
        raise ValueError('ordinary prose not translated')
    residue = TOKEN.sub('', translated)
    if re.search(r'\\|[{}$%&#]', residue):
        raise ValueError('translation introduced TeX syntax')
    for i, value in enumerate(unit['protected']):
        translated = translated.replace(f'PTPROTECTED{i:04d}TOKEN', value)
    return translated


def reject_symlink_ancestors(path):
    """在resolve前核验词法路径，包含目标本身和所有祖先。"""
    path = Path(path).expanduser().absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('symlink path or ancestor unsupported')
    return path


def generation_parameters(model, fingerprint=None):
    if fingerprint and fingerprint.get('api_contract'):
        from lmstudio_native import CONTRACT_ID,PARAMETERS
        if fingerprint['api_contract']!=CONTRACT_ID:raise ValueError('unknown model API contract')
        return dict(PARAMETERS)
    return {**GENERATION, **({'reasoning_effort':'none'} if model.lower().startswith('qwen') else {})}


def service_identity(fingerprint_path, model, base_url):
    fingerprint = json.loads(Path(fingerprint_path).read_text())
    if fingerprint['model_id'] != model or fingerprint['endpoint'].rstrip('/') != base_url.rstrip('/'):
        raise ValueError('model service differs from frozen identity')
    with urllib.request.urlopen(base_url.rstrip('/') + '/models', timeout=5) as response:
        served = next(row for row in json.load(response)['data'] if row['id'] == model)
    if served != fingerprint['served_configuration']:
        raise ValueError('served model configuration changed')
    stable = lambda row: {key:value for key,value in row.items() if key not in {'state', 'loaded_instances'}}
    identity = {'model_id':model,'endpoint':base_url.rstrip('/'),'served_configuration':served}
    if fingerprint.get('api_contract'):
        endpoint=base_url.rstrip('/').removesuffix('/v1')+'/api/v1/models'
        with urllib.request.urlopen(endpoint,timeout=5) as response:
            native=next(row for row in json.load(response)['models'] if row['key']==fingerprint['native_model_key'])
        instance=next(row for row in native['loaded_instances'] if row['id']==model)
        if stable(native)!=stable(fingerprint['native_service_metadata']) or instance['config']!=fingerprint['instance_config']:
            raise ValueError('native service or instance configuration changed')
        identity.update(api_contract=fingerprint['api_contract'],native_service_metadata=stable(native),instance_config=instance['config'])
    elif 'native_service_metadata' in fingerprint:
        endpoint = base_url.rstrip('/').removesuffix('/v1') + '/api/v0/models'
        with urllib.request.urlopen(endpoint, timeout=5) as response:
            native = next(row for row in json.load(response)['data'] if row['id'] == model)
        if stable(native) != stable(fingerprint['native_service_metadata']):
            raise ValueError('native model service identity changed')
        identity['native_service_metadata'] = stable(native)
    if fingerprint['generation_parameters'] != generation_parameters(model,fingerprint):
        raise ValueError('generation parameters differ from frozen identity')
    if fingerprint.get('transport_contract') != TRANSPORT:
        raise ValueError('transport contract differs from frozen identity')
    return identity


def cache_identity(output, plan, unit, model, base_url, fingerprint_path):
    import model_client
    if plan.get('semantic_feedback_ref'):
        item=plan['semantic_feedback_ref']
        if file_sha(item['path'])!=item['sha256']:raise ValueError('semantic feedback file changed')
    for row in plan['asset_dependencies']:
        if file_sha(row['path']) != row['sha256']:
            raise ValueError('source project dependency changed')
    identity={'plan_sha256':file_sha(output/'latex_plan.json'),
            'source_project':plan['asset_dependencies'], 'unit_source_sha256':unit['source_sha256'],
            'masked_prompt_sha256':digest(unit['masked_text']), 'system_prompt_sha256':digest(unit_system_prompt(unit)),
            'protection_protocol':unit.get('protection_protocol','legacy_strict_order'),
            'protected_atoms':unit.get('protected_atoms'),
            'parameters':generation_parameters(model,json.loads(Path(fingerprint_path).read_text())), 'transport':TRANSPORT,
            'service':service_identity(fingerprint_path, model, base_url),
            'fingerprint_sha256':file_sha(fingerprint_path),
            'implementation':{str(Path(__file__).resolve()):file_sha(__file__),
                              str(Path(model_client.__file__).resolve()):file_sha(model_client.__file__)}}
    if json.loads(Path(fingerprint_path).read_text()).get('api_contract'):
        import lmstudio_native
        identity['implementation'][str(Path(lmstudio_native.__file__).resolve())]=file_sha(lmstudio_native.__file__)
    return identity


def source_project(tex):
    """只展开声明的本地include/input；拒绝越界、符号链接与循环。"""
    tex = reject_symlink_ancestors(tex).resolve(); root = tex.parent; inputs = []
    def visit(path, chain):
        reject_symlink_ancestors(path)
        if not path.is_file() or root not in path.resolve().parents:
            raise ValueError('unsafe or missing include')
        path = path.resolve()
        if path in chain or len(inputs) >= 20 or path.stat().st_size > 2*1024**2:
            raise ValueError('include cycle or source budget exceeded')
        text = path.read_text(encoding='utf-8')
        inputs.append({'path':str(path),'sha256':file_sha(path)})
        def expand(match):
            relative=Path(match[1])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('include outside source project')
            child=path.parent/relative
            if not child.suffix: child=child.with_suffix('.tex')
            return visit(child, [*chain,path])
        return re.sub(r'\\(?:input|include)\{([^}]+)\}',expand,text)
    return visit(tex,[]),inputs


def bind_semantic_feedback(plan,path):
    path=reject_symlink_ancestors(path).resolve()
    packet=json.loads(path.read_text())
    if set(packet)!={'protocol','units'} or packet['protocol']!='source_bound_semantic_feedback_v1':
        raise ValueError('unknown semantic feedback protocol')
    seen=set()
    for row in packet['units']:
        if set(row)!={'source_sha256','review_ref','system_feedback'} or row['source_sha256'] in seen:
            raise ValueError('invalid or duplicate semantic feedback binding')
        matches=[u for u in plan['units'] if u['source_sha256']==row['source_sha256']]
        if len(matches)!=1 or not isinstance(row['system_feedback'],str) or not row['system_feedback'].strip():
            raise ValueError('feedback must bind one complete source unit')
        evidence=row['review_ref']
        if set(evidence)!={'path','sha256'} or file_sha(evidence['path'])!=evidence['sha256']:
            raise ValueError('semantic review identity changed')
        matches[0]['semantic_feedback']=row
        seen.add(row['source_sha256'])
    plan['semantic_feedback_ref']={'path':str(path),'sha256':file_sha(path)}


def prepare(tex, output, feedback_path=None):
    tex = reject_symlink_ancestors(tex).resolve(); output = reject_symlink_ancestors(output).resolve()
    text, dependencies = source_project(tex)
    parsed = split_units(text)
    if feedback_path:
        bind_semantic_feedback(parsed,feedback_path)
    output.mkdir(parents=True, exist_ok=False)
    if any(path.is_symlink() for path in tex.parent.rglob('*')):
        raise ValueError('source project symlink unsupported')
    asset_files=[path for path in tex.parent.rglob('*') if path.is_file()]
    if len(asset_files)>100 or sum(path.stat().st_size for path in asset_files)>16*1024**2:
        raise ValueError('source project asset budget exceeded')
    assets=[{'path':str(path),'sha256':file_sha(path)} for path in asset_files]
    shutil.copytree(tex.parent, output / 'paper_source', ignore=shutil.ignore_patterns('*.aux', '*.log', '*.out', '*.xdv'))
    (output / 'units').mkdir()
    parsed.update(schema_version=1, status='prepared_candidate', input_tex={'path': str(tex), 'sha256': file_sha(tex)},
                  main_tex=tex.name, dependencies=dependencies, asset_dependencies=assets,
                  producer='independent_latex', model_calls=0,
                  human_accepted=False, strict_delivery=False)
    _,_,parsed['class_locale']=class_locale(parsed['prefix'],parsed['document_class'])
    write_new(output / 'latex_plan.json', parsed)
    return {'status': 'prepared_candidate', 'units': [u['id'] for u in parsed['units']]}


def translate_one(output, unit_id, model, base_url, fingerprint_path):
    output = Path(output).resolve(); plan = json.loads((output / 'latex_plan.json').read_text())
    unit = next(u for u in plan['units'] if u['id'] == unit_id)
    identity = cache_identity(output, plan, unit, model, base_url, fingerprint_path)
    path = output / 'units' / (unit_id + '.json')
    if path.exists():
        cached = json.loads(path.read_text())
        if cached.get('cache_identity') != identity:
            raise ValueError('cached unit identity changed')
        validate_translation(unit, cached['masked_translation'])
        return {'status': 'cached', 'unit': unit_id}
    journal=output/'units'/(unit_id+'.transport.jsonl')
    with journal.open('x') as stream:
        stream.write(json.dumps({'phase':'frozen','cache_identity':identity,'transport':TRANSPORT})+'\n')
    def record(event):
        with journal.open('a') as stream:stream.write(json.dumps(event)+'\n')
    def interrupted(signum, frame):raise SystemExit(128+signum)
    previous=signal.signal(signal.SIGTERM,interrupted)
    try:
        fingerprint=json.loads(Path(fingerprint_path).read_text())
        if fingerprint.get('api_contract'):
            from lmstudio_native import post_native
            response=post_native(base_url=base_url,model=model,system=unit_system_prompt(unit),source=unit['masked_text'],attempt_callback=record)
        else:
            response = post_chat(endpoint=base_url.rstrip('/')+'/chat/completions', model=model,
            system_prompt=unit_system_prompt(unit),
            user_input=unit['masked_text'], provider='openai_compatible',**TRANSPORT,
            attempt_callback=record,max_tokens=GENERATION['max_tokens'], temperature=GENERATION['temperature'],
            extra_body={key:value for key,value in generation_parameters(model).items() if key not in {'max_tokens','temperature'}})
    finally:signal.signal(signal.SIGTERM,previous)
    write_new(output/'units'/(unit_id+'.raw.json'),{'source_sha256':unit['source_sha256'],
              'model':model,'base_url':base_url,'cache_identity':identity,'response':response,'quality_accepted':False})
    if fingerprint.get('api_contract'):
        from lmstudio_native import native_text
        translated=native_text(response,model)
    else:translated = extract_text(response)
    normalized, normalization = normalize_markers(unit, translated)
    actual = validate_translation(unit, normalized)
    write_new(path, {'schema_version':1, 'status':'translated_candidate', 'unit':unit_id,
        'source_sha256':unit['source_sha256'], 'model':model, 'cache_identity':identity, 'response':response,
        'masked_translation':normalized, 'translation':actual, 'protected_marker_normalization':normalization,
        'protected_atom_permutation':validate_marker_sequence(unit,TOKEN.findall(normalized)),
        'semantic_accepted':False, 'human_accepted':False})
    return {'status':'translated_candidate', 'unit':unit_id}


def generation_accounting(output, units):
    """按实际请求事件计量；完成单元数不代替模型调用数。"""
    journals = set()
    for unit in units:
        initial = Path(output)/'units'/(unit['id']+'.transport.jsonl')
        if not initial.is_file():
            return {'model_calls': None, 'model_request_attempts': None,
                    'accounting_status': 'unknown_missing_transport_events'}
        journals.add(initial)
        row = json.loads((Path(output)/'units'/(unit['id']+'.json')).read_text())
        if row.get('repair_raw_ref'):
            raw = row['repair_raw_ref']
            path = reject_symlink_ancestors(Path(raw['path']))
            if file_sha(path) != raw['sha256']:
                raise ValueError('repair raw identity changed during accounting')
            journal = path.parent/'transport.jsonl'
            if not journal.is_file():
                return {'model_calls': None, 'model_request_attempts': None,
                        'accounting_status': 'unknown_missing_repair_transport_events'}
            journals.add(journal)
    attempts = completed = 0
    reviewed_units = []
    for unit in units:
        row = json.loads((Path(output)/'units'/(unit['id']+'.json')).read_text())
        if row.get('reviewed_correction'):
            from latex_unit_review import verify_reviewed_unit
            evidence = verify_reviewed_unit(output, None, unit, row)
            reviewed_units.append({'unit':unit['id'], **evidence})
    refs = []
    for path in sorted(journals):
        reject_symlink_ancestors(path)
        events = [json.loads(line) for line in path.read_text().splitlines()]
        attempts += sum(event.get('phase') == 'start' for event in events)
        completed += sum(event.get('phase') == 'success' for event in events)
        refs.append({'path': str(path), 'sha256': file_sha(path)})
    return {'model_calls': completed, 'model_request_attempts': attempts,
            'accounting_status': 'observed_transport_events', 'transport_refs': refs,
            'operator_reviewed_unit_count':len(reviewed_units), 'operator_reviewed_units':reviewed_units}


def cjk_font_support(cjk_font, cjk_emphasis_font="Kaiti SC"):
    if not all(re.fullmatch(r'[A-Za-z0-9 ._-]+', name) for name in (cjk_font,cjk_emphasis_font)):
        raise ValueError('invalid CJK main/emphasis font name')
    if cjk_font == cjk_emphasis_font:
        raise ValueError('CJK emphasis requires a separately declared typeface')
    return '\\usepackage{fontspec}\n\\usepackage{xeCJK}\n\\setCJKmainfont[ItalicFont={'+cjk_emphasis_font+'}]{'+cjk_font+'}\n'


def compile_project(output, cjk_font, source_pdf=None, cjk_emphasis_font="Kaiti SC"):
    output = Path(output).resolve(); plan = json.loads((output/'latex_plan.json').read_text())
    if any(file_sha(row['path']) != row['sha256'] for row in plan['asset_dependencies']):
        raise ValueError('source TeX dependency changed')
    pieces = plan['pieces']; prefix = plan['prefix'];prefix_replacements=[]
    for unit in plan['units']:
        row = json.loads((output/'units'/(unit['id']+'.json')).read_text())
        if row['source_sha256'] != unit['source_sha256']: raise ValueError('unit source changed')
        if row.get('reviewed_correction'):
            from latex_unit_review import verify_reviewed_unit
            verify_reviewed_unit(output, plan, unit, row)
        value = validate_translation(unit,row['masked_translation'])
        if 'prefix_range' in unit:
            start,stop=unit['prefix_range'];prefix_replacements.append((start,stop,value))
        else: pieces[unit['piece_index']] = value
    for start,stop,value in sorted(prefix_replacements,reverse=True):prefix=prefix[:start]+value+prefix[stop:]
    prefix,locale_commands,locale_audit=class_locale(prefix,plan['document_class'])
    support = cjk_font_support(cjk_font,cjk_emphasis_font)
    prefix = prefix.replace('\\begin{document}',support+'\\begin{document}\n'+locale_commands+'\n')
    destination = output/'paper_cn'
    shutil.copytree(output/'paper_source',destination)
    final_text,classification_audit=subject_class_locale(prefix+''.join(pieces)+plan['suffix'])
    target = destination/plan['main_tex'];target.write_text(final_text,encoding='utf-8')
    compiler = shutil.which('xelatex')
    if not compiler: raise ValueError('xelatex missing')
    commands=[]
    for i in range(2):
        outcome=run_command([compiler,'-no-shell-escape','-interaction=nonstopmode','-halt-on-error',target.name],
            operation=f'independent-latex-compile-{i+1}',cwd=destination,timeout_seconds=45,
            receipt_dir=output/'compile_receipts')
        commands.append(outcome.as_dict())
        if not outcome.success:
            write_new(output/'latex_result.json',{'status':'blocked','stage':'compile','commands':commands})
            return {'status':'blocked','stage':'compile'}
    pdf=target.with_suffix('.pdf')
    if not pdf.is_file(): raise ValueError('compiled PDF missing')
    result={'schema_version':1,'status':'candidate','actual_render_source':'latex_direct_independent',
            'translated_pdf':{'path':str(pdf),'sha256':file_sha(pdf)},'translated_tex':{'path':str(target),'sha256':file_sha(target)},
            'plan':{'path':str(output/'latex_plan.json'),'sha256':file_sha(output/'latex_plan.json')},
            'commands':commands,'complete_units':len(plan['units']),
            **generation_accounting(output, plan['units']),
            'class_locale':locale_audit,
            'cjk_emphasis':{'protocol':'limited_article_amsart_cjk_emphasis_v1','main_font':cjk_font,'italic_role_font':cjk_emphasis_font,'adaptation':'CJK emphasis uses separate declared typeface; Latin italic unchanged'},
            'classification_locale':classification_audit,'metadata_units':plan['metadata_units'],
            'date_policy':plan['date_policy'],
            'human_accepted':False,'strict_delivery':False,'fallback_used':False}
    if source_pdf:
        from qa_pipeline import attach_pipeline_quality
        quality_manifest = {'status':'candidate','actual_render_source':'latex_direct_independent',
                            'input_pdf':str(Path(source_pdf).resolve()),'outputs':{'translated_pdf':str(pdf)}}
        attach_pipeline_quality(quality_manifest, source=Path(source_pdf).resolve(), output_dir=output)
        write_new(output/'render_manifest.json',quality_manifest)
        result['comprehensive_quality_ref']={'path':str(output/'comprehensive_quality.json'),
                                             'sha256':file_sha(output/'comprehensive_quality.json')}
    write_new(output/'latex_result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','translate','compile'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--tex',type=Path)
    parser.add_argument('--unit')
    parser.add_argument('--model')
    parser.add_argument('--base-url')
    parser.add_argument('--cjk-font',default='Songti SC')
    parser.add_argument('--cjk-emphasis-font',default='Kaiti SC')
    parser.add_argument('--source-pdf',type=Path)
    parser.add_argument('--model-fingerprint',type=Path)
    parser.add_argument('--semantic-feedback',type=Path,help='Source-SHA-bound complete-unit independent review feedback; no target patch')
    args=parser.parse_args()
    if args.action == 'translate' and (not args.model or not args.base_url):
        parser.error('translate需要显式--model和--base-url')
    if args.action=='prepare': result=prepare(args.tex,args.output,args.semantic_feedback)
    elif args.action=='translate': result=translate_one(args.output,args.unit,args.model,args.base_url,args.model_fingerprint)
    else: result=compile_project(args.output,args.cjk_font,args.source_pdf,args.cjk_emphasis_font)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 1 if result['status']=='blocked' else 0


if __name__=='__main__':
    raise SystemExit(main())
