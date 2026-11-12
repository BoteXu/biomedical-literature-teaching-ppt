"""Build an allowlisted, self-contained skill ZIP and SHA256 sidecar."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from check_package import ROOT, SKILL_FILES, validate

def build(output_dir):
    errors = validate()
    if errors:
        raise ValueError('; '.join(errors))
    version = (ROOT/'VERSION').read_text().strip()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir/f'biomedical-literature-teaching-ppt-v{version}.zip'
    sidecar = output_dir/f'SHA256SUMS-v{version}.txt'
    if archive.exists() or sidecar.exists():
        raise FileExistsError('Refuse to overwrite an existing release')
    manifest = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SKILL_FILES}
    prefix = 'biomedical-literature-teaching-ppt/'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for name in SKILL_FILES:
            z.writestr(prefix+name, (ROOT/name).read_bytes())
        z.writestr(prefix+'MANIFEST.json', json.dumps({'version':version,'sha256':manifest},ensure_ascii=False,indent=2))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError('ZIP integrity check failed')
        if set(z.namelist()) != {prefix+n for n in SKILL_FILES} | {prefix+'MANIFEST.json'}:
            raise ValueError('Unexpected archive members')
        for name, expected in manifest.items():
            if hashlib.sha256(z.read(prefix+name)).hexdigest() != expected:
                raise ValueError(f'ZIP content mismatch: {name}')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    sidecar.write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    print(f'Built and verified: {archive.name} ({len(SKILL_FILES)+1} members)')
    return archive, sidecar

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    build(args.output_dir)
