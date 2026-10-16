"""统一保护普通工作台与儿童展示适配器生成的离线 HTML。"""

from .core import ContractError

CSP_POLICY = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data: blob:; font-src data:; manifest-src data:; media-src data: blob:; "
    "connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'"
)


def protect_offline_html(source: str) -> str:
    """在任何资源和脚本之前插入 CSP，不依赖外部 HTTP 响应头。"""
    head_end = source.find('>', source.lower().find('<head'))
    if head_end < 0 or '<head' not in source.lower():
        raise ContractError('离线候选缺少 head，无法安装网络限制')
    policy = f'<meta http-equiv="Content-Security-Policy" content="{CSP_POLICY}">'
    return source[:head_end + 1] + policy + source[head_end + 1:]
