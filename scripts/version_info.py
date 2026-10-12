"""Write the PyInstaller Windows version resource from ``cfbtui.__version__``."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cfbtui import __version__

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({v}, 0), prodvers=({v}, 0), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Bill Kane'),
      StringStruct('FileDescription', 'College football scoreboard for the terminal'),
      StringStruct('FileVersion', '{s}'),
      StringStruct('InternalName', 'cfbtui'),
      StringStruct('OriginalFilename', 'cfbtui.exe'),
      StringStruct('ProductName', 'cfbtui'),
      StringStruct('ProductVersion', '{s}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

out = Path(".pyi-build/version_info.txt")
out.parent.mkdir(exist_ok=True)
out.write_text(TEMPLATE.format(v=", ".join(__version__.split(".")), s=__version__), encoding="utf-8")
print(out)
