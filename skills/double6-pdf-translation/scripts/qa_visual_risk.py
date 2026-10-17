"""风险区必须闭合；裁图按当前PDF重绘核验，标签不构成图像证据。"""
from __future__ import annotations
from stable_page_raster import stable_get_pixmap
import hashlib,math,json
from pathlib import Path
import fitz
from qa_source_contract import file_ref

# 普通正文仍按跨栏、公式、拥挤等风险触发；其它可读源角色逐区核验。
RISK_ROLES={'caption','title','heading','subheading','abstract','metadata','footer',
            'affiliation','author_identity','equation_label','footnote','license',
            'chart_label','table_text','label','page_number','journal_brand',
            'scientific_identity','identifier','bibliographic_record','image',
            'blank_text_record','layout_whitespace'}

def build_risk_regions(source_regions, *, changed_ids=()):
    ids=[r['id'] for r in source_regions]
    if len(set(ids))!=len(ids) or set(changed_ids)-set(ids):raise ValueError('risk_inventory_scope_or_duplicate')
    result=[]
    for region in source_regions:
        reasons=[]
        if region['id'] in changed_ids:reasons.append('changed_region')
        if region.get('role') in RISK_ROLES:reasons.append('role_requires_review')
        for flag in ('cross_column','cross_page','multiple_columns','near_capacity','formula','colored_link','abnormal_whitespace','image_text'):
            if region.get(flag):reasons.append(flag)
        if reasons:result.append({**region,'risk_reasons':reasons,'review_required':True})
    return result

def _rect(bbox):
    if not isinstance(bbox,(tuple,list)) or len(bbox)!=4 or not all(isinstance(x,(float,int)) and math.isfinite(x) for x in bbox):
        raise ValueError('crop_finite_geometry_required')
    r=fitz.Rect(bbox)
    if r.is_empty or not r.is_valid:raise ValueError('crop_nonempty_geometry_required')
    return r

def render_bound_crop(pdf, page_number, bbox, output, *, dpi=144, maximum_pixels=4000000):
    if not 72<=dpi<=200 or not 1<=maximum_pixels<=8000000:raise ValueError('crop_resource_bound')
    identity=file_ref(pdf);rect=_rect(bbox)
    with fitz.open(pdf) as doc:
        if type(page_number) is not int or not 1<=page_number<=len(doc):raise ValueError('crop_page_outside_pdf')
        page=doc[page_number-1]
        if not page.rect.contains(rect):raise ValueError('crop_outside_page')
        if math.ceil(rect.width*dpi/72)*math.ceil(rect.height*dpi/72)>maximum_pixels:raise ValueError('crop_pixel_limit')
        image=stable_get_pixmap(page, matrix=fitz.Matrix(dpi/72,dpi/72),clip=rect,alpha=False)
        pixel_digest=hashlib.sha256(image.samples).hexdigest();data=image.tobytes('png')
    if file_ref(pdf)!=identity:raise ValueError('crop_pdf_changed')
    with Path(output).open('xb') as stream:stream.write(data)
    return {'pdf':identity,'page':page_number,'bbox':list(rect),'dpi':dpi,'image':file_ref(output),
            'pixel_sha256':pixel_digest,'dimensions':[image.width,image.height],
            'renderer':fitz.VersionBind,'maximum_pixels':maximum_pixels}


class _CropAuditSession:
    """仅本次close调用复用成功像素核验，不跨调用继承视觉结论。

    每个PDF/PNG首次核对SHA；每次使用核对inode、大小、mtime/ctime；
    调用结束再次核对全部SHA。只缓存完整相同crop描述的像素核验，
    不缓存区域是否完整、审校身份、标准或视觉决定。
    """
    def __init__(self):
        self.files = {}
        self.pixel_checks = set()
        self.pixel_checks_performed = 0

    @staticmethod
    def signature(path):
        info = Path(path).stat()
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def matches(self, identity):
        path = identity["path"]
        signature = self.signature(path)
        if path in self.files:
            expected, previous = self.files[path]
            return expected == identity and previous == signature
        if file_ref(path) != identity or self.signature(path) != signature:
            return False
        self.files[path] = (dict(identity), signature)
        return True

    def stable_at_end(self):
        changed = []
        for path, (identity, signature) in self.files.items():
            try:
                if self.signature(path) != signature or file_ref(path) != identity or self.signature(path) != signature:
                    changed.append(path)
            except (OSError, ValueError, TypeError):
                changed.append(path)
        return changed

    @staticmethod
    def key(crop):
        return hashlib.sha256(json.dumps(crop, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def audit_crop(region, crop, *, side, _session=None):
    """当前PDF、区域位置及实际PNG像素三者一致；源/译两侧分别检查。"""
    issues=[]
    def issue(rule):issues.append({'id':region['id'],'side':side,'rule':rule})
    try:
        matches = _session.matches if _session is not None else lambda identity: file_ref(identity['path']) == identity
        if crop['pdf']!=region[side] or not matches(crop['pdf']) or not matches(crop['image']):
            issue('crop_current_identity_mismatch')
        rect=_rect(crop['bbox']);required=_rect(region[side+'_bbox'])
        if crop['page']!=region[side+'_page'] or not rect.contains(required):issue('crop_omits_expected_region')
        if type(crop['page']) is not int or crop['page']<1:issue('crop_page_outside_pdf')
        if crop['renderer']!=fitz.VersionBind:issue('crop_renderer_changed')
        if not 72<=crop['dpi']<=200 or math.ceil(rect.width*crop['dpi']/72)*math.ceil(rect.height*crop['dpi']/72)>4000000:
            issue('crop_resource_bound_invalid')
        pixel_key = _session.key(crop) if _session is not None else None
        if not issues and (_session is None or pixel_key not in _session.pixel_checks):
            if _session is not None:
                _session.pixel_checks_performed += 1
            with fitz.open(crop['pdf']['path']) as doc:
                page=doc[crop['page']-1]
                if not page.rect.contains(rect):issue('crop_outside_current_page')
                else:
                    expected=stable_get_pixmap(page, matrix=fitz.Matrix(crop['dpi']/72,crop['dpi']/72),clip=rect,alpha=False)
                    actual=fitz.Pixmap(crop['image']['path'])
                    if [actual.width,actual.height]!=crop['dimensions'] or [expected.width,expected.height]!=crop['dimensions'] or actual.n!=expected.n:
                        issue('crop_actual_dimensions_or_channels')
                    elif hashlib.sha256(actual.samples).hexdigest()!=crop['pixel_sha256'] or actual.samples!=expected.samples:
                        issue('crop_pixels_do_not_match_frozen_pdf_region')
        if not issues and _session is not None:
            _session.pixel_checks.add(pixel_key)
    except (KeyError,ValueError,OSError,TypeError,RuntimeError,IndexError):issue('crop_evidence_unverified')
    return {'status':'fail' if issues else 'pass','issues':issues,'quality_pass':False}

def close_visual_risks(regions, reviews, *, source_ref, target_ref, standard_sha256, producer_id):
    by_id={r['id']:r for r in reviews};issues=[];pending=[];session=_CropAuditSession()
    if len(by_id)!=len(reviews) or set(by_id)-{r['id'] for r in regions}:issues.append({'rule':'visual_review_scope_or_duplicate'})
    for region in regions:
        review=by_id.get(region['id'])
        if not review:pending.append({'id':region['id'],'rule':'mandatory_visual_region_not_reviewed'});continue
        if review.get('source')!=source_ref or review.get('target')!=target_ref or review.get('standard_sha256')!=standard_sha256:
            pending.append({'id':region['id'],'rule':'visual_identity_or_standard_changed'});continue
        if not review.get('reviewer_id') or review['reviewer_id']==producer_id:
            pending.append({'id':region['id'],'rule':'independent_visual_reviewer_required'});continue
        for side in ('source','target'):
            result=audit_crop(region,review.get(side+'_crop',{}),side=side,_session=session)
            issues.extend(result['issues'])
        decision=review.get('decision')
        if decision=='fail':issues.append({'id':region['id'],'rule':'visual_reviewer_rejected_region'})
        elif decision!='pass' or not review.get('rationale'):
            pending.append({'id':region['id'],'rule':'visual_decision_unverified'})
    issues.extend({'rule':'crop_identity_changed_during_review','path':path} for path in session.stable_at_end())
    return {'status':'fail' if issues else 'unverified' if pending else 'pass','issues':issues,'pending':pending,
            'required_regions':len(regions),'reviewed_regions':len(reviews),'pixel_checks_performed':session.pixel_checks_performed,'quality_pass':False}
