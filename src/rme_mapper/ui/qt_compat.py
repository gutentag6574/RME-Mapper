"""Re-export of central qt_compat module for UI components."""
from __future__ import annotations

from rme_mapper.qt_compat import (
    QT_BINDING,
    QT_VERSION,
    Property,
    QAction,
    QActionGroup,
    Qt,
    QtCore,
    QtGui,
    QtNetwork,
    QtWidgets,
    Signal,
    Slot,
    install_pyside6_shim,
)

__all__ = [
    "QT_BINDING",
    "QT_VERSION",
    "QtCore",
    "QtGui",
    "QtWidgets",
    "QtNetwork",
    "Qt",
    "Signal",
    "Slot",
    "Property",
    "QAction",
    "QActionGroup",
    "install_pyside6_shim",
]
