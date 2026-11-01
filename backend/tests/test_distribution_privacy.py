"""Keep public wheel build metadata distinct from private package contents."""
import base64
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.audit_package import audit


class DistributionPrivacyTests(unittest.TestCase):
    def wheel_file(self, root, data):
        site = root / 'python/Lib/site-packages'
        target = site / 'synthetic_package/config.py'
        target.parent.mkdir(parents=True)
        target.write_bytes(data)
        record = site / 'synthetic_package-1.0.dist-info/RECORD'
        record.parent.mkdir()
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
        record.write_text(f'synthetic_package/config.py,sha256={digest},{len(data)}\n')
        return target

    def test_public_build_account_requires_unchanged_wheel_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = ('C:' + '/Users/' + 'runneradmin/build/public-wheel').encode()
            target = self.wheel_file(root, data)
            with patch('tools.audit_package.Path.home', return_value=Path('C:') / 'Users' / 'runneradmin'):
                self.assertEqual(audit(root)['unchanged_wheel_build_paths'], 1)
                target.write_bytes(data + b' changed after installation')
                with self.assertRaises(RuntimeError):
                    audit(root)
                target.write_bytes(data)
                (root / 'README.md').write_bytes(data)
                with self.assertRaises(RuntimeError):
                    audit(root)

    def test_private_owner_and_checkout_paths_are_never_exempt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = ('C:' + '/Users/' + 'PrivateOwner/private-project').encode()
            target = self.wheel_file(root, data)
            with patch('tools.audit_package.Path.home', return_value=Path('C:') / 'Users' / 'PrivateOwner'):
                with self.assertRaises(RuntimeError):
                    audit(root)
            checkout = str(Path(__file__).resolve().parents[2]).encode()
            target.write_bytes(checkout)
            digest = base64.urlsafe_b64encode(hashlib.sha256(checkout).digest()).decode().rstrip('=')
            record = root / 'python/Lib/site-packages/synthetic_package-1.0.dist-info/RECORD'
            record.write_text(f'synthetic_package/config.py,sha256={digest},{len(checkout)}\n')
            with patch('tools.audit_package.Path.home', return_value=Path('C:') / 'Users' / 'runneradmin'):
                with self.assertRaises(RuntimeError):
                    audit(root)


if __name__ == '__main__':
    unittest.main()
