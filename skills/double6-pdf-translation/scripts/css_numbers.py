"""CSS长度使用有限十进制，避免微小源浮点被Story误读为科学计数法。"""
import math

def css_number(value):
    number=float(value)
    if not math.isfinite(number) or abs(number)>1_000_000:
        raise ValueError('css_number_bounds')
    result=f'{number:.9f}'.rstrip('0').rstrip('.')
    return '0' if result in ('','-0') else result
