"""Fetch only the approved original lab assets; verify their pinned bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true', help='verify existing assets without network access')
    args = parser.parse_args()
    model = json.loads((ROOT / 'models/yolox-tiny/manifest.json').read_text())['artifact']
    fixture = json.loads((ROOT / 'models/yolox-tiny/fixture-manifest.json').read_text())
    assets = [(ROOT / 'data/oracle/yolox_tiny.onnx', model),
              (ROOT / 'data/oracle/shibuya_people.jpg', fixture)]
    try:
        for destination, metadata in assets:
            if not args.verify_only and not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                partial = destination.with_suffix(destination.suffix + '.part')
                subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                                '--connect-timeout', '20', '--max-time', '120',
                                metadata['source_url'], '-o', str(partial)],
                               check=True, timeout=125)
                verify(partial, metadata['size_bytes'], metadata['sha256'])
                # Both paths are fixed workspace-local siblings, never user supplied.
                if partial.resolve().parent != (ROOT / 'data/oracle').resolve() or destination.resolve().parent != (ROOT / 'data/oracle').resolve():
                    raise ValueError('asset destination escapes data/oracle')
                partial.replace(destination)
            verify(destination, metadata['size_bytes'], metadata['sha256'])
            print(f'verified {destination.relative_to(ROOT)} {metadata["sha256"]}')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'oracle asset fetch failed: {error}', file=sys.stderr)
        return 2
    return 0


def verify(path: Path, size_bytes: int, sha256: str) -> None:
    if path.stat().st_size != size_bytes:
        raise ValueError(f'{path.name}: size mismatch')
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != sha256:
        raise ValueError(f'{path.name}: SHA-256 mismatch')


if __name__ == '__main__':
    raise SystemExit(main())
