"""Qt Widgets release: collect required DLLs through normal dependency analysis.

This app uses raster Widgets, not Qt Quick/OpenGL. Omit PyInstaller's optional
ANGLE, Mesa software OpenGL, and unreferenced ICU renderer additions. Required
DLL imports are still resolved by PyInstaller's normal dependency analysis.
"""
from PyInstaller.utils.hooks.qt import ensure_single_qt_bindings_package

ensure_single_qt_bindings_package("PySide6")
hiddenimports = ["shiboken6", "inspect", "PySide6.support.deprecated"]
binaries = []
