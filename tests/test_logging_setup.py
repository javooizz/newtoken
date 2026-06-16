"""newtoken.common.logging_setup 单元测试（stdlib unittest，零额外依赖）。"""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from newtoken.common import logging_setup as ls


class LoggingSetupTest(unittest.TestCase):
    def setUp(self):
        ls.reset_logging()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        ls.reset_logging()
        self._tmp.cleanup()

    def _read(self, path: Path) -> str:
        logging.getLogger(ls.LOGGER_ROOT).handlers[0].flush()
        return path.read_text(encoding="utf-8")

    def test_mask_token_keeps_prefix_hides_rest(self):
        out = ls.mask_token("eyJhbGciOiJ" + "x" * 200)
        self.assertTrue(out.startswith("eyJhbG"))
        self.assertNotIn("x" * 20, out)
        self.assertIn("masked,len=", out)

    def test_mask_token_short_and_empty(self):
        self.assertEqual(ls.mask_token(""), "")
        self.assertEqual(ls.mask_token("abc"), "***")

    def test_mask_card_and_password(self):
        self.assertEqual(ls.mask_card("ABCD1234EFGH"), "ABCD****")
        self.assertEqual(ls.mask_card(""), "")
        self.assertEqual(ls.mask_password("hunter2"), "***")
        self.assertEqual(ls.mask_password(""), "")

    def test_mask_text_redacts_jwt_in_body(self):
        body = 'prefix {"access_token":"eyJabc.' + "y" * 40 + '.zzz"} suffix'
        out = ls.mask_text(body)
        self.assertNotIn("y" * 40, out)
        self.assertIn("prefix", out)
        self.assertIn("suffix", out)

    def test_log_run_context_sets_and_resets(self):
        self.assertEqual(ls._run_id_var.get(), "-")
        with ls.log_run_context("auto203500"):
            self.assertEqual(ls._run_id_var.get(), "auto203500")
            with ls.log_run_context("auto203500/r1"):
                self.assertEqual(ls._run_id_var.get(), "auto203500/r1")
            self.assertEqual(ls._run_id_var.get(), "auto203500")
        self.assertEqual(ls._run_id_var.get(), "-")

    def test_setup_logging_creates_file_and_writes(self):
        log_path = ls.setup_logging(level="DEBUG", log_dir=str(self.tmp))
        self.assertEqual(log_path, self.tmp / "sub2api.log")
        ls.get_logger("webui.test").info("hello-line")
        self.assertIn("hello-line", self._read(log_path))

    def test_setup_logging_idempotent(self):
        ls.setup_logging(level="INFO", log_dir=str(self.tmp))
        n1 = len(logging.getLogger(ls.LOGGER_ROOT).handlers)
        ls.setup_logging(level="INFO", log_dir=str(self.tmp))
        n2 = len(logging.getLogger(ls.LOGGER_ROOT).handlers)
        self.assertEqual(n1, 2)
        self.assertEqual(n2, 2)

    def test_run_id_appears_in_file(self):
        log_path = ls.setup_logging(level="DEBUG", log_dir=str(self.tmp))
        with ls.log_run_context("auto999"):
            ls.get_logger("webui.test").info("with-context")
        self.assertIn("auto999", self._read(log_path))

    def test_exception_writes_traceback(self):
        log_path = ls.setup_logging(level="DEBUG", log_dir=str(self.tmp))
        log = ls.get_logger("webui.test")
        try:
            raise RuntimeError("boom-xyz")
        except RuntimeError:
            log.exception("caught failure")
        text = self._read(log_path)
        self.assertIn("Traceback (most recent call last)", text)
        self.assertIn("boom-xyz", text)

    def test_masking_filter_redacts_token_in_emitted_log(self):
        log_path = ls.setup_logging(level="DEBUG", log_dir=str(self.tmp))
        secret = "eyJsecret." + "q" * 60 + ".tail"
        ls.get_logger("webui.test").info("token=%s done", secret)
        text = self._read(log_path)
        self.assertNotIn("q" * 60, text)
        self.assertIn("done", text)


if __name__ == "__main__":
    unittest.main()
