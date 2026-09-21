# -*- mode: python ; coding: utf-8 -*-
import os

project_root = os.path.abspath(os.path.join(SPECPATH, ".."))
a = Analysis(
    [os.path.join(project_root, "src", "locklock_windows", "service.py")],
    pathex=[os.path.join(project_root, "src")],
    hiddenimports=["win32timezone"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LockLockService",
    console=True,
    uac_admin=True,
)
