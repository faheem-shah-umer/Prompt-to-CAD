"""Verify a portable ZIP's checksum, exact manifest inventory and file hashes."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile
from tools.audit_package import BLOCKED


def verify(path):
    path = Path(path)
    checksum = path.with_suffix('.zip.sha256').read_text().split()[0]
    with path.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != checksum:
            raise RuntimeError('Archive checksum mismatch.')
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError('Duplicate archive entries.')
        prefix = names[0].split('/')[0] + '/'
        manifest_name = prefix + 'runtime-manifest.json'
        manifest = json.loads(archive.read(manifest_name))
        expected = {prefix + name for name in manifest['files']} | {manifest_name}
        if set(names) != expected:
            raise RuntimeError('Archive contents differ from the reviewed manifest.')
        for entry in archive.infolist():
            relative = PurePosixPath(entry.filename)
            if relative.is_absolute() or '..' in relative.parts or any(part.lower() in BLOCKED for part in relative.parts):
                raise RuntimeError('Unsafe or user-data archive path.')
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError('Archive contains a filesystem link.')
            if entry.filename == manifest_name:
                continue
            with archive.open(entry) as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            if digest != manifest['files'][entry.filename[len(prefix):]]:
                raise RuntimeError('Archive file hash mismatch.')
        report = {'passed': True, 'files': len(names), 'version': manifest['version'],
            'sha256': checksum, 'publication_ready': manifest['publication_ready']}
    print(json.dumps(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    verify(parser.parse_args().archive)


if __name__ == '__main__':
    main()
