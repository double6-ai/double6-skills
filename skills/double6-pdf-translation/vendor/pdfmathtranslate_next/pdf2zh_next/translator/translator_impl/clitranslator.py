import logging
import os
import shlex
import subprocess
from pathlib import Path
from shutil import which

from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.translator.base_rate_limiter import BaseRateLimiter
from pdf2zh_next.translator.base_translator import BaseTranslator
from tenacity import before_sleep_log
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_exponential

logger = logging.getLogger(__name__)


class CLITranslatorTranslator(BaseTranslator):
    """CLI translator that can call any external translation tool

    This translator allows you to use any CLI tool for translation by specifying
    the command and arguments. Input text is always provided via stdin.

    Example configurations:

    1. Basic usage:
       clitranslator_command: "your-translator-command --flag value"

    2. Custom flags:
       clitranslator_command: "your-translator-command --from en --to ja"

    3. Postprocess command (e.g. jq):
       clitranslator_command: "your-translator-command --format json"
       clitranslator_postprocess_command: "jq -r .result.translation"
    """

    name = "clitranslator"

    def __init__(
        self,
        settings: SettingsModel,
        rate_limiter: BaseRateLimiter,
    ):
        super().__init__(settings, rate_limiter)
        cli_settings = settings.translate_engine_settings
        self.command_string = cli_settings.clitranslator_command

        try:
            command_parts = shlex.split(self.command_string)
        except ValueError as e:
            raise ValueError(f"Invalid clitranslator_command: {e}") from e
        if not command_parts:
            raise ValueError(
                "CLI command is required. Please specify --clitranslator-command"
            )

        self.command = command_parts[0]
        self.args = command_parts[1:]
        self.timeout = cli_settings.clitranslator_timeout
        self.postprocess_command_string = cli_settings.clitranslator_postprocess_command
        self.postprocess_command = None
        if self.postprocess_command_string:
            # Parse once so invalid quoting fails early and the command is cache-keyed.
            try:
                postprocess_parts = shlex.split(self.postprocess_command_string)
            except ValueError as e:
                raise ValueError(
                    f"Invalid clitranslator_postprocess_command: {e}"
                ) from e
            if not postprocess_parts:
                raise ValueError("clitranslator_postprocess_command cannot be empty")
            self.postprocess_command = postprocess_parts

        # Add cache impact parameters
        self.add_cache_impact_parameters("clitranslator_command", self.command_string)
        if self.postprocess_command_string:
            self.add_cache_impact_parameters(
                "clitranslator_postprocess_command", self.postprocess_command_string
            )

        # Best-effort availability check (does not assume --version support).
        self._test_command(self.command, label="CLI")
        if self.postprocess_command:
            self._test_command(self.postprocess_command[0], label="Postprocess")

    def _test_command(self, command: str, label: str):
        """Validate that the command is executable or discoverable on PATH."""
        cmd_path = Path(command)
        if cmd_path.is_absolute() or cmd_path.parent != Path():
            if not cmd_path.exists():
                raise ValueError(
                    f"{label} command '{command}' not found. "
                    f"Please ensure it's installed and in your PATH."
                )
            if not os.access(cmd_path, os.X_OK):
                raise ValueError(
                    f"{label} command '{command}' is not executable. "
                    f"Please check permissions."
                )
            return

        resolved = which(command)
        if not resolved:
            raise ValueError(
                f"{label} command '{command}' not found. "
                f"Please ensure it's installed and in your PATH."
            )

    @retry(
        retry=retry_if_exception_type(
            (subprocess.CalledProcessError, subprocess.TimeoutExpired)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def do_translate(self, text, rate_limit_params: dict = None) -> str:
        """Execute translation using the configured CLI tool"""

        cmd = [self.command] + self.args

        try:
            logger.debug(f"Executing CLI command: {' '.join(cmd)}")

            # Pass text via stdin
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            stdout, stderr = process.communicate(input=text, timeout=self.timeout)

            if process.returncode != 0:
                logger.error(
                    "CLI command failed (exit %s): %s", process.returncode, stderr
                )
                raise subprocess.CalledProcessError(
                    process.returncode,
                    cmd,
                    output=stdout,
                    stderr=stderr,
                )

            output = stdout
            if self.postprocess_command:
                # Allow arbitrary stdout transformation (e.g., jq).
                output = self._run_postprocess(output)

            return output.strip()

        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise

    def _run_postprocess(self, output: str) -> str:
        """Run postprocess command on CLI output."""
        if not self.postprocess_command:
            return output

        try:
            process = subprocess.Popen(
                self.postprocess_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            stdout, stderr = process.communicate(input=output, timeout=self.timeout)
            if process.returncode != 0:
                logger.error(
                    "Postprocess command failed (exit %s): %s",
                    process.returncode,
                    stderr,
                )
                raise subprocess.CalledProcessError(
                    process.returncode,
                    self.postprocess_command,
                    output=stdout,
                    stderr=stderr,
                )
            return stdout
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
