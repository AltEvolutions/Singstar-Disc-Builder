# ruff: noqa
from __future__ import annotations

"""Qt item delegates + style helpers (internal).

Extracted from `spcdb_tool/qt/main_window.py` as part of the incremental Qt refactor.
Behavior is intended to be unchanged.

This module is imported lazily via `MainWindow` (Qt-only path).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QStyle,
    QStyleOptionViewItem,
    QStyleOption,
    QStyledItemDelegate,
    QProxyStyle,
)

# Data role used by the Songs table to mark disc-group header rows.
# We keep it palette-friendly by using the delegate for styling.
try:
    _SONGS_ROW_KIND_ROLE = int(Qt.UserRole) + 77
except Exception:
    _SONGS_ROW_KIND_ROLE = 0x0100 + 77


class _NoFocusItemDelegate(QStyledItemDelegate):
    """Paint items without native focus/selection markers.

    Some native styles draw a thin accent bar (often blue) on the current/selected
    cell. We suppress that while still allowing keyboard navigation, and we draw
    our own subtle selection overlay so row-state tints (green/red) remain visible.
    """

    def paint(self, painter, option, index):  # type: ignore[override]
        is_group_header = False
        try:
            kind = index.sibling(int(index.row()), 1).data(_SONGS_ROW_KIND_ROLE)
            is_group_header = (str(kind) == "group_header")
        except Exception:
            pass

        try:
            opt = QStyleOptionViewItem(option)

            # Capture whether Qt thinks this cell is selected, then clear the flag
            # so the native style doesn't draw its accent marker.
            try:
                is_selected = bool(opt.state & QStyle.State_Selected)
            except Exception:
                is_selected = False

            # Remove focus/current-item decorations and native selection painting.
            try:
                opt.state &= ~QStyle.State_HasFocus
            except Exception:
                pass
            try:
                opt.state &= ~QStyle.State_Selected
            except Exception:
                pass
            try:
                opt.showDecorationSelected = False
            except Exception:
                pass
            if is_group_header:
                try:
                    from PySide6.QtGui import QColor, QBrush, QPalette
                    base = opt.palette.color(QPalette.AlternateBase)
                    c = QColor(base)
                    c.setAlpha(70)
                    opt.backgroundBrush = QBrush(c)
                except Exception:
                    pass
        except Exception:
            opt = option
            is_selected = False

        super().paint(painter, opt, index)

        if is_group_header:
            try:
                from PySide6.QtGui import QColor, QPen, QPalette
                painter.save()
                lc = opt.palette.color(QPalette.Mid)
                c = QColor(lc)
                c.setAlpha(140)
                painter.setPen(QPen(c))
                r = option.rect
                painter.drawLine(r.bottomLeft(), r.bottomRight())
                painter.restore()
            except Exception:
                pass

        # Draw a very subtle overlay for selection so it's still readable,
        # but doesn't wipe out row-state tinting.
        if is_selected:
            try:
                from PySide6.QtGui import QColor
                painter.save()
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 255, 255, 18))
                painter.drawRect(option.rect)
                painter.restore()
            except Exception:
                pass



class _SourcesTintDelegate(QStyledItemDelegate):
    """Sources row tinting that survives no-focus / no-accent styling.

    We draw the row-state tint ourselves (green for Base, red for Packed/Needs extract/Errors),
    then let the styled delegate paint the text/icon content on top.
    """

    def paint(self, painter, option, index):  # type: ignore[override]
        # Determine row tint
        tint = None
        try:
            row = int(index.row())
        except Exception:
            row = -1

        try:
            state_txt = str(index.sibling(row, 1).data() or "")
        except Exception:
            state_txt = ""

        is_base = (row == 0)
        needs_attention = ((("Packed" in state_txt) or ("Needs extract" in state_txt)) and ("Extracted" not in state_txt)) or ("Errors" in state_txt)

        try:
            from PySide6.QtGui import QColor, QBrush, QPalette
        except Exception:
            QColor = None  # type: ignore[assignment]
            QBrush = None  # type: ignore[assignment]
            QPalette = None  # type: ignore[assignment]

        if is_base and QColor is not None:
            tint = QColor(40, 100, 40, 180)
        elif needs_attention and QColor is not None:
            tint = QColor(155, 45, 45, 180)

        if tint is not None:
            try:
                painter.save()
                painter.setPen(Qt.NoPen)
                painter.setBrush(tint)
                painter.drawRect(option.rect)
                painter.restore()
            except Exception:
                pass

        # Paint content without native focus/selection markers (same philosophy as _NoFocusItemDelegate),
        # and keep the base background transparent so our tint remains visible.
        try:
            opt = QStyleOptionViewItem(option)
            try:
                is_selected = bool(opt.state & QStyle.State_Selected)
            except Exception:
                is_selected = False

            try:
                opt.state &= ~QStyle.State_HasFocus
            except Exception:
                pass
            try:
                opt.state &= ~QStyle.State_Selected
            except Exception:
                pass
            try:
                opt.showDecorationSelected = False
            except Exception:
                pass

            # Ensure the style doesn't paint an opaque background over our tint.
            try:
                if QColor is not None and QBrush is not None:
                    opt.backgroundBrush = QBrush(QColor(0, 0, 0, 0))
            except Exception:
                pass
            try:
                if QColor is not None and QBrush is not None and QPalette is not None:
                    pal = opt.palette
                    pal.setBrush(QPalette.Base, QBrush(QColor(0, 0, 0, 0)))
                    pal.setBrush(QPalette.Window, QBrush(QColor(0, 0, 0, 0)))
                    pal.setBrush(QPalette.AlternateBase, QBrush(QColor(0, 0, 0, 0)))
                    opt.palette = pal
            except Exception:
                pass
        except Exception:
            opt = option
            is_selected = False

        QStyledItemDelegate.paint(self, painter, opt, index)

        # Subtle selection overlay so selection stays readable without wiping out tint.
        if is_selected:
            try:
                from PySide6.QtGui import QColor as _QColor
                painter.save()
                painter.setPen(Qt.NoPen)
                painter.setBrush(_QColor(255, 255, 255, 18))
                painter.drawRect(option.rect)
                painter.restore()
            except Exception:
                pass

class _NoAccentProxyStyle(QProxyStyle):
    """Proxy style that suppresses native selection accent markers.

    Some native styles paint a thin colored bar on the left edge of selected
    cells/rows, or a focus rectangle that looks like little blue ticks on
    every selected cell. We suppress those while leaving our delegate in
    charge of a subtle selection overlay.
    """

    def drawPrimitive(self, element, option, painter, widget=None):  # type: ignore[override]
        try:
            # Suppress focus rectangles (often rendered as small blue markers).
            if element == QStyle.PE_FrameFocusRect:
                return
            if element in (QStyle.PE_PanelItemViewItem, QStyle.PE_PanelItemViewRow):
                opt = QStyleOption(option)
                try:
                    opt.state &= ~QStyle.State_Selected
                except Exception:
                    pass
                try:
                    opt.state &= ~QStyle.State_HasFocus
                except Exception:
                    pass
                return super().drawPrimitive(element, opt, painter, widget)
        except Exception:
            pass
        return super().drawPrimitive(element, option, painter, widget)

    def drawControl(self, element, option, painter, widget=None):  # type: ignore[override]
        try:
            if element == QStyle.CE_ItemViewItem:
                opt = QStyleOptionViewItem(option)
                try:
                    opt.state &= ~QStyle.State_HasFocus
                except Exception:
                    pass
                try:
                    opt.state &= ~QStyle.State_Selected
                except Exception:
                    pass
                try:
                    opt.showDecorationSelected = False
                except Exception:
                    pass
                return super().drawControl(element, opt, painter, widget)
        except Exception:
            pass
        return super().drawControl(element, option, painter, widget)


_TABLE_NOFOCUS_QSS = (
    "QTableView { show-decoration-selected: 0; } "
    "QAbstractItemView::item { outline: none; border: 0px; } "
    "QAbstractItemView::item:focus { outline: none; border: 0px; } "
    # Keep Qt selection background transparent; our delegate draws a subtle overlay.
    "QAbstractItemView { selection-background-color: rgba(0,0,0,0); } "
    "QAbstractItemView::item:selected { background-color: rgba(0,0,0,0); } "
    "QAbstractItemView::item:selected:active { background-color: rgba(0,0,0,0); } "
    "QAbstractItemView::item:selected:!active { background-color: rgba(0,0,0,0); } "
    # Defuse left-edge accent markers in some native styles.
    "QTableView::item:selected { border-left: 0px solid transparent; border: 0px; } "
    "QTableView::item { border: 0px; } "
)



