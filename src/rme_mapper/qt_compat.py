"""Centralized Qt compatibility shim for GeoPoint Mapper.

Supports:
- PySide6 (Modern default, Qt 6.x)
- PySide2 (Legacy Qt 5.x on Python 3.8 / Windows 7)
- PyQt5   (Alternative legacy Qt 5.x on Python 3.8 / Windows 7)

Exports only actually used Qt symbols to maintain a single source tree.
"""
from __future__ import annotations

import sys
import types
from typing import Any, Tuple

QT_BINDING: str | None = None
QT_VERSION: Tuple[int, ...] = (0, 0, 0)

QtCore: Any = None
QtGui: Any = None
QtWidgets: Any = None
QtNetwork: Any = None
Qt: Any = None
Signal: Any = None
Slot: Any = None
Property: Any = None
QAction: Any = None
QActionGroup: Any = None

# 1. Try PySide6 first (Modern)
try:
    import PySide6
    from PySide6 import QtCore, QtGui, QtNetwork, QtWidgets
    from PySide6.QtCore import Property, Qt, Signal, Slot
    from PySide6.QtGui import QAction, QActionGroup

    QT_BINDING = "PySide6"
    version_str = getattr(PySide6, "__version__", "6.0.0")
    QT_VERSION = tuple(int(x) for x in version_str.split(".")[:3] if x.isdigit())
except ImportError:
    # 2. Try PySide2 (Legacy Qt 5 official binding)
    try:
        import PySide2
        from PySide2 import QtCore, QtGui, QtNetwork, QtWidgets
        from PySide2.QtCore import Property, Qt, Signal, Slot
        from PySide2.QtWidgets import QAction, QActionGroup  # In Qt5 QAction was in QtWidgets

        # Re-export QAction in QtGui for Qt6 compatibility
        if not hasattr(QtGui, "QAction"):
            setattr(QtGui, "QAction", QAction)
        if not hasattr(QtGui, "QActionGroup"):
            setattr(QtGui, "QActionGroup", QActionGroup)

        QT_BINDING = "PySide2"
        version_str = getattr(PySide2, "__version__", "5.15.0")
        QT_VERSION = tuple(int(x) for x in version_str.split(".")[:3] if x.isdigit())
    except ImportError:
        # 3. Try PyQt5 (Alternative legacy Qt 5 binding)
        try:
            import PyQt5
            from PyQt5 import QtCore, QtGui, QtNetwork, QtWidgets
            from PyQt5.QtCore import Qt, pyqtProperty as Property, pyqtSignal as Signal, pyqtSlot as Slot
            from PyQt5.QtWidgets import QAction, QActionGroup

            if not hasattr(QtGui, "QAction"):
                setattr(QtGui, "QAction", QAction)
            if not hasattr(QtGui, "QActionGroup"):
                setattr(QtGui, "QActionGroup", QActionGroup)

            QT_BINDING = "PyQt5"
            version_str = getattr(QtCore, "PYQT_VERSION_STR", "5.15.0")
            QT_VERSION = tuple(int(x) for x in version_str.split(".")[:3] if x.isdigit())
        except ImportError:
            QT_BINDING = None
            QT_VERSION = (0, 0, 0)


def install_pyside6_shim() -> bool:
    """Install synthetic PySide6 modules into sys.modules if PySide6 is not natively available.
    
    This allows existing code that imports from PySide6 to function transparently
    on legacy systems running PySide2 or PyQt5.
    """
    if "PySide6" in sys.modules:
        return True
    if QT_BINDING is None:
        return False

    shim_root = types.ModuleType("PySide6")
    shim_root.QtCore = QtCore
    shim_root.QtGui = QtGui
    shim_root.QtWidgets = QtWidgets
    shim_root.QtNetwork = QtNetwork
    shim_root.__version__ = ".".join(map(str, QT_VERSION))

    sys.modules["PySide6"] = shim_root
    sys.modules["PySide6.QtCore"] = QtCore
    sys.modules["PySide6.QtGui"] = QtGui
    sys.modules["PySide6.QtWidgets"] = QtWidgets
    sys.modules["PySide6.QtNetwork"] = QtNetwork
    return True


# Auto-install shim if PySide6 is missing but another binding is active
if QT_BINDING in ("PySide2", "PyQt5") and "PySide6" not in sys.modules:
    install_pyside6_shim()
