# PyInstaller spec: one-file console build of cfbtui. Build with scripts/build_exe.ps1.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [("cfbtui/ui/app.tcss", "cfbtui/ui")]
datas += collect_data_files("tzdata")
datas += collect_data_files("textual")

hiddenimports = collect_submodules("textual.widgets") + collect_submodules("tzdata")

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
    version=".pyi-build/version_info.txt",
)
