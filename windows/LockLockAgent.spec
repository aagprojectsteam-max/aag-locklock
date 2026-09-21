# -*- mode: python ; coding: utf-8 -*-
import os

project_root = os.path.abspath(os.path.join(SPECPATH, ".."))
a = Analysis(
    [os.path.join(project_root, "src", "locklock_windows", "agent.py")],
    pathex=[os.path.join(project_root, "src")],
    hiddenimports=["pystray._win32", "win32timezone", "win32ts"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LockLockAgent",
    console=False,
    disable_windowed_traceback=False,
    uac_admin=False,
)
