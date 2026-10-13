import json
import tempfile
import unittest
from pathlib import Path
from terra.validation import load

class TextPortabilityTests(unittest.TestCase):
    def test_utf8_json_and_native_path_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix='terra text ') as directory:
            path = Path(directory)/'材料.json'
            value = {'description': '磁砖, ceramic tile 300 × 600 mm'}
            path.write_bytes(json.dumps(value, ensure_ascii=False).encode('utf-8'))
            self.assertEqual(load(path), value)
