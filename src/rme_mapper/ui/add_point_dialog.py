"""Compatibility module for PointDialog.

This module re-exports PointDialog and AddPointDialog from point_dialog.py
for backward compatibility with existing tests and scripts.
"""

from rme_mapper.ui.point_dialog import (
    AddPointDialog,
    MarkerPreviewWidget,
    PointDialog,
    PointDialogData,
    decimal_to_dms,
)

__all__ = [
    "AddPointDialog",
    "PointDialog",
    "PointDialogData",
    "MarkerPreviewWidget",
    "decimal_to_dms",
]
