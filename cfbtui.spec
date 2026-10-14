# PyInstaller spec: one-file console build of cfbtui, the same on Windows, Linux and macOS.
# Build with scripts/build_exe.ps1 on Windows, or `python -m PyInstaller --workpath .pyi-build cfbtui.spec` anywhere.
import importlib.util
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [("cfbtui/ui/app.tcss", "cfbtui/ui")]
datas += collect_data_files("textual")
hiddenimports = collect_submodules("textual.widgets")

# tzdata is only a dependency on Windows, where there are no system zone files. When it is installed anyway
# (the release workflow installs it everywhere), bundle it so the binary works on a system without /usr/share/zoneinfo.
if importlib.util.find_spec("tzdata") is not None:
    datas += collect_data_files("tzdata")
    hiddenimports += collect_submodules("tzdata")

a = Analysis(
    ["cfbtui/__main__.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "pronouncing", "respx"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="cfbtui",
    console=True,
    upx=False,
    # The Windows version resource, written by scripts/version_info.py. PyInstaller ignores it elsewhere.
    version=".pyi-build/version_info.txt" if sys.platform == "win32" else None,
)
