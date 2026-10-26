"""把逐段校对的扫描源文字按具名源坐标重建，供既有 digital_pdf 路线使用。

不执行 OCR 或翻译，不把执行者校对记为用户验收；未通过 OCR 的原件身份继续留在清单中。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def bound(item):
    path = Path(item['path'])
    if reference(path)['sha256'] != item['sha256']:
        raise ValueError('reviewed_source_reference_changed')
    return path


def wrap(text, font, size, width, indent):
    lines, current = [], ''
    for char in text:
        limit = width - indent if not lines else width
        if char == '\n' or (current and font.text_length(current + char, fontsize=size) > limit):
            lines.append(current)
            current = '' if char == '\n' else char
        else:
            current += char
    if current:
        lines.append(current)
    return lines


def rebuild(review_path, output):
    import fitz
    review_path, output = Path(review_path).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('reviewed_source_output_exists')
    review = json.loads(review_path.read_text())
    if review.get('status') != 'executor_reviewed_source' or not review.get('reviewer'):
        raise ValueError('reviewed_source_review_required')
    source = bound(review['original_scan'])
    for item in review.get('evidence_refs', []):
        bound(item)
    fonts = {name: fitz.Font(fontfile=str(bound(item))) for name, item in review['fonts'].items()}
    with fitz.open(source) as original, fitz.open() as result:
        if [page['page'] for page in review['pages']] != list(range(1, len(original) + 1)):
            raise ValueError('reviewed_source_scope_incomplete')
        blocks = []
        for record, source_page in zip(review['pages'], original):
            if record.get('complete_visible_text') is not True or not record.get('blocks'):
                raise ValueError('reviewed_source_complete_page_review_required')
            page = result.new_page(width=source_page.rect.width, height=source_page.rect.height)
            identifiers, boxes = set(), []
            for block in record['blocks']:
                if block['id'] in identifiers or not block['text'].strip():
                    raise ValueError('reviewed_source_block_missing_or_duplicate')
                identifiers.add(block['id'])
                box = fitz.Rect(block['bbox'])
                if box.is_empty or not page.rect.contains(box):
                    raise ValueError('reviewed_source_geometry_invalid')
                if any((box & other).get_area() > .1 for other in boxes):
                    raise ValueError('reviewed_source_blocks_overlap')
                boxes.append(box)
                font = fonts[block['font']]
                size, leading, indent = block['font_size'], block['leading'], block.get('first_line_indent', 0)
                if size <= 0 or leading < size or not 0 <= indent < box.width:
                    raise ValueError('reviewed_source_typography_invalid')
                if any(not font.has_glyph(ord(char)) for char in block['text'] if not char.isspace()):
                    raise ValueError('reviewed_source_glyph_missing')
                lines = wrap(block['text'], font, size, box.width, indent)
                # 按实际字体升降部核对；不为凑页面偷偷缩字或丢行。
                height = (font.ascender - font.descender) * size + leading * (len(lines) - 1)
                if height > box.height + .1:
                    raise ValueError(f'reviewed_source_block_overflow:{block["id"]}:{height:.2f}>{box.height:.2f}')
                writer = fitz.TextWriter(page.rect)
                for index, text in enumerate(lines):
                    width = font.text_length(text, fontsize=size)
                    x = box.x0 + (indent if index == 0 else 0)
                    if block.get('align') == 'center':
                        x = box.x0 + (box.width - width) / 2
                    writer.append((x, box.y0 + font.ascender * size + index * leading), text, font=font, fontsize=size)
                writer.write_text(page)
                blocks.append({'page': record['page'], 'id': block['id'], 'role': block['role'],
                               'bbox': block['bbox'], 'font_size': size, 'lines': len(lines),
                               'source_text': block['text'], 'source_continues': block.get('source_continues', False)})
        output.parent.mkdir(parents=True, exist_ok=True)
        result.save(output, garbage=4, deflate=True)
    manifest = {'protocol': 'reviewed_text_source_v1', 'original_scan': reference(source),
                'review_ref': reference(review_path), 'rebuilt_source': reference(output), 'blocks': blocks,
                'geometry': '保留可视页面物理尺寸；显式把 /Rotate 归零，坐标使用阅读方向的 point。',
                'route': 'executor_reviewed_source_then_digital_pdf', 'automatic_ocr_acceptance': False,
                'human_acceptance': False, 'strict_delivery': False}
    output.with_suffix('.source.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-json', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(rebuild(args.review_json, args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
