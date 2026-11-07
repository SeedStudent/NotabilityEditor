"""Content-sized editor buttons and a toolbar row that keeps every action visible."""
from PyQt6.QtCore import QSize, QRect, Qt
from PyQt6.QtGui import QFont, QFontMetrics, QIcon, QPalette
from PyQt6.QtWidgets import (QWidget, QToolButton, QHBoxLayout, QGridLayout,
                             QSizePolicy, QStyle, QStyleOptionToolButton, QStylePainter)


class ToolbarButton(QToolButton):
    """Use the same padding and icon gap for labels of any length."""
    SIDE_PADDING = 10
    ICON_GAP = 6
    HEIGHT = 38

    def __init__(self, parent=None, *, icon_only=False):
        super().__init__(parent)
        self.setObjectName('toolbarAction')
        self.setIconSize(QSize(20, 20))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if icon_only
                                else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        if self.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly:
            return QSize(self.HEIGHT, self.HEIGHT)
        # Reserve the selected weight before selection, so clicking never shifts neighbours.
        selected_font = QFont(self.font())
        selected_font.setWeight(QFont.Weight.DemiBold)
        text_width = max(QFontMetrics(self.font()).horizontalAdvance(self.text()),
                         QFontMetrics(selected_font).horizontalAdvance(self.text()))
        icon_width = 0 if self.icon().isNull() else self.iconSize().width() + self.ICON_GAP
        return QSize(self.SIDE_PADDING * 2 + icon_width + text_width, self.HEIGHT)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        icon, text = QIcon(option.icon), option.text
        option.icon, option.text = QIcon(), ''
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)
        icon_only = self.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
        icon_size = self.iconSize()
        x = (self.width() - icon_size.width()) // 2 if icon_only else self.SIDE_PADDING
        icon_rect = QRect(x, (self.height() - icon_size.height()) // 2,
                          icon_size.width(), icon_size.height())
        icon_rect = QStyle.visualRect(self.layoutDirection(), self.rect(), icon_rect)
        mode = QIcon.Mode.Disabled if not self.isEnabled() else QIcon.Mode.Normal
        state = QIcon.State.On if self.isChecked() else QIcon.State.Off
        if not icon.isNull():
            icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter, mode, state)
        if not icon_only:
            text_x = self.SIDE_PADDING + (0 if icon.isNull() else icon_size.width() + self.ICON_GAP)
            text_rect = QRect(text_x, 0, self.width() - text_x - self.SIDE_PADDING, self.height())
            text_rect = QStyle.visualRect(self.layoutDirection(), self.rect(), text_rect)
            color_group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
            painter.setPen(option.palette.color(color_group, QPalette.ColorRole.ButtonText))
            alignment = Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight
                         if self.layoutDirection() == Qt.LayoutDirection.RightToLeft else Qt.AlignmentFlag.AlignLeft)
            painter.drawText(text_rect, alignment, text)


class EditorToolRow(QWidget):
    """Move the command group below the tools when a single row no longer fits."""
    GROUP_GAP = 12
    ROW_GAP = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.tools = QWidget(self)
        self.commands = QWidget(self)
        self.tools_layout = QHBoxLayout(self.tools)
        self.commands_layout = QHBoxLayout(self.commands)
        for layout in (self.tools_layout, self.commands_layout):
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(self.GROUP_GAP)
        self.grid.setVerticalSpacing(self.ROW_GAP)
        self.grid.setColumnStretch(0, 1)
        self.wrapped = None
        self.sync_layout()

    def minimumSizeHint(self):
        return QSize(max(self.tools.minimumSizeHint().width(), self.commands.minimumSizeHint().width()),
                     max(self.tools.sizeHint().height(), self.commands.sizeHint().height()))

    def sizeHint(self):
        return QSize(self.tools.sizeHint().width() + self.commands.sizeHint().width() + self.GROUP_GAP,
                     self.height())

    def sync_layout(self):
        needed = self.tools.sizeHint().width() + self.commands.sizeHint().width() + self.GROUP_GAP
        wrapped = self.width() < needed
        if wrapped != self.wrapped:
            self.grid.removeWidget(self.tools)
            self.grid.removeWidget(self.commands)
            self.wrapped = wrapped
            if wrapped:
                self.grid.addWidget(self.tools, 0, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
                self.grid.addWidget(self.commands, 1, 0, 1, 2, Qt.AlignmentFlag.AlignRight)
            else:
                self.grid.addWidget(self.tools, 0, 0, Qt.AlignmentFlag.AlignLeft)
                self.grid.addWidget(self.commands, 0, 1, Qt.AlignmentFlag.AlignRight)
        height = max(self.tools.sizeHint().height(), self.commands.sizeHint().height())
        if wrapped:
            height = self.tools.sizeHint().height() + self.commands.sizeHint().height() + self.ROW_GAP
        self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync_layout()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_layout()
