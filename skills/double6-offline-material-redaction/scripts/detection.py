"""仅在本机生成可取消的疑似敏感项；检测不代表已完成脱敏。"""
import math
import re
import unicodedata

import engine
import local_ocr

TYPES = {'name': '姓名', 'phone': '电话', 'email': '邮箱', 'id': '身份证号',
         'bank': '银行卡号', 'address': '地址', 'organization': '机构名称',
         'account': '账号 / 编号', 'passport': '护照 / 通行证', 'date': '出生日期'}
MAX_CANDIDATES = 200


def matches(text):
    # NFKC 对某些字符会展开，逐字建立索引，保证 emoji、全角数字之前的定位正确。
    normalized = ''; indices = []
    for index, char in enumerate(text):
        folded = unicodedata.normalize('NFKC', char)
        normalized += folded; indices.extend([index] * len(folded))
    found = []
    def add(kind, start, end, reason):
        if end <= start:
            return
        a, b = indices[start], indices[end-1]+1
        value = text[a:b].strip()
        if not value or len(value) > 200:
            return
        a += len(text[a:b])-len(text[a:b].lstrip()); b = a+len(value)
        found.append({'type': kind, 'text': value, 'start': a, 'end': b, 'reason': reason})
    def pattern(kind, regex, reason, group=0, flags=0):
        for match in re.finditer(regex, normalized, flags):
            add(kind, *match.span(group), reason)
    pattern('email', r'(?<![\w.+-])[A-Z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?\.[A-Z]{2,63}', '邮箱格式', flags=re.I)
    for match in re.finditer(r'(?<!\d)(?:\+?86[ -]?)?1[3-9](?:[ -]?\d){9}(?!\d)|(?<!\d)(?:\+\d{1,3}[ -])?(?:\(?0\d{2,3}\)?[ -]?)\d{7,8}(?:[ -](?:转|ext\.?)[ -]?\d{1,6})?(?!\d)', normalized, re.I):
        if not engine._ORDER_LABEL.search(normalized[max(0, match.start()-12):match.start()]):
            add('phone', *match.span(), '电话格式')
    pattern('phone', r'(?:电话|手机|联系方式|联系电话|Phone|Mobile|Tel)\s*[:：]?\s*(\+?[\d][\d ()-]{5,22}\d)', '联系电话字段', 1, re.I)
    pattern('id', r'(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)', '身份证号码格式，需人工核对')
    for match in re.finditer(r'(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)', normalized):
        number = re.sub(r'\D', '', match.group())
        if 16 <= len(number) <= 19 and engine._luhn_ok(number) and not (len(number) == 18 and engine._id_check_ok(number)):
            add('bank', *match.span(), '银行卡校验格式')
    label_specs = [
        ('name', r'姓名|联系人|收件人|申请人|持有人|负责人|客户姓名|紧急联系人|Name|Contact', r'[\u3400-\u9fff·]{2,12}|[A-Za-z][A-Za-z .\x27-]{1,60}'),
        ('address', r'家庭住址|通讯地址|联系地址|收件地址|居住地址|住址|地址|Address', r'[^\n\r;；\t]{4,120}'),
        ('organization', r'工作单位|所在单位|单位名称|公司名称|机构名称|学校名称|就读学校|Company|Organization|School', r'[^\n\r;；\t]{2,80}'),
        ('passport', r'护照号(?:码)?|通行证号(?:码)?|Passport(?:\s*(?:No\.?|Number))?', r'[A-Za-z0-9 -]{5,25}'),
        ('account', r'银行卡号|银行账号|账号|账户|学号|工号|社保号|微信号|QQ号|Account(?:\s*(?:No\.?|Number))?', r'[A-Za-z0-9_@.-]{3,40}'),
        ('date', r'出生日期|生日|Date of Birth|DOB', r'\d{2,4}[年/.-]\d{1,2}[月/.-]\d{1,2}日?'),
    ]
    for kind, labels, value in label_specs:
        for match in re.finditer(r'(?:'+labels+r')\s*[:：]\s*('+value+r')', normalized, re.I):
            # 在并排字段、句子尾部截断，避免一项吞掉下一项。
            start, end = match.span(1)
            fragment = normalized[start:end]
            split = re.search(r'\s+(?=(?:电话|手机|邮箱|姓名|地址|性别|年龄|公司|单位|Phone|Email|Address)\s*[:：])|[，,。]', fragment, re.I)
            if split: end = start+split.start()
            add(kind, start, end, '由字段标签判断，请确认')
    pattern('organization', r'[\u3400-\u9fffA-Za-z0-9（）()·]{2,40}(?:有限责任公司|股份有限公司|有限公司|研究院|研究所|委员会|大学|中学|小学|医院|协会|学会)', '机构名称后缀，需人工确认')
    # 证件与扫描件常省略冒号，短姓名字段仍给出候选，避免只认表单标点。
    for match in re.finditer(r'(?:姓名|联系人|收件人|申请人|持有人|负责人)[ \t:：]*([\u3400-\u9fff·]{2,12})', normalized):
        start, end = match.span(1)
        next_label = re.search(r'性别|民族|年龄|出生|电话|住址|地址', normalized[start:end])
        if next_label: end = start+next_label.start()
        add('name', start, end, '姓名字段，需人工确认')
    pattern('address', r'(?:北京市|上海市|天津市|重庆市|[\u3400-\u9fff]{2,3}省[\u3400-\u9fff]{2,6}市)[\u3400-\u9fff0-9]{2,30}(?:区|县|镇|乡|街道)[\u3400-\u9fffA-Za-z0-9-]{2,35}(?:路|街|巷)[0-9一二三四五六七八九十-]{1,12}号(?:[0-9A-Za-z-]{1,10}(?:室|栋|楼))?', '地址结构，需人工确认')
    # 重叠时先保留更明确的类型；同一位置不重复报账号和银行卡。
    priority = {'id': 0, 'bank': 1, 'email': 2, 'phone': 3, 'passport': 4, 'name': 5, 'address': 6, 'organization': 7, 'account': 8, 'date': 9}
    result = []
    for item in sorted(found, key=lambda x: (priority[x['type']], -(x['end']-x['start']), x['start'])):
        if any(item['start'] < old['end'] and old['start'] < item['end'] for old in result):
            continue
        result.append(item)
    return sorted(result, key=lambda x: x['start'])


def text_detection(text):
    groups = {}
    for match in matches(text):
        key = match['type'], match['text']
        groups.setdefault(key, {k: match[k] for k in ('type', 'text', 'reason')})
    # 文本按值替换，预览也标出同值的所有出现，包含没有重复字段标签的地方。
    offsets = [0]
    for char in text: offsets.append(offsets[-1] + (2 if ord(char) > 0xffff else 1))
    for item in groups.values():
        item['spans'] = [{'start': offsets[m.start()], 'end': offsets[m.end()]} for m in re.finditer(re.escape(item['text']), text)]

    candidates = []
    for index, item in enumerate(groups.values()):
        candidates.append({**item, 'id': 'text-'+str(index), 'label': TYPES[item['type']], 'source': 'text', 'page': None, 'rectangles': []})
    return {'status': 'complete', 'candidates': candidates[:MAX_CANDIDATES], 'truncated': len(candidates)>MAX_CANDIDATES, 'warnings': [], 'engine': '本地规则'}


def _native_pdf_lines(data, page_number, size):
    import pdf_preserve
    fitz = pdf_preserve.backend()
    lines = []
    with fitz.open(stream=data, filetype='pdf') as doc:
        page = doc[page_number-1]
        transform = pdf_preserve._display_matrix(page)
        sx, sy = pdf_preserve._pixel_scale(page, size)
        flags = fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES
        for block in page.get_text('rawdict', flags=flags, sort=True)['blocks']:
            for line in block.get('lines', []):
                text = ''; boxes = []
                for span in line['spans']:
                    for char in span['chars']:
                        rect = fitz.Rect(char['bbox']) * transform
                        value = char['c']; text += value
                        boxes.extend([[rect.x0*sx, rect.y0*sy, rect.x1*sx, rect.y1*sy]]*len(value))
                lines.append({'text': text, 'boxes': boxes})
    return lines


def _regions(lines, size, source, page):
    candidates = []
    for line in lines:
        text = line['text']
        for match in matches(text):
            chars = [b for b in line['boxes'][match['start']:match['end']] if b is not None]
            if not chars: continue
            rectangle = [max(0, math.floor(min(b[0] for b in chars)-2)), max(0, math.floor(min(b[1] for b in chars)-2)),
                         min(size[0], math.ceil(max(b[2] for b in chars)+2)), min(size[1], math.ceil(max(b[3] for b in chars)+2))]
            if rectangle[0] >= rectangle[2] or rectangle[1] >= rectangle[3]: continue
            candidates.append({k: match[k] for k in ('type', 'text', 'reason')})
            candidates[-1].update({'rectangles': [rectangle], 'source': source, 'page': page, 'spans': [], 'label': TYPES[match['type']]})
    return candidates


def page_detection(data, kind, page=1):
    import formats
    import pdf_preserve
    if kind == 'pdf':
        sizes = formats.pdf_info(data)
        if type(page) is not int or not 1 <= page <= len(sizes): raise engine.Rejected('检测页码无效。')
        size = sizes[page-1]
        image = formats.pdf_image(data, page-1, sizes)
        candidates = _regions(_native_pdf_lines(data, page, size), size, 'pdf-text', page)
    elif kind == 'image':
        if page != 1: raise engine.Rejected('图片检测页码无效。')
        image = engine.image_source(data); size = image.size; candidates = []
    else:
        raise engine.Rejected('此检测接口只接收图片或 PDF。')
    warnings = []; ocr_engine = None; complete = True
    try:
        recognized = local_ocr.recognize(image)
        ocr_engine = recognized['engine']
        if not any(lang.startswith(('zh', 'chi')) for lang in recognized['languages']):
            warnings.append('本机 OCR 未启用中文语言包，中文图片内容可能漏检。'); complete = False
        candidates.extend(_regions(recognized['lines'], size, 'ocr', page))
    except local_ocr.OcrUnavailable as exc:
        warnings.append(str(exc)); complete = False
    # OCR 与文字层命中同一位置时，优先采用文字层的精确定位。
    unique = []
    for item in candidates:
        box = item['rectangles'][0]
        duplicate = False
        for old in unique:
            other = old['rectangles'][0]
            intersection = max(0, min(box[2], other[2])-max(box[0], other[0])) * max(0, min(box[3], other[3])-max(box[1], other[1]))
            area = min((box[2]-box[0])*(box[3]-box[1]), (other[2]-other[0])*(other[3]-other[1]))
            if item['type']==old['type'] and intersection/max(area,1)>.6:
                duplicate = True; break
        if not duplicate: unique.append(item)
    if kind == 'pdf' and unique:
        try:
            snapped = pdf_preserve.snap_regions(data, page, [item['rectangles'][0] for item in unique[:MAX_CANDIDATES]])
            for item, rectangle in zip(unique, snapped): item['rectangles'] = [rectangle]
        except engine.Rejected:
            complete = False
            warnings.append('部分建议区域无法对齐完整字符，请逐项查看并手动调整。')
            for item in unique: item['selectable'] = False
    for index, item in enumerate(unique[:MAX_CANDIDATES]):
        item['id'] = 'p'+str(page)+'-'+str(index)
    return {'status': 'complete' if complete else 'partial', 'candidates': unique[:MAX_CANDIDATES], 'truncated': len(unique)>MAX_CANDIDATES, 'warnings': warnings, 'engine': (ocr_engine or '仅 PDF 文字层') if kind=='pdf' else (ocr_engine or 'OCR 不可用'), 'page': page}
