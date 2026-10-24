"""测试辅助（非 pytest 用例）：在隔离 HOME 的子进程里用 vendored PDFMathTranslate-next 的真实配置解析、
真实 OpenAITranslator / CLITranslator 与真实翻译缓存（cache.v1.db），按本项目实际构建的后端命令执行翻译。

只接受合成标记凭据；只连本机测试 HTTP 服务。用法：
  python credential_probe_backend.py <spec.json>
spec: {"mode": "openai"|"qwen-cli", "base_url":..., "model":..., "openai_timeout": int,
       "texts": [...], "log": path, "result": path}
可选：``extra_args``（追加给 run_pdf_translation 解析器，如 ``["--target-language", "en"]``）、
``custom_system_prompt``、``llm_texts``（经 ``llm_translate`` 发送的完整提示词）、
``pause``（``{"ready": path, "go": path}``：翻译器初始化与健康检查后写 ready，等 go 出现再翻译，用于运行中换上游）。
凭据经环境变量 LOCAL_TRANSLATION_API_KEY 给入（与 run_pdf_translation 入口相同）。
"""
import json
import logging
import os
import sys
import traceback
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SKILL / 'scripts'), str(SKILL / 'vendor/babeldoc'), str(SKILL / 'vendor/pdfmathtranslate_next')]


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text())
    logging.basicConfig(filename=spec['log'], level=logging.DEBUG, force=True,
                        format='%(levelname)s %(name)s %(message)s')
    import run_pdf_translation
    from credential_env import scrub_backend_env
    from pdf_translation_commands import backend_credential_env, build_pdf2zh_command
    source = Path(spec['work']) / 'in.pdf'
    if not source.exists():
        import fitz
        document = fitz.open()
        document.new_page().insert_text((72, 72), 'Hello world.')
        document.save(source)
    args = run_pdf_translation.build_parser().parse_args([
        str(source), '--model', spec['model'], '--base-url', spec['base_url'], '--translator-mode', spec['mode'],
        '--openai-timeout', str(spec.get('openai_timeout', 30)), '--local-max-concurrency', '1',
        *spec.get('extra_args', [])])
    args.custom_system_prompt = spec.get('custom_system_prompt', 'Translate to Simplified Chinese.')
    command = build_pdf2zh_command(args, Path(spec['work']) / 'out')
    # 与 pdf_translation_render._run_render 相同：先清除继承变量，再只经后端原生环境变量给凭据。
    scrub_backend_env(os.environ)
    os.environ.update(backend_credential_env(args))
    sys.argv = ['pdf2zh', *command[2:]]
    result = {'argv': sys.argv, 'outputs': [], 'error': None}
    try:
        from pdf2zh_next.config.main import ConfigManager
        from pdf2zh_next.translator.utils import get_translator
        settings = ConfigManager().initialize_config()
        translator = get_translator(settings)
        result['cache_params'] = translator.cache.translate_engine_params
        result['translator'] = type(translator).__name__
        pause = spec.get('pause')
        if pause:
            import time
            Path(pause['ready']).write_text('ready')
            deadline = time.monotonic() + 60
            while not Path(pause['go']).exists() and time.monotonic() < deadline:
                time.sleep(0.05)
        for text in spec['texts']:
            result['outputs'].append(translator.translate(text))
        for text in spec.get('llm_texts', []):
            result['outputs'].append(translator.llm_translate(text))
        result['translate_call_count'] = translator.translate_call_count
        result['translate_cache_call_count'] = translator.translate_cache_call_count
    except BaseException as exc:  # noqa: BLE001 - 失败路径同样要写入日志/结果供扫描
        cause = getattr(getattr(exc, 'last_attempt', None), 'exception', lambda: None)()
        result['error'] = {'type': type(exc).__name__, 'str': str(exc), 'repr': repr(exc),
                           'cause': repr(cause) if cause else None, 'traceback': traceback.format_exc()}
        logging.getLogger('probe').exception('probe failure: %r cause=%r', exc, cause)
    Path(spec['result']).write_text(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
