"""只处理能明确保留业务读法的单元格格式；未知显示规则停止。"""
import math
import re
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from engine import Rejected, parse_xml


DATE_FORMATS = {
    'yyyy-mm-dd': '%Y-%m-%d', 'yyyy/mm/dd': '%Y/%m/%d',
    'mm-dd-yy': '%m-%d-%y', 'yyyy-mm-dd h:mm:ss': '%Y-%m-%d %H:%M:%S',
    'yyyy-mm-dd hh:mm:ss': '%Y-%m-%d %H:%M:%S',
    'h:mm:ss': '%H:%M:%S', 'hh:mm:ss': '%H:%M:%S',
    'h:mm': '%H:%M', 'hh:mm': '%H:%M',
}


def plain(value):
    if isinstance(value, bool): return 'TRUE' if value else 'FALSE'
    if isinstance(value, float):
        if not math.isfinite(value): raise Rejected('单元格数值不是有限数。')
        return str(int(value)) if value.is_integer() else str(value)
    return str(value)


def display(value, fmt):
    """预览与keep使用显示值；导出同时保留原数值和已验证格式。"""
    if fmt in ('General', '@'): return plain(value)
    if fmt in DATE_FORMATS and isinstance(value, (date, datetime, time)):
        return value.strftime(DATE_FORMATS[fmt])
    if isinstance(value, (str, bool)):
        # 数字格式不应静默改变文字；未知格式也可能隐藏文字，因此仍需校验。
        validate_numeric_format(fmt)
        return plain(value)
    if not isinstance(value, (int, float)): raise Rejected('日期或时间的显示格式尚未支持。')
    pattern, symbol, percent = validate_numeric_format(fmt)
    try:
        number = Decimal(str(value)) * (100 if percent else 1)
        if not number.is_finite(): raise InvalidOperation()
        decimals = len(pattern.split('.')[1]) if '.' in pattern else 0
        rounded = number.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
        text = format(rounded, (',' if ',' in pattern else '') + '.' + str(decimals) + 'f')
        if re.fullmatch('0{2,32}', pattern):
            negative = text.startswith('-'); text = ('-' if negative else '') + text.lstrip('-').zfill(len(pattern))
        return symbol + text + ('%' if percent else '')
    except (InvalidOperation, ValueError): raise Rejected('该数值无法按原格式安全显示。')


def validate_numeric_format(fmt):
    symbol = ''
    for prefix in ('"¥"', '"￥"', '"$"', '¥', '￥', '$'):
        if fmt.startswith(prefix): symbol = prefix.strip('"'); fmt = fmt[len(prefix):]; break
    percent = fmt.endswith('%')
    if percent: fmt = fmt[:-1]
    if not re.fullmatch(r'(?:0{1,32}|#,##0)(?:\.0{1,8})?', fmt) or (symbol and percent):
        raise Rejected('单元格含未支持的显示格式；为避免隐藏值暴露或业务读法改变，已停止。请在本机核对原件后选择PDF/图片路线。')
    return fmt, symbol, percent


def hidden_format(fmt):
    return fmt.strip() == ';;;'


def theme_colors(raw):
    if not raw:return {0:'FFFFFF',1:'000000'}
    ns='{http://schemas.openxmlformats.org/drawingml/2006/main}'
    scheme=parse_xml(raw).find('.//'+ns+'clrScheme')
    if scheme is None:raise Rejected('工作簿缺少可解析的主题颜色。')
    colors={}
    for index,name in enumerate(['lt1','dk1','lt2','dk2','accent1','accent2','accent3','accent4','accent5','accent6','hlink','folHlink']):
        item=scheme.find(ns+name)
        if item is not None and len(item)==1:
            child=item[0]
            if child.tag==ns+'srgbClr':colors[index]=child.get('val','').upper()
            elif child.tag==ns+'sysClr':colors[index]=child.get('lastClr','').upper()
    return colors


def resolve_color(color,themes,indexed):
    if color is None or color.type=='auto':return '000000'
    if color.tint:raise Rejected('单元格含色彩调整，当前无法安全判断可见性，已停止。')
    if color.type=='rgb':value=str(color.rgb)[-6:].upper()
    elif color.type=='theme':value=themes.get(color.theme,'')
    elif color.type=='indexed'and 0<=color.indexed<len(indexed):value=str(indexed[color.indexed])[-6:].upper()
    else:value=''
    if not re.fullmatch('[0-9A-F]{6}',value):raise Rejected('单元格颜色引用无法安全解释，已停止。')
    return value


def check_font(cell,themes,indexed):
    font = cell.font
    if font.sz is not None and font.sz <= 0: raise Rejected('单元格含不可见字号，已停止。')
    rgb=resolve_color(font.color,themes,indexed);fill=cell.fill
    if fill.patternType not in (None,'solid'):raise Rejected('单元格含图案填充，当前无法安全判断可见性，已停止。')
    background=resolve_color(fill.fgColor,themes,indexed)if fill.patternType=='solid'else'FFFFFF'
    if background==rgb:raise Rejected('单元格文字与背景同色，当前无法安全判断可见性，已停止。')
