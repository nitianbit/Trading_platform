import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.source_manifest import source_fingerprint, verify_image
from scripts.deployment_target import table_fingerprint


class DeploymentToolTests(unittest.TestCase):
    def test_source_fingerprint_covers_dirty_source_but_excludes_private_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/"app.py").write_text("one")
            original=source_fingerprint(root)
            (root/".env").write_text("private"); (root/".claude").mkdir(); (root/".claude/settings.local.json").write_text("private")
            self.assertEqual(source_fingerprint(root),original)
            (root/".env.example").write_text("public template")
            self.assertNotEqual(source_fingerprint(root),original)
            template=source_fingerprint(root); (root/"app.py").write_text("uncommitted repair")
            self.assertNotEqual(source_fingerprint(root),template)
    def test_stale_image_is_rejected_before_deploying(self):
        with patch("subprocess.check_output",return_value="old-source\n"):
            with self.assertRaisesRegex(RuntimeError,"fingerprint mismatch"): verify_image("owned-test-image","current-source")
    def test_fingerprint_escapes_table_identity_and_checks_row_content(self):
        query=table_fingerprint('has"quote')
        self.assertIn('public."has""quote"',query); self.assertIn("to_jsonb(t)",query); self.assertIn("count(*)",query)
