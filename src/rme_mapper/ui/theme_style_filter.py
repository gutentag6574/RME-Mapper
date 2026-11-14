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
                "#ffffff": "#1F2937", "#fff": "#1F2937", "white": "#1F2937",
                "rgb(255,255,255)": "#1F2937",
                "#f5f6f8": "#111827", "#f8fafc": "#111827",
                "#f1f5f9": "#293548", "#f3f4f6": "#293548", "#f5f7fa": "#111827",
                "#eff6ff": "#1E3A5F", "#dbeafe": "#1E3A5F", "#e0edff": "#1E3A5F",
                "#fee2e2": "#450A0A", "#fef2f2": "#450A0A",
            }
            foregrounds = {
                "#202124": "#F1F5F9", "#0f172a": "#F1F5F9", "#1e293b": "#F1F5F9",
                "#000000": "#F1F5F9", "#000": "#F1F5F9", "black": "#F1F5F9",
                "rgb(0,0,0)": "#F1F5F9",
                "#334155": "#CBD5E1", "#64748b": "#CBD5E1", "#6b7280": "#CBD5E1",
                "#475569": "#CBD5E1", "#9ca3af": "#94A3B8", "#dc2626": "#FCA5A5",
            }
            borders = {
                "#e2e8f0": "#475569", "#d9dde3": "#475569", "#cbd5e1": "#475569",
                "#bfdbfe": "#1D4ED8", "#999999": "#64748B", "#999": "#64748B",
                "#cccccc": "#475569", "#ccc": "#475569", "#dddddd": "#475569", "#ddd": "#475569",
            }

            def _normalize_color_token(token: str) -> str:
                low = token.strip().lower()
                if low.startswith("rgb("):
                    low = re.sub(r"\s+", "", low)
                elif re.fullmatch(r"#[0-9a-f]{3}", low):
                    low = "#" + "".join(ch * 2 for ch in low[1:])
                return low

            color_token_re = r"(?:#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{3}|rgb\([^)]*\)|\b(?:white|black)\b)"

            def _replace_bg_fg(match):
                prop, color = match.group(1), match.group(2)
                norm = _normalize_color_token(color)
                palette = foregrounds if prop.lower() == "color" else backgrounds
                mapped = palette.get(norm, palette.get(color.strip().lower(), color))
                return f"{prop}: {mapped}"

            themed = re.sub(
                rf"(?<![\w-])(background(?:-color)?|color)\s*:\s*({color_token_re})",
                _replace_bg_fg,
                original,
                flags=re.IGNORECASE,
            )

            def _replace_border(match):
                prop, rest = match.group(1), match.group(2)
                updated_rest = re.sub(
                    color_token_re,
                    lambda cm: borders.get(_normalize_color_token(cm.group(0)), borders.get(cm.group(0).lower(), cm.group(0))),
                    rest,
                    flags=re.IGNORECASE,
                )
                return f"{prop}: {updated_rest}"

            themed = re.sub(
                r"(?<![\w-])(border(?:-(?:top|right|bottom|left))?(?:-color)?)\s*:\s*([^;\}]+)",
                _replace_border,
                themed,
                flags=re.IGNORECASE,
            )
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
