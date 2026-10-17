"""Install verified Linux geometry dependencies and build the production C++ targets."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DOWNLOADS = ROOT / '.artifacts/cloud-downloads'
BUNDLE = ROOT / 'vendor/linux'
BLENDER = ROOT / '.artifacts/blender-5.0.1-linux-x64'


def download(url, digest):
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    path = DOWNLOADS / url.rsplit('/', 1)[-1]
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        temporary = path.with_suffix('.download')
        with urllib.request.urlopen(url, timeout=180) as source, temporary.open('wb') as target:
            shutil.copyfileobj(source, target)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Download checksum mismatch: ' + url)
        temporary.replace(path)
    return path


def unpack_zip(archive, target):
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as data:
        for name in data.namelist():
            if not (target / name).resolve().is_relative_to(target.resolve()):
                raise RuntimeError('Unsafe archive path: ' + name)
        data.extractall(target)


def inventory(folder):
    files = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name != 'inventory.json'}
    lock = hashlib.sha256((ROOT / 'tools/cloud/linux-wheels.json').read_bytes()).hexdigest()
    (folder / 'inventory.json').write_text(json.dumps(dict(files=files, wheel_lock=lock), sort_keys=True))


def install_packages():
    target = BUNDLE / 'packages'
    if target.exists():
        from core.linux_dependencies import verify
        try:
            verify(target)
            return
        except (ValueError, OSError, RuntimeError):
            shutil.rmtree(target)
    rows = json.loads((ROOT / 'tools/cloud/linux-wheels.json').read_text())
    for row in rows:
        unpack_zip(download(row['url'], row['sha256']), target)
    inventory(target)


def install_blender():
    url = 'https://mirror.blender.org/release/Blender5.0/blender-5.0.1-linux-x64.tar.xz'
    digest = '8019580ee1b7262e505f4196a00237ccf743c88d205b38d34201510676e60b09'
    if not (BLENDER / 'blender').is_file():
        with tarfile.open(download(url, digest)) as archive:
            archive.extractall(BLENDER.parent, filter='data')
    subprocess.run([str(BLENDER / 'blender'), '--version'], check=True)


def install_quadwild():
    url = 'https://github.com/cgg-bern/quadwild-bimdf/releases/download/v0.0.2/linux-binaries.zip'
    digest = 'f27d9f2ffebf4eafca4ca0ce45b21e5c6cc6fbee70dd8573f5e6dd7cd6b7ccc1'
    target = BUNDLE / 'quadwild'
    unpack_zip(download(url, digest), target)
    for name in ('quadwild', 'quad_from_patches'):
        (target / name).chmod(0o755)
    inventory(target)


def build_native():
    folder = ROOT / '.artifacts/linux-native'
    command = ['cmake', '-S', str(ROOT / 'native'), '-B', str(folder), '-DCMAKE_BUILD_TYPE=Release']
    if shutil.which('clang++'):
        command.append('-DCMAKE_CXX_COMPILER=clang++')
    subprocess.run(command, check=True)
    subprocess.run(['cmake', '--build', str(folder), '--parallel', '2'], check=True)
    subprocess.run(['ctest', '--test-dir', str(folder), '--output-on-failure'], check=True)
    subprocess.run(['cmake', '--install', str(folder), '--prefix', str(ROOT / 'native')], check=True)


def main():
    if not sys.platform.startswith('linux') or sys.version_info[:2] != (3, 11):
        raise SystemExit('Run this installer with Linux x64 Python 3.11.')
    sys.path.insert(0, str(ROOT))
    install_packages()
    install_quadwild()
    install_blender()
    build_native()
    print('Geometry runtime ready:', BLENDER / 'blender', flush=True)


if __name__ == '__main__':
    main()
