"""Adapt legacy inline widget colors when an application theme changes."""
from __future__ import annotations
import re
from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QApplication, QWidget


class ThemeStyleFilter(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.dark = False
        self.busy = False

    def eventFilter(self, obj, event):
        try:
            if not self.busy and isinstance(obj, QWidget) and event.type() in (QEvent.Type.Polish, QEvent.Type.Show):
                self.adapt(obj)
        except RuntimeError:
            # Qt may send final events while a Python widget wrapper is deleted.
            pass
        return False

    def adapt(self, widget):
        style = widget.styleSheet()
        previous = widget.property("uxThemedStyle")
        original = widget.property("uxOriginalStyle")
        if original is None or style != previous:
            original = style
            widget.setProperty("uxOriginalStyle", original)
        if not original:
            return
        themed = original
        if self.dark:
            backgrounds = {
                "#ffffff": "#1F2937", "#f5f6f8": "#111827", "#f8fafc": "#111827",
                "#f1f5f9": "#293548", "#f3f4f6": "#293548", "#f5f7fa": "#111827",
                "#eff6ff": "#1E3A5F", "#fee2e2": "#450A0A", "#fef2f2": "#450A0A",
            }
            foregrounds = {
                "#202124": "#F1F5F9", "#0f172a": "#F1F5F9", "#1e293b": "#F1F5F9",
                "#334155": "#CBD5E1", "#64748b": "#CBD5E1", "#6b7280": "#CBD5E1",
                "#475569": "#CBD5E1", "#9ca3af": "#94A3B8", "#dc2626": "#FCA5A5",
            }
            def replace(match):
                prop, color = match.group(1), match.group(2)
                palette = foregrounds if prop.lower() == "color" else backgrounds
                return prop + ": " + palette.get(color.lower(), color)
            themed = re.sub(r"(?<![\w-])(background(?:-color)?|color)\s*:\s*(#[0-9A-Fa-f]{6})", replace, original)
        self.busy = True
        try:
            widget.setProperty("uxThemedStyle", themed)
            if style != themed:
                widget.setStyleSheet(themed)
        finally:
            self.busy = False

    def apply(self, dark):
        self.dark = dark
        for widget in QApplication.allWidgets():
            self.adapt(widget)
