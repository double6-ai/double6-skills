"""中文条款的源编号身份；不推断缺页内容或重新编号。"""
import re
from collections import Counter

_HAN_NUM = '一二三四五六七八九十百千'
_PREFIX = re.compile(rf'^\s*(?P<marker>(?P<section>[{_HAN_NUM}]+)、|[（(](?P<item>[{_HAN_NUM}]+|[1-9]\d{{0,3}})[）)])\s*')
_OUT_PREFIX = re.compile(r'^(?:[（(](?:[1-9]\d{0,3}|[IVXLCDMivxlcdm]+|[一二三四五六七八九十百千]+)[）)]|(?:[1-9]\d{0,3}|[IVXLCDMivxlcdm]+)[.、])\s*')


def chinese_number(text):
    if text.isascii() and text.isdigit():
        return int(text)
    digits = {c: i for i, c in enumerate('零一二三四五六七八九')}
    units = {'十': 10, '百': 100, '千': 1000}
    total, pending, previous_unit = 0, None, 10000
    for char in text:
        if char in digits:
            if pending is not None:
                return None
            pending = digits[char]
        elif char in units and units[char] < previous_unit:
            unit = units[char]
            total += (pending if pending is not None else 1) * unit
            pending, previous_unit = None, unit
        else:
            return None
    return total + (pending or 0)


def cjk_numbering(text):
    match = _PREFIX.match(text or '')
    if not match or not re.search(r'[\u3400-\u9fff]', text[match.end():]):
        return None
    number_text = match['section'] or match['item']
    number = chinese_number(number_text)
    if not number:
        return None
    return {'source_marker': match['marker'], 'number': number,
            'level': 'section' if match['section'] else ('clause' if not number_text.isascii() else 'subitem'),
            'output_marker': f'{number}.' if match['section'] else f'({number})'}


def normalize_cjk_numbering(source, output, target_language):
    """仅规范源段首编号。模型原始回复另留；标签内部文字与正文数字都不改。"""
    numbering = cjk_numbering(source)
    if not numbering or str(target_language).lower() not in {'en', 'en-us', 'en-gb', 'english'}:
        return output
    # 保留模型使用的样式开标签，只替换紧随其后的明确编号。
    tags = re.match(r'^(?:\s*<style\b[^>]*>)*\s*', output, re.I).group(0)
    tail = output[len(tags):]
    match = _OUT_PREFIX.match(tail)
    if not match:
        return output  # 未识别形态交给原有语义审校，不凭猜测删改正文。
    return tags + numbering['output_marker'] + ' ' + tail[match.end():]


def cjk_identifiers(text):
    """中文正文中的拉丁字母数字代码（如类别/型号），区别于普通数字和可翻译词。"""
    if not re.search(r'[\u3400-\u9fff]', text or ''):
        return []
    plain = re.sub(r'<[^>]*>', '', text)
    return re.findall(r'(?<![A-Za-z0-9_])[A-Z]{1,8}\d{1,6}(?:[._-][A-Z0-9]+)*(?![A-Za-z0-9_])', plain)


def missing_cjk_identifiers(source, output, target_language):
    if str(target_language).lower() not in {'en', 'en-us', 'en-gb', 'english'}:
        return []
    expected = Counter(cjk_identifiers(source))
    actual = Counter(re.findall(r'(?<![A-Za-z0-9_])[A-Z]{1,8}\d{1,6}(?:[._-][A-Z0-9]+)*(?![A-Za-z0-9_])',
                               re.sub(r'<[^>]*>', '', output)))
    return list((expected - actual).elements())
