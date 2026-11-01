"""Cache checksum-pinned supplementary runtime license texts from upstream."""
import hashlib
import urllib.request
from tools.build_native import ROOT

TEXTS = {
    'Qt-GPL-3.0-only.txt': ('https://raw.githubusercontent.com/qt/qtbase/v6.9.0/LICENSES/GPL-3.0-only.txt',
        '8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903'),
    'OCCT_LGPL_EXCEPTION.txt': ('https://raw.githubusercontent.com/Open-Cascade-SAS/OCCT/V7_8_1/OCCT_LGPL_EXCEPTION.txt',
        '04580a884ea6cea294402649ff7b5cbb167d47462d1340a4ed33e550db10a81b'),
}


def prepare():
    folder = ROOT / '.sdk/compliance'
    folder.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in TEXTS.items():
        path = folder / name
        if not path.is_file():
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError('Upstream license text checksum mismatch.')
            path.write_bytes(data)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Cached license text checksum mismatch.')
    return folder


if __name__ == '__main__':
    prepare()
    print('Supplementary license text hashes verified.')
