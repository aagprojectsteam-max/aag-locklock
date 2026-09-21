# -*- mode: python ; coding: utf-8 -*-
import os

project_root = os.path.abspath(os.path.join(SPECPATH, ".."))
a = Analysis(
    [os.path.join(project_root, "src", "locklock_windows", "cli.py")],
    pathex=[os.path.join(project_root, "src")],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LockLockCli",
    console=True,
    uac_admin=False,
)
