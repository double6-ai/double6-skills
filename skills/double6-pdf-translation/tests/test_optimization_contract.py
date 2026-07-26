from __future__ import annotations

import locale
import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import _subprocess_safe  # noqa: E402
import build_bilingual_pdf  # noqa: E402
import latex_direct_runtime  # noqa: E402
import pdf_translation_artifacts_runtime  # noqa: E402
import pdf_translation_runtime  # noqa: E402
import run_pdf_translation  # noqa: E402
import translation_api_probe  # noqa: E402


class OptimizationContractTests(unittest.TestCase):
    def _require_fitz(self):
        try:
            import fitz  # type: ignore
        except Exception:
            try:
                import pymupdf as fitz  # type: ignore
            except Exception as exc:  # noqa: BLE001
                self.skipTest(f"PyMuPDF unavailable: {exc}")
        return fitz

    def _write_pdf(self, path: Path, label: str) -> None:
        fitz = self._require_fitz()
        doc = fitz.open()
        page = doc.new_page(width=200, height=120)
        page.insert_text((30, 60), label, fontsize=14)
        doc.save(path)
        doc.close()

    def test_subprocess_decode_order_and_empty_output(self) -> None:
        self.assertEqual("中文", _subprocess_safe._decode("中文".encode("utf-8")))
        with mock.patch.object(locale, "getpreferredencoding", return_value="cp1252"):
            self.assertEqual("café", _subprocess_safe._decode("café".encode("cp1252")))
        with mock.patch.object(locale, "getpreferredencoding", return_value="ascii"):
            self.assertEqual("中文", _subprocess_safe._decode("中文".encode("gb18030")))
        self.assertEqual("", _subprocess_safe._decode(None))
        self.assertEqual("", _subprocess_safe._decode(b""))

    def test_run_text_always_returns_strings(self) -> None:
        result = _subprocess_safe.run_text(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write('中文'.encode('utf-8'))"]
        )
        self.assertEqual("中文", result.stdout)
        self.assertIsInstance(result.stderr, str)

    def test_latex_reflow_plan_no_name_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            plan = latex_direct_runtime.build_latex_reflow_plan(
                output_dir=Path(tmpdir),
                estimate={"required_lines_for_page_delta": 8, "translated_line_count": 100},
                summary={},
                eligible_segment_count=5,
            )
        self.assertEqual("review_required", plan["status"])
        self.assertTrue(plan["options"])

    def test_bilingual_vector_layouts_and_deprecated_alias(self) -> None:
        fitz = self._require_fitz()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.pdf"
            translated = root / "translated.pdf"
            self._write_pdf(source, "EN-SOURCE")
            self._write_pdf(translated, "ZH-TARGET")
            for layout, left_label, right_label in [
                ("zh-left-en-right", "ZH-TARGET", "EN-SOURCE"),
                ("en-left-zh-right", "EN-SOURCE", "ZH-TARGET"),
            ]:
                output = root / f"{layout}.pdf"
                manifest = build_bilingual_pdf.build_manifest(
                    source,
                    translated,
                    output,
                    layout=layout,
                    mode="pypdf-vector" if layout == "zh-left-en-right" else "vector",
                )
                self.assertEqual("ok", manifest["status"])
                self.assertEqual(layout.replace("-", "_"), manifest["layout"])
                if layout == "zh-left-en-right":
                    self.assertEqual("vector", manifest["render_mode"])
                    self.assertTrue(manifest["deprecated_render_mode_alias"])
                doc = fitz.open(output)
                page = doc[0]
                midpoint = page.rect.width / 2
                left_text = page.get_text("text", clip=fitz.Rect(0, 0, midpoint, page.rect.height))
                right_text = page.get_text("text", clip=fitz.Rect(midpoint, 0, page.rect.width, page.rect.height))
                doc.close()
                self.assertIn(left_label, left_text)
                self.assertIn(right_label, right_text)

    def test_bilingual_raster_errors_and_cli_manifest(self) -> None:
        self._require_fitz()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.pdf"
            translated = root / "translated.pdf"
            self._write_pdf(source, "EN-SOURCE")
            self._write_pdf(translated, "ZH-TARGET")
            raster = build_bilingual_pdf.build_manifest(
                source,
                translated,
                root / "raster.pdf",
                mode="raster",
                raster_dpi=96,
            )
            self.assertEqual("ok", raster["status"])
            self.assertEqual("raster", raster["render_mode"])

            with self.assertRaisesRegex(ValueError, "render mode"):
                build_bilingual_pdf.build_bilingual_pdf(
                    source, translated, root / "invalid-mode.pdf", mode="unknown"
                )
            with self.assertRaisesRegex(ValueError, "layout"):
                build_bilingual_pdf.build_bilingual_pdf(
                    source, translated, root / "invalid-layout.pdf", layout="unknown"
                )
            missing = build_bilingual_pdf.build_manifest(
                root / "missing.pdf",
                translated,
                root / "missing-output.pdf",
            )
            self.assertEqual("error", missing["status"])

            cli_output = root / "cli.pdf"
            cli_manifest = root / "cli-manifest.json"
            exit_code = build_bilingual_pdf.main(
                [
                    "--source-pdf",
                    str(source),
                    "--translated-pdf",
                    str(translated),
                    "--output-pdf",
                    str(cli_output),
                    "--manifest",
                    str(cli_manifest),
                ]
            )
            self.assertEqual(0, exit_code)
            self.assertTrue(cli_output.is_file())
            self.assertTrue(cli_manifest.is_file())

    def test_bilingual_selection_reuse_rebuild_partial_and_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "paper.pdf"
            mono = root / "mono.pdf"
            backend_dual = root / "backend-dual.pdf"
            self._write_pdf(source, "EN")
            self._write_pdf(mono, "ZH")
            self._write_pdf(backend_dual, "BACKEND-DUAL")

            unchanged = {"mono_pdf": str(mono), "dual_pdf": str(backend_dual)}
            reused = pdf_translation_artifacts_runtime.build_standard_bilingual_output(
                source,
                root,
                unchanged,
                layout="zh-left-en-right",
                backend_dual_pdf=str(backend_dual),
                mono_changed=False,
            )
            self.assertEqual(("ok", "backend_native", "final_mono"), (
                reused["status"], reused["source"], reused["content_sync"]
            ))

            rebuilt_outputs = {"mono_pdf": str(mono), "dual_pdf": str(backend_dual)}
            rebuilt = pdf_translation_artifacts_runtime.build_standard_bilingual_output(
                source,
                root,
                rebuilt_outputs,
                layout="en-left-zh-right",
                backend_dual_pdf=str(backend_dual),
                mono_changed=True,
            )
            self.assertEqual(("ok", "pymupdf_rebuilt", "final_mono"), (
                rebuilt["status"], rebuilt["source"], rebuilt["content_sync"]
            ))

            fallback_outputs = {"mono_pdf": str(mono), "dual_pdf": str(backend_dual)}
            with mock.patch.object(
                pdf_translation_artifacts_runtime.build_bilingual_pdf,
                "build_manifest",
                return_value={
                    "version": 1,
                    "status": "error",
                    "layout": "zh_left_en_right",
                    "source": "pymupdf_rebuilt",
                    "content_sync": "unknown",
                    "layout_verification": "failed",
                },
            ):
                fallback = pdf_translation_artifacts_runtime.build_standard_bilingual_output(
                    source,
                    root,
                    fallback_outputs,
                    layout="zh-left-en-right",
                    backend_dual_pdf=str(backend_dual),
                    mono_changed=True,
                )
            self.assertEqual(("partial", "backend_native", "backend_snapshot"), (
                fallback["status"], fallback["source"], fallback["content_sync"]
            ))

            backend_default = pdf_translation_artifacts_runtime.build_standard_bilingual_output(
                source,
                root,
                {"mono_pdf": str(mono)},
                layout="backend-default",
                backend_dual_pdf=str(backend_dual),
                mono_changed=False,
            )
            self.assertEqual("backend_default", backend_default["layout"])

            off_outputs = {"mono_pdf": str(mono), "dual_pdf": str(backend_dual)}
            off = pdf_translation_artifacts_runtime.build_standard_bilingual_output(
                source,
                root,
                off_outputs,
                layout="off",
                backend_dual_pdf=str(backend_dual),
                mono_changed=False,
            )
            self.assertEqual("skipped", off["status"])
            self.assertIsNone(off_outputs["dual_pdf"])
            delivery = pdf_translation_artifacts_runtime.finalize_delivery_pdf_outputs(
                source,
                root,
                off_outputs,
                bilingual_manifest=off,
            )
            self.assertEqual("ok", delivery["status"])
            self.assertIsNone(delivery["outputs"]["bilingual_pdf"])

    def test_parser_defaults_to_chinese_left(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            args = run_pdf_translation.build_parser().parse_args(["paper.pdf"])
        self.assertEqual("zh-left-en-right", args.bilingual_layout)
        self.assertEqual("vector", args.bilingual_render_mode)

    def test_help_probe_failure_uses_conservative_options(self) -> None:
        self.assertFalse(pdf_translation_artifacts_runtime.build_bilingual_pdf is None)
        self.assertFalse(pdf_translation_runtime._pdf2zh_supports_option("", "--working-dir"))
        self.assertFalse(pdf_translation_runtime._pdf2zh_supports_option(None, "--disable-same-text-fallback"))
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(engine_home=str(Path(tmpdir) / "engine"))
            completed = subprocess.CompletedProcess(["fake", "--help"], 1, stdout="", stderr="")
            with (
                mock.patch.object(pdf_translation_runtime, "pdf2zh_command_prefix", return_value=["fake"]),
                mock.patch.object(pdf_translation_runtime, "run_text", return_value=completed),
            ):
                help_text = pdf_translation_runtime._pdf2zh_help_text(args, Path(tmpdir))
        self.assertEqual("", help_text)
        self.assertEqual("failed", args.backend_help_probe["status"])
        self.assertEqual("conservative", args.backend_help_probe["parameter_policy"])

    def test_translation_probe_requires_explicit_model_for_live_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.dict(os.environ, {}, clear=True):
            dry_args = translation_api_probe.build_parser().parse_args(
                ["--dry-run", "--output-dir", tmpdir]
            )
            dry_payload = translation_api_probe.run_probe(dry_args)
            self.assertEqual("", dry_payload["model"])

            live_args = translation_api_probe.build_parser().parse_args(
                ["--output-dir", tmpdir, "--api-key", "test-key"]
            )
            with self.assertRaisesRegex(RuntimeError, "Missing model"):
                translation_api_probe.run_probe(live_args)

    def test_offline_main_flow_with_fake_backend(self) -> None:
        self._require_fitz()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "paper.pdf"
            output_dir = root / "output"
            fake_backend = root / "fake-pdf2zh"
            self._write_pdf(source, "Offline source text for smoke testing.")
            fake_backend.write_text(
                "#!" + sys.executable + "\n"
                "import shutil, sys\n"
                "from pathlib import Path\n"
                "if '--help' in sys.argv:\n"
                "    print('--output --working-dir --disable-same-text-fallback')\n"
                "    raise SystemExit(0)\n"
                "source = Path(sys.argv[1])\n"
                "out = Path(sys.argv[sys.argv.index('--output') + 1])\n"
                "out.mkdir(parents=True, exist_ok=True)\n"
                "shutil.copy2(source, out / 'paper-mono.pdf')\n"
                "shutil.copy2(source, out / 'paper-dual.pdf')\n",
                encoding="utf-8",
            )
            fake_backend.chmod(0o755)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "run_pdf_translation.py"),
                    str(source),
                    "--output-dir",
                    str(output_dir),
                    "--pdf2zh-binary",
                    str(fake_backend),
                    "--skip-preflight",
                    "--model",
                    "offline-model",
                    "--base-url",
                    "http://127.0.0.1:9/v1",
                    "--api-key",
                    "offline-key",
                    "--translation-compat-proxy",
                    "off",
                    "--no-latex-autodiscovery",
                    "--skip-visual-eval",
                    "--toc-repair",
                    "off",
                    "--metadata-label-repair",
                    "off",
                    "--visible-residue-repair-mode",
                    "off",
                    "--bilingual-layout",
                    "backend-default",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertIn(result.returncode, {0, 3}, result.stderr + result.stdout)
            self.assertTrue((output_dir / "paper.zh.pdf").is_file())
            self.assertTrue((output_dir / "paper.bilingual.pdf").is_file())
            self.assertTrue((output_dir / "bilingual_pdf_manifest.json").is_file())

    def test_setup_venv_path_discovery_and_actionable_failure(self) -> None:
        setup_script = SCRIPT_DIR / "setup_venv.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            old_python = home / ".workbuddy/binaries/python/versions/3.12.1/python.exe"
            new_python = home / ".workbuddy/binaries/python/versions/3.13.2/python.exe"
            old_python.parent.mkdir(parents=True)
            new_python.parent.mkdir(parents=True)
            old_python.touch()
            new_python.touch()
            env = {
                **os.environ,
                "HOME": str(home),
                "PDFTR_SETUP_DRY_RUN": "1",
            }
            env.pop("PDFTR_PYTHON", None)
            env.pop("PDFTR_VENV", None)
            result = subprocess.run(
                ["bash", str(setup_script)],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(str(new_python), result.stdout)

            override = subprocess.run(
                ["bash", str(setup_script)],
                text=True,
                capture_output=True,
                env={
                    **env,
                    "PDFTR_PYTHON": sys.executable,
                    "PDFTR_VENV": str(home / "custom-venv"),
                },
                check=False,
            )
            self.assertEqual(0, override.returncode, override.stderr)
            self.assertIn(str(home / "custom-venv"), override.stdout)

            missing = subprocess.run(
                ["bash", str(setup_script)],
                text=True,
                capture_output=True,
                env={**env, "PDFTR_PYTHON": str(home / "missing-python")},
                check=False,
            )
            self.assertEqual(2, missing.returncode)
            self.assertIn("Set PDFTR_PYTHON explicitly", missing.stderr)

    def test_setup_venv_re_resolves_paths_after_fresh_install(self) -> None:
        setup_script = SCRIPT_DIR / "setup_venv.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target_venv = root / "fresh-venv"
            fake_manager = root / "managed-python"
            fake_manager.write_text(
                f"""#!{sys.executable}
import os
import pathlib
import sys

target = pathlib.Path(sys.argv[-1])
if len(sys.argv) >= 3 and sys.argv[1] == "-c" and ".installing." in str(target):
    bindir = target / "bin"
    bindir.mkdir(parents=True)
    python_bin = bindir / "python"
    python_bin.write_text("#!{sys.executable}\\nimport sys\\nsys.exit(0)\\n")
    python_bin.chmod(0o755)
    pdf2zh = bindir / "pdf2zh"
    pdf2zh.write_text("#!/bin/sh\\necho --output\\n")
    pdf2zh.chmod(0o755)
sys.exit(0)
""",
                encoding="utf-8",
            )
            fake_manager.chmod(0o755)
            result = subprocess.run(
                ["/bin/bash", str(setup_script)],
                text=True,
                capture_output=True,
                env={
                    **os.environ,
                    "HOME": str(root),
                    "PDFTR_PYTHON": str(fake_manager),
                    "PDFTR_VENV": str(target_venv),
                    "PATH": "/usr/bin:/bin",
                },
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            self.assertTrue((target_venv / "bin/python").is_file())
            self.assertTrue((target_venv / "bin/pdf2zh").is_file())
            self.assertIn("Backend installed", result.stdout)
            self.assertIn("pdf2zh CLI OK", result.stdout)

    def test_run_translate_normalizes_msys_backend_path(self) -> None:
        launcher = SKILL_DIR / "run_translate.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            venv_bin = root / "venv/bin"
            tools = root / "tools"
            venv_bin.mkdir(parents=True)
            tools.mkdir()
            python_bin = venv_bin / "python"
            python_bin.write_text(
                f"""#!{sys.executable}
import os
import sys
if any(value.endswith("run_pdf_translation.py") for value in sys.argv):
    print(os.environ.get("PAPER_TRANSLATION_PDF2ZH_BINARY", ""))
sys.exit(0)
""",
                encoding="utf-8",
            )
            python_bin.chmod(0o755)
            (venv_bin / "pdf2zh").touch()
            native_backend = root / "native-pdf2zh.exe"
            native_backend.touch()
            cygpath = tools / "cygpath"
            cygpath.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$NATIVE_PDF2ZH\"\n",
                encoding="utf-8",
            )
            cygpath.chmod(0o755)
            result = subprocess.run(
                ["/bin/bash", str(launcher), "--help"],
                text=True,
                capture_output=True,
                env={
                    **os.environ,
                    "PDFTR_VENV": str(root / "venv"),
                    "MSYSTEM": "MINGW64",
                    "NATIVE_PDF2ZH": str(native_backend),
                    "PATH": f"{tools}:/usr/bin:/bin",
                },
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            self.assertEqual(str(native_backend), result.stdout.strip())

    def test_run_translate_normalizes_all_msys_path_arguments(self) -> None:
        launcher = SKILL_DIR / "run_translate.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            venv_bin = root / "venv/bin"
            tools = root / "tools"
            venv_bin.mkdir(parents=True)
            tools.mkdir()
            python_bin = venv_bin / "python"
            python_bin.write_text(
                f"""#!{sys.executable}
import json
import sys
if any(value.endswith("run_pdf_translation.py") for value in sys.argv):
    print(json.dumps(sys.argv[2:]))
sys.exit(0)
""",
                encoding="utf-8",
            )
            python_bin.chmod(0o755)
            original_backend = venv_bin / "pdf2zh"
            original_backend.touch()
            native_backend = root / "native-pdf2zh.exe"
            native_backend.touch()
            input_pdf = root / "input.pdf"
            input_pdf.touch()
            output_dir = root / "output"
            source_root = root / "source-root"
            engine_home = root / "engine-home"
            cygpath = tools / "cygpath"
            cygpath.write_text(
                """#!/bin/sh
case "$2" in
  "$ORIGINAL_BACKEND") printf '%s\\n' "$NATIVE_PDF2ZH" ;;
  "$INPUT_PATH") printf '%s\\n' "WIN_INPUT" ;;
  "$OUTPUT_PATH") printf '%s\\n' "WIN_OUTPUT" ;;
  "$SOURCE_ROOT") printf '%s\\n' "WIN_SOURCE_ROOT" ;;
  "$ENGINE_HOME") printf '%s\\n' "WIN_ENGINE_HOME" ;;
  *) printf '%s\\n' "$2" ;;
esac
""",
                encoding="utf-8",
            )
            cygpath.chmod(0o755)
            result = subprocess.run(
                [
                    "/bin/bash",
                    str(launcher),
                    "--custom-system-prompt",
                    "literal.pdf",
                    str(input_pdf),
                    "--output-dir",
                    str(output_dir),
                    f"--latex-source-root={source_root}",
                    "--engine-home",
                    str(engine_home),
                ],
                text=True,
                capture_output=True,
                env={
                    **os.environ,
                    "PDFTR_VENV": str(root / "venv"),
                    "MSYSTEM": "MINGW64",
                    "ORIGINAL_BACKEND": str(original_backend),
                    "NATIVE_PDF2ZH": str(native_backend),
                    "INPUT_PATH": str(input_pdf),
                    "OUTPUT_PATH": str(output_dir),
                    "SOURCE_ROOT": str(source_root),
                    "ENGINE_HOME": str(engine_home),
                    "PATH": f"{tools}:/usr/bin:/bin",
                },
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            args = json.loads(result.stdout)
            self.assertEqual(
                [
                    "--custom-system-prompt",
                    "literal.pdf",
                    "WIN_INPUT",
                    "--output-dir",
                    "WIN_OUTPUT",
                    "--latex-source-root=WIN_SOURCE_ROOT",
                    "--engine-home",
                    "WIN_ENGINE_HOME",
                ],
                args,
            )

    def test_dual_translate_first_follows_requested_layout(self) -> None:
        def build(layout: str, help_text: str) -> tuple[list[str], argparse.Namespace]:
            args = argparse.Namespace(
                input_pdf="paper.pdf",
                backend_debug_artifacts=False,
                ignore_translation_cache=False,
                translator_mode="openai",
                model="test-model",
                base_url="https://provider.example/v1",
                api_key="test-key",
                openai_timeout=30,
                temperature=0.0,
                openai_reasoning_effort="none",
                openai_json_mode=False,
                disable_same_text_fallback=False,
                local_max_concurrency=1,
                custom_system_prompt="Translate.",
                resolved_pdf_layout_profile="default",
                pdf_layout_profile="default",
                dual=True,
                pages=None,
                bilingual_layout=layout,
            )
            with (
                mock.patch.object(
                    pdf_translation_runtime,
                    "pdf2zh_command_prefix",
                    return_value=["fake-pdf2zh"],
                ),
                mock.patch.object(
                    pdf_translation_runtime,
                    "_pdf2zh_help_text",
                    return_value=help_text,
                ),
            ):
                command = pdf_translation_runtime.build_pdf2zh_command(
                    args,
                    Path("output"),
                )
            return command, args

        zh_left, _ = build("zh-left-en-right", "--dual-translate-first")
        en_left, _ = build("en-left-zh-right", "--dual-translate-first")
        backend_default, _ = build("backend-default", "--dual-translate-first")
        unsupported, unsupported_args = build("zh-left-en-right", "")
        self.assertIn("--dual-translate-first", zh_left)
        self.assertNotIn("--dual-translate-first", en_left)
        self.assertNotIn("--dual-translate-first", backend_default)
        self.assertNotIn("--dual-translate-first", unsupported)
        self.assertIn(
            "--dual-translate-first",
            unsupported_args.backend_unsupported_options,
        )


if __name__ == "__main__":
    unittest.main()
