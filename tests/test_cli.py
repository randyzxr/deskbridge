import io
import sys
import unittest
from unittest.mock import patch

from deskbridge.cli import main


class DiagnosticTests(unittest.TestCase):
    def test_doctor_on_ascii_redirected_console(self):
        data = io.BytesIO()
        output = io.TextIOWrapper(data, encoding="ascii", write_through=True)
        with patch.object(sys, "stdout", output), patch.object(sys, "stderr", io.StringIO()), \
             patch.object(sys, "argv", ["DeskBridge", "--doctor"]), \
             patch("deskbridge.cli.check_engine", return_value="verified-core"):
            main()
        text = data.getvalue().decode("utf-8")
        self.assertIn("版本与便携目录检查通过", text)

    def test_doctor_in_windowed_application_without_console(self):
        with patch.object(sys, "stdout", None), patch.object(sys, "stderr", None), \
             patch.object(sys, "argv", ["DeskBridge", "--doctor"]), \
             patch("deskbridge.cli.check_engine", return_value="verified-core") as checked:
            main()
        checked.assert_called_once()
