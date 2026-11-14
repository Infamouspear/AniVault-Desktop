# Windows-only, clean staged application input. Never points at user AppData.
from pathlib import Path
import sys
import ssl
from PyInstaller.utils.hooks import copy_metadata, get_package_paths
if sys.platform != 'win32': raise RuntimeError('Build Windows binaries on Windows x64.')
root=Path(SPECPATH).parent
stage=root/'build'/'clean-source'
if not (stage/'release-manifest.json').exists(): raise RuntimeError('Run packaging/build_windows.ps1 first.')
data=[(str(stage/'assets'),'assets'),(str(stage/'release-manifest.json'),'.')]
# Preserve the build runtime's certificate distrust policy when present.
policy = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
if policy.is_file():data.append((str(policy),'.'))
for package in ('PySide6','PySide6_Essentials','PySide6_Addons','shiboken6','python-vlc','pypdfium2','Pillow','rarfile','imageio-ffmpeg'):
    data += copy_metadata(package)
license=Path(sys.base_prefix)/'LICENSE.txt'
if license.exists():data.append((str(license),'licenses/python'))
# Include ICU only when supplied by Qt itself; never take another toolchain's ICU.
qt_package=Path(get_package_paths('PySide6')[1])
qt_icu=[(str(path),'.') for path in qt_package.glob('icu*.dll')]
a=Analysis([str(stage/'main.py')],pathex=[str(stage)],binaries=qt_icu,
 datas=data,
 hiddenimports=['PySide6.QtSvg','vlc','rarfile','pypdfium2','imageio_ffmpeg'],
 excludes=['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtWebEngineQuick','pytest','tkinter'],
 noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='AniVault',debug=False,
 bootloader_ignore_signals=False,strip=False,upx=False,console=False,
 icon=str(stage/'assets'/'anivault.ico'),version=str(root/'packaging'/'windows_version.txt'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='AniVault')
