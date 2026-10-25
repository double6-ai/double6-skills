# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pdf translation cli：从原入口拆出的同一实现。"""
from __future__ import annotations
from run_pdf_translation_context import *

from model_profiles import request_concurrency_from_env

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the strong PDF-first paper translation pipeline.")
    parser.add_argument("input_pdf", help="Input PDF path.")
    parser.add_argument("--output-dir", help="Output artifact directory. Defaults to <pdf-stem>-zh.")
    parser.add_argument('--quality-review', type=Path, help='授权独立复核的完整综合packet；必须同时冻结SHA。')
    parser.add_argument('--quality-review-sha256', help='独立packet的冻结SHA256。')
    parser.add_argument('--adaptive-plan', type=Path,
                        help='显式候选：渲染已冻结结构计划；保留LaTeX优先路由和人工验收门。')
    parser.add_argument("--pdf2zh-binary", help="pdf2zh executable path. Defaults to PATH lookup.")
    parser.add_argument(
        "--pdf2zh-backend",
        choices=["vendored", "path"],
        default=os.environ.get("PAPER_TRANSLATION_PDF2ZH_BACKEND", DEFAULT_PDF2ZH_BACKEND),
        help="PDFMathTranslate-next backend source. Default uses the copy vendored inside this skill.",
    )
    parser.add_argument("--model", default=os.environ.get("LOCAL_TRANSLATION_MODEL"))
    parser.add_argument("--base-url", default=os.environ.get("LOCAL_TRANSLATION_BASE_URL"))
    parser.add_argument("--api-key", default=os.environ.get("LOCAL_TRANSLATION_API_KEY", DEFAULT_API_KEY),
                        help="兼容保留：会出现在本进程 argv。请改用环境变量 LOCAL_TRANSLATION_API_KEY；"
                             "回环地址未给时用 local-no-auth 占位，远端未给时启动子进程前报 remote_backend_requires_explicit_api_key。")
    parser.add_argument("--translator-mode", choices=["auto", "openai", "qwen-cli"], default=os.environ.get("PDF_TRANSLATION_TRANSLATOR_MODE", DEFAULT_TRANSLATOR_MODE))
    parser.add_argument('--translation-transport',choices=['openai_compatible','lmstudio_native_chat_v1'],default='openai_compatible',help='显式native启用源段落代理与无历史reasoning:off合同；默认保留OpenAI协议。')
    parser.add_argument(
        "--hymt-compat-proxy",
        choices=["auto", "on", "off"],
        default=os.environ.get("PAPER_TRANSLATION_HYMT_COMPAT_PROXY", "auto"),
        help="hy-mt JSON 兼容代理开关；auto 会在 hy-mt OpenAI 模式下自动启用。",
    )
    parser.add_argument(
        "--hymt-compat-proxy-port",
        type=int,
        default=int(os.environ.get("PAPER_TRANSLATION_HYMT_COMPAT_PROXY_PORT", str(DEFAULT_HYMT_COMPAT_PROXY_PORT))),
        help="hy-mt JSON 兼容代理本地端口。",
    )
    parser.add_argument(
        "--local-max-concurrency",
        type=int,
        default=request_concurrency_from_env(),
        help="同时发给模型的请求数。不写时，智谱档案用 8，其它模型用 3。环境变量 LOCAL_MODEL_MAX_CONCURRENCY 同样算写明了。",
    )
    parser.add_argument("--openai-json-mode", action=argparse.BooleanOptionalAction, default=os.environ.get("PDF_TRANSLATION_OPENAI_JSON_MODE", "1") not in {"0", "false", "False"})
    parser.add_argument(
        "--disable-same-text-fallback",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("PAPER_TRANSLATION_DISABLE_SAME_TEXT_FALLBACK", "1") not in {"0", "false", "False"},
        help="默认禁用 BabelDOC 的 same-as-input 原文 fallback；普通英文同文返回会作为 retry/failure 证据记录。",
    )
    parser.add_argument(
        "--ignore-translation-cache",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("PAPER_TRANSLATION_IGNORE_CACHE", "0") in {"1", "true", "True"},
        help="诊断/评测用：向 PDFMathTranslate-next/BabelDOC 传入 --ignore-cache，强制绕过翻译缓存。",
    )
    parser.add_argument(
        "--backend-debug-artifacts",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("PAPER_TRANSLATION_BACKEND_DEBUG_ARTIFACTS", "1") not in {"0", "false", "False"},
        help="默认打开后端 debug 产物，以便回收 translate_tracking.json 生成 item 级 fallback 证据。",
    )
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("PDF_TRANSLATION_TIMEOUT_SEC", "3600")))
    parser.add_argument("--openai-timeout", type=int, default=int(os.environ.get("PDF_TRANSLATION_OPENAI_TIMEOUT_SEC", "7200")))
    parser.add_argument("--openai-reasoning-effort", default=os.environ.get("PDF_TRANSLATION_OPENAI_REASONING_EFFORT", DEFAULT_REASONING_EFFORT))
    parser.add_argument("--openai-send-reasoning-effort", action=argparse.BooleanOptionalAction, default=True,
                        help="把 reasoning_effort 发给模型。智谱 GLM-5.3 不能关闭思考，档案使用它的最低档 low。")
    parser.add_argument("--temperature", type=float, default=float(os.environ.get("PDF_TRANSLATION_TEMPERATURE", str(DEFAULT_HYMT2_TEMPERATURE))))
    parser.add_argument("--cli-max-tokens", type=int, default=int(os.environ.get("PDF_TRANSLATION_CLI_MAX_TOKENS", str(DEFAULT_CLI_MAX_TOKENS))))
    parser.add_argument("--target-language", choices=SUPPORTED_TARGET_LANGUAGES, default="zh",
                        help="目标语言：zh=英译中（默认），en=中译英。")
    parser.add_argument("--custom-system-prompt", default=os.environ.get("PDF_TRANSLATION_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT))
    parser.add_argument("--source-override", "--latex-source", dest="source_override", help="Compatibility/debug override. Normal runs auto-discover LaTeX source and do not require this flag.")
    parser.add_argument('--source-cache-mode',choices=['collect','read'],help='显式当前attempt源请求收集/仅缓存渲染；强制ignore-cache，collector类型排版前停止')
    parser.add_argument('--source-cache-context',type=Path)
    parser.add_argument('--source-cache-context-sha256')
    parser.add_argument('--pdf-backend-only',action='store_true',help='显式电子PDF路线；全部实际源页须为native digital，跳过TeX发现，须同时--latex-render-mode off；默认auto路由保持。')
    parser.add_argument("--latex-source-root", action="append", default=[], help="Additional root to scan for LaTeX source; auto-discovery still applies without this when .tex files are adjacent.")
    parser.add_argument("--no-latex-autodiscovery", dest="disable_latex_autodiscovery", action="store_true", help="Disable LaTeX-first auto source selection for diagnostics.")
    parser.add_argument(
        "--latex-render-mode",
        choices=["auto", "required", "off"],
        default=os.environ.get("PAPER_TRANSLATION_LATEX_RENDER_MODE", DEFAULT_LATEX_RENDER_MODE),
        help="LaTeX source case 的主渲染策略；auto/required 会用 vendored LaTeX 直译编译路径生成主 PDF。",
    )
    parser.add_argument(
        "--latex-project-mode",
        choices=["in-place", "merged"],
        default=os.environ.get("PAPER_TRANSLATION_LATEX_PROJECT_MODE", DEFAULT_LATEX_PROJECT_MODE),
        help="LaTeX direct 项目模式；in-place 保留 paper_source -> paper_cn -> <main>.pdf，merged 保留旧 merge_中文 诊断路径。",
    )
    parser.add_argument("--latex-render-timeout", type=int, default=int(os.environ.get("PAPER_TRANSLATION_LATEX_RENDER_TIMEOUT_SEC", "7200")))
    parser.add_argument("--latex-translate-timeout", type=int, default=int(os.environ.get("PAPER_TRANSLATION_LATEX_TRANSLATE_TIMEOUT_SEC", "7200")))
    parser.add_argument("--latex-compile-timeout", type=int, default=int(os.environ.get("PAPER_TRANSLATION_LATEX_COMPILE_TIMEOUT_SEC", "300")))
    parser.add_argument("--latex-retry-untranslated", type=int, default=int(os.environ.get("PAPER_TRANSLATION_LATEX_RETRY_UNTRANSLATED", "4")))
    parser.add_argument("--latex-auto-repair-passes", type=int, default=int(os.environ.get("PAPER_TRANSLATION_LATEX_AUTO_REPAIR_PASSES", "2")))
    parser.add_argument("--latex-compiler", choices=["lualatex", "xelatex", "pdflatex"], default=os.environ.get("PAPER_TRANSLATION_LATEX_COMPILER"))
    parser.add_argument(
        "--latex-compile-runtime",
        choices=["auto", "local", "docker"],
        default=os.environ.get("PAPER_TRANSLATION_LATEX_COMPILE_RUNTIME", "auto"),
        help="LaTeX direct 编译运行时。auto 优先本机 TeX，缺失时自动使用 Docker TeX Live wrapper。",
    )
    parser.add_argument(
        "--latex-docker-image",
        default=os.environ.get("PAPER_TRANSLATION_TEX_DOCKER_IMAGE", DEFAULT_LATEX_DOCKER_IMAGE),
        help="LaTeX direct 使用 Docker 编译时的 TeX Live 镜像。",
    )
    parser.add_argument("--latex-baseline-pdf", default=os.environ.get("PAPER_TRANSLATION_LATEX_BASELINE_PDF"), help="可选历史/外部最佳 LaTeX PDF，用于生成 latex_baseline_audit.json。")
    parser.add_argument("--latex-skip-glossary", action="store_true", help="调试用：LaTeX 直译路径跳过术语抽取。")
    parser.add_argument("--latex-skip-consistency-review", action="store_true", help="调试用：LaTeX 直译路径跳过一致性复审。")
    parser.add_argument("--skip-pdf-backend-when-latex-direct", action="store_true", help="LaTeX direct case 只重跑 LaTeX 主路径，PDFMathTranslate-next 旧产物仅作为 fallback/对照。")
    parser.add_argument("--post-qa-repair", choices=["auto", "off"], default=os.environ.get("PAPER_TRANSLATION_POST_QA_REPAIR", "auto"), help="是否默认渲染 QA 修复后的可读 PDF。")
    parser.add_argument("--strict-delivery-gates", action="store_true", default=os.environ.get("PAPER_TRANSLATION_STRICT_DELIVERY_GATES", "0") in {"1", "true", "True"}, help="启用评测级交付 gate；warn 级问题也会把主交付标为 partial。")
    parser.add_argument(
        "--pdf-layout-profile",
        choices=["auto", "default", "toc-safe"],
        default=os.environ.get("PAPER_TRANSLATION_PDF_LAYOUT_PROFILE", "auto"),
        help="PDF 后端版式配置；auto 会在检测到目录页时启用 split-short-lines。",
    )
    parser.add_argument(
        "--visual-check-pages",
        default=os.environ.get("PAPER_TRANSLATION_VISUAL_CHECK_PAGES", "auto"),
        help="视觉检查页码，支持 auto 或 1,2,5,8-10。auto 保持旧的前三页检查。",
    )
    parser.add_argument(
        "--skip-visual-eval",
        action="store_true",
        default=os.environ.get("PAPER_TRANSLATION_SKIP_VISUAL_EVAL", "0") in {"1", "true", "True"},
        help="长报告快速交付模式：跳过 visual_layout、dual_visual 和 paragraph label 评估，只生成明确的 skipped 报告。",
    )
    parser.add_argument(
        "--allow-pdf-direct-text-overlay",
        action="store_true",
        default=os.environ.get("PAPER_TRANSLATION_ALLOW_PDF_DIRECT_TEXT_OVERLAY", "0") in {"1", "true", "True"},
        help="调试用：允许 PDF direct text repair 原地覆盖主 PDF。默认关闭，避免白底 redaction 污染主交付。",
    )
    parser.add_argument(
        "--visual-repair-mode",
        choices=["auto", "off", "candidate"],
        default=os.environ.get("PAPER_TRANSLATION_VISUAL_REPAIR_MODE", "auto"),
        help="可见质量候选层；auto/candidate 只生成候选和人工复核清单，不自动替换标准双语右页。",
    )
    parser.add_argument("--engine-home", help="Shared pdf2zh/BabelDOC asset cache. Defaults to .cache/paper-translation/pdf2zh-home under the repo.")
    parser.add_argument("--allow-cloud-layout", action="store_true", help="Authorize upload to the official MinerU remote parser; credentials alone never activate it.")
    parser.add_argument(
        "--scanned-parser",
        choices=["auto", "rapidocr", "mineru"],
        default=os.environ.get("PAPER_TRANSLATION_SCANNED_PARSER", "auto"),
        help="Scanned-page parser. auto starts with RapidOCR. Clear single-column pages stay there; rotated, multi-column, table, or formula pages escalate to MinerU.",
    )
    parser.add_argument(
        "--mineru-tier",
        choices=["auto", "basic", "standard", "advanced"],
        default=os.environ.get("PAPER_TRANSLATION_MINERU_TIER", "auto"),
        help="MinerU parse tier. auto uses Basic, Standard, then Advanced when the preceding quality gate fails.",
    )
    parser.add_argument(
        "--mineru-runtime",
        choices=["local", "remote"],
        default=os.environ.get("PAPER_TRANSLATION_MINERU_RUNTIME", "local"),
        help="MinerU execution location. remote additionally requires --allow-cloud-layout.",
    )
    parser.add_argument(
        "--emit-mineru-render-candidates",
        action="store_true",
        help="Write MinerU original-layout/reflow PDFs under experimental/; never promotes them to strict delivery.",
    )
    parser.add_argument(
        "--scanned-max-pages",
        type=int,
        default=5,
        help="Bound one scanned run to 1–20 pages (default 5). Raise explicitly only after one-page and <=5-page smoke stages pass.",
    )
    parser.add_argument('--scanned-checkpoint-dir', help='Persistent raw-response checkpoints. Defaults to the workspace scanned-reuse cache; resume in a fresh output directory and rerun QA/rendering.')
    parser.add_argument('--scanned-model-fingerprint', help='SHA-256 of frozen model/provider revision evidence, required when checkpoints are enabled.')
    parser.add_argument('--scanned-parse-checkpoint-dir', help='Persistent per-page raw parser checkpoints; retain original parse evidence and use a fresh output attempt.')
    parser.add_argument('--scanned-parser-fingerprint', help='SHA-256 of frozen parser package/model/service evidence, required for parse checkpoints.')
    parser.add_argument('--mixed-cover-mode', choices=['off', 'translate'], default='off',
                        help='Explicitly treat one image-dominant first page as a cover; remaining pages must all be digital. Experimental candidate only.')
    parser.add_argument('--mixed-max-pages', type=int, default=5,
                        help='Bound an image-cover plus digital-body run to 2–20 pages, default 5; expand after smoke verification.')
    parser.add_argument("--dual", action=argparse.BooleanOptionalAction, default=True, help="Request dual PDF output when supported.")
    parser.add_argument(
        "--bilingual-layout",
        choices=["en-left-zh-right", "backend-default", "off"],
        default=os.environ.get("PAPER_TRANSLATION_BILINGUAL_LAYOUT", "en-left-zh-right"),
        help="Final bilingual PDF layout. Default rebuilds dual PDF as source page left, translated page right (both directions; the value name is historical).",
    )
    parser.add_argument(
        "--bilingual-render-mode",
        choices=["vector", "raster", "pypdf-vector"],
        default=os.environ.get("PAPER_TRANSLATION_BILINGUAL_RENDER_MODE", "pypdf-vector"),
        help="标准双语 PDF 合成模式；pypdf-vector 默认用于兼顾 macOS Preview 兼容性、清晰度和文本层，vector 使用 PyMuPDF Form XObject，raster 仅作最后兼容兜底。",
    )
    parser.add_argument(
        "--bilingual-raster-dpi",
        type=int,
        default=int(os.environ.get("PAPER_TRANSLATION_BILINGUAL_RASTER_DPI", "144")),
        help="--bilingual-render-mode=raster 时的页面栅格化 DPI。",
    )
    parser.add_argument("--pages", help="Optional pdf2zh page range for smoke tests or partial PDF translation.")
    parser.add_argument("--document-term-context", type=Path, default=None,
                        help="分块翻译：整份文档的术语/专名上下文（chunked-candidate 生成并冻结），每块提示词共用。")
    parser.add_argument("--document-term-context-sha256", default=None, help="--document-term-context 的 SHA-256（必填）。")
    parser.add_argument(
        "--route-only",
        action="store_true",
        help="只写 route_manifest.json 后退出；不调用 PDF 后端、不 OCR 写回、不调用 hy-mt。",
    )
    return parser

def main(argv: list[str] | None = None) -> int:
    from pdf_translation_latex_render import discover_latex_source
    from pdf_translation_runtime import run
    args = build_parser().parse_args(argv)
    if args.adaptive_plan:
        if bool(args.quality_review) != bool(args.quality_review_sha256):
            raise ValueError('quality_review_and_frozen_sha_required_together')
        from adaptive_document_renderer import render_plan, sha
        input_pdf = Path(args.input_pdf).resolve()
        if not args.output_dir or args.route_only:
            raise ValueError('adaptive_plan_requires_output_and_render')
        latex, selection = discover_latex_source(input_pdf, args)
        if latex or selection.get('identity_status') == 'ambiguous':
            raise ValueError('adaptive_plan_requires_verified_native_pdf_route')
        plan = json.loads(args.adaptive_plan.read_text())
        identity = plan.get('input_source', {})
        if identity.get('path') != str(input_pdf) or identity.get('sha256') != sha(input_pdf):
            raise ValueError('adaptive_plan_input_identity_mismatch')
        out = Path(args.output_dir).resolve()
        out.mkdir(parents=True, exist_ok=False)
        manifest = render_plan(plan, out/'adaptive.zh.candidate.pdf')
        manifest.update(source_selection=selection,
                        plan={'path':str(args.adaptive_plan.resolve()),'sha256':sha(args.adaptive_plan)})
        from qa_pipeline import attach_pipeline_quality
        attach_pipeline_quality(manifest, source=input_pdf, output_dir=out,
            review_ref={'path':str(args.quality_review.resolve()),'sha256':args.quality_review_sha256} if args.quality_review else None)
        (out/'render_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:v for k,v in manifest.items() if k!='placements'},ensure_ascii=False,indent=2))
        return 0
    manifest = run(args)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
