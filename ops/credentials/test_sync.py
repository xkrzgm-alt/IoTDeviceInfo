import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apply_remote import env_text
from sync_aliyun import load_inventory


class CredentialTests(unittest.TestCase):
    def test_quoting(self):
        self.assertEqual(env_text({'KEY': 'a"b\\c$z'}), 'KEY="a\\"b\\\\c$z"\n')
        with self.assertRaises(ValueError):
            env_text({'KEY': 'line\nnext'})

    def test_plaintext_inventory_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'secrets.sops.json'
            path.write_text(json.dumps({'common': {}, 'iotdeviceinfo': {}, 'hwprogm': {}}))
            with self.assertRaisesRegex(ValueError, 'not SOPS-encrypted'):
                load_inventory(path)

    def test_missing_required_and_duplicate_keys_rejected(self):
        from sync_aliyun import HERE
        schema = json.loads((HERE / 'schema.json').read_text())
        groups = {group: {key: 'example' for key in fields['required']}
                  for group, fields in schema.items()}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'secrets.sops.json'
            path.write_text(json.dumps({'sops': {}}))
            with patch('sync_aliyun.subprocess.run') as decrypt:
                decrypt.return_value.stdout = json.dumps(groups).encode()
                self.assertEqual(load_inventory(path), groups)
                del groups['common']['DEVICE_INFO_PWD']
                decrypt.return_value.stdout = json.dumps(groups).encode()
                with self.assertRaisesRegex(ValueError, 'Invalid or missing'):
                    load_inventory(path)


if __name__ == '__main__':
    unittest.main()
