# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pdf translation paths：从原入口拆出的同一实现。"""
from __future__ import annotations
from run_pdf_translation_context import *

def repo_root() -> Path:
    return __import__("runtime_paths").workspace_root()

def paper_translation_project_root() -> Path:
    configured = os.environ.get("PAPER_TRANSLATION_PROJECT_ROOT", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else repo_root() / path
    return repo_root() / "projects" / "paper-translation"

def paper_translation_run_root() -> Path:
    configured = os.environ.get("PAPER_TRANSLATION_RUN_ROOT", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else repo_root() / path
    return paper_translation_project_root() / "runs" / "daily" / "2026-05-20_paper-translation-literature"

def paper_translation_shared_library_dir() -> Path:
    configured = os.environ.get("PAPER_TRANSLATION_SHARED_LIBRARY_DIR", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else repo_root() / path
    return repo_root() / "shared_resources"

def default_engine_home() -> Path:
    configured = os.environ.get("PAPER_TRANSLATION_ENGINE_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (repo_root() / ".cache" / "paper-translation" / "pdf2zh-home").resolve()

def vendored_pdf2zh_skill_root() -> Path:
    return Path(__file__).resolve().parents[1] / "vendor" / "pdf2zh_skill"

def latex_translation_after_writeback_repair(source: str, translation: str) -> str:
    """返回 LaTeX 写回前实际会进入 TeX 的译文口径。"""
    try:
        vendor_root = vendored_pdf2zh_skill_root()
        if str(vendor_root) not in sys.path:
            sys.path.insert(0, str(vendor_root))
        from pdf2zh_skill.latex_ops import fix_translation

        return str(fix_translation(translation, source))
    except Exception:
        return translation

def vendored_babeldoc_root() -> Path:
    return Path(__file__).resolve().parents[1] / "vendor" / "babeldoc"

def default_output_dir(input_pdf: Path) -> Path:
    return input_pdf.with_name(f"{input_pdf.stem}-zh")

def find_pdf2zh_binary(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    return shutil.which("pdf2zh") or "pdf2zh"

def pdf2zh_command_prefix(args: argparse.Namespace) -> list[str]:
    if getattr(args,'source_cache_mode',None)=='collect':
        if args.pdf2zh_binary or args.pdf2zh_backend!='vendored':raise ValueError('source-only collector requires frozen vendored backend')
        return [sys.executable,str(Path(__file__).with_name('pdf_source_collector_backend.py'))]
    if args.pdf2zh_binary:
        return [find_pdf2zh_binary(args.pdf2zh_binary)]
    if getattr(args, "pdf2zh_backend", DEFAULT_PDF2ZH_BACKEND) == "vendored":
        wrapper = Path(__file__).resolve().with_name("pdf2zh_next_vendor.py")
        return [sys.executable, str(wrapper)]
    return [find_pdf2zh_binary(None)]

def should_use_qwen_cli_adapter(args: argparse.Namespace) -> bool:
    mode = args.translator_mode
    if mode == "qwen-cli":
        return True
    if mode == "openai":
        return False
    return "qwen" in args.model.lower() and ("localhost" in args.base_url or "127.0.0.1" in args.base_url)

def should_enable_hymt_compat_proxy(args: argparse.Namespace) -> bool:
    mode = str(getattr(args, "hymt_compat_proxy", "auto") or "auto")
    if mode == "off":
        if getattr(args,'translation_transport','openai_compatible')=='lmstudio_native_chat_v1':
            raise ValueError('native source-bound adapter cannot be disabled')
        return False
    if getattr(args,'translation_transport','openai_compatible')=='lmstudio_native_chat_v1':
        return True
    if mode == "on":
        return not should_use_qwen_cli_adapter(args)
    return "hy-mt" in str(args.model).lower() and not should_use_qwen_cli_adapter(args)

def pdf_has_toc_like_pages(input_pdf: Path, max_pages: int = 5) -> bool:
    try:
        fitz = visual_layout._load_fitz()
        with fitz.open(str(input_pdf)) as doc:  # type: ignore[attr-defined]
            for page_index in range(min(max_pages, len(doc))):
                lines = visual_layout.normalize_lines(doc[page_index].get_text("text"))
                if visual_layout.looks_like_toc_page(lines):
                    return True
    except Exception:
        return False
    return False

def resolve_pdf_layout_profile(args: argparse.Namespace, input_pdf: Path) -> str:
    profile = str(getattr(args, "pdf_layout_profile", "auto") or "auto")
    if profile in {"default", "toc-safe"}:
        return profile
    return "toc-safe" if pdf_has_toc_like_pages(input_pdf) else "default"

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
