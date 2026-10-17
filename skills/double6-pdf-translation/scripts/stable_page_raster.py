"""正式稳定渲染接口：保留原get_pixmap默认值及dpi接口；接口采用不授予成品质检通过。"""
import fitz

def stable_get_pixmap(page, *, matrix=fitz.Identity, dpi=None, colorspace=fitz.csRGB,
                      clip=None, alpha=False, annots=True):
    if not isinstance(page, fitz.Page) or page.parent is None or page.parent.is_closed:
        raise ValueError('stable_raster_requires_live_page')
    if not callable(getattr(fitz.TOOLS, 'store_shrink', None)):
        raise RuntimeError('stable_raster_store_reset_unavailable')
    fitz.TOOLS.store_shrink(100)
    return page.get_pixmap(matrix=matrix, dpi=dpi, colorspace=colorspace,
                          clip=clip, alpha=alpha, annots=annots)
