"""续译模式只翻译可靠段落，其余区域保留源图；不猜字、不删除原文。"""


def select_lines(record, lines, script_lines, fraction_bars):
    """消化可定位的局部发现；不能定位的结构风险仍保留为页级拒绝。"""
    allowed = {'ocr_low_confidence', 'ocr_resolution_too_low', 'ocr_formula_unsupported'}
    protected = {tuple(line['key'][:2]) for line in lines
                 if line['class'] == 'uncertain' or line.get('math')}
    for suspect in script_lines:
        matches = [line for line in lines if line['bbox_px'] == suspect['bbox_px']]
        if not matches:
            return None
        protected.update(tuple(line['key'][:2]) for line in matches)
    if fraction_bars or any(f['code'] not in allowed for f in record['findings']):
        return None
    groups = {}
    for line in lines:
        key = tuple(line['key'][:2])
        if key in protected:
            groups.setdefault(key, []).append(line)
    record['preserved_regions'] = [
        {'paragraph': list(key), 'bbox_px': [min(l['bbox_px'][0] for l in members),
            min(l['bbox_px'][1] for l in members), max(l['bbox_px'][2] for l in members),
            max(l['bbox_px'][3] for l in members)],
         'reason': 'unreliable_ocr_or_formula', 'action': 'original_image_preserved',
         'source_ocr_for_review_only': '\n'.join(l['text'] for l in members)}
        for key, members in groups.items()]
    for item in record['findings']:
        record.setdefault('warnings', []).append({**item, 'severity': 'warning',
                                                  'action': 'preserve_local_source_and_continue'})
    record['findings'] = []
    return [line for line in lines if line['class'] == 'text' and tuple(line['key'][:2]) not in protected]


def residue_is_preserved(word, regions):
    if not all(k in word for k in ('left', 'top', 'width', 'height')):
        return False
    x, y = word['left'] + word['width'] / 2, word['top'] + word['height'] / 2
    return any(b[0] - 4 <= x <= b[2] + 4 and b[1] - 4 <= y <= b[3] + 4
               for b in (r['bbox_px'] for r in regions))


SCRIPT_INTERFACE = 'internal-module'
SCRIPT_INTERFACE_REASON = '由显式续译OCR模式选择原图保留区域。'
