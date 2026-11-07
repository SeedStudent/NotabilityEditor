"""Shape controls share the editor's palette, shortcuts and undo model."""
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QActionGroup, QColor
from PyQt6.QtWidgets import QLabel, QDoubleSpinBox, QToolButton, QColorDialog
from editing.ne_shape_tools import SHAPES
from ui.ne_colors import ColorPalette


def build_controls(owner, panel):
    from ui.ne_toolbar import (FavoriteSwatches, CustomColorButton,
                               restore_color, restore_number, tool_icon)
    settings = owner.color_settings
    owner.shape_kind = settings.value('shape/kind', 'rectangle')
    if not isinstance(owner.shape_kind, str) or owner.shape_kind not in dict(SHAPES):
        owner.shape_kind = 'rectangle'
    owner.current_shape_color = restore_color(settings.value('shape/color', '#e53935'), '#e53935')
    row = panel.pages['shape'][1]
    group = QActionGroup(panel)
    group.setExclusive(True)
    owner.shape_actions = {}
    def select_kind(kind):
        if hasattr(owner.canvas, 'finishGesture'): owner.canvas.finishGesture()
        owner.shape_kind = kind
        settings.setValue('shape/kind', kind)
        owner.select_tool('shape')
    for kind, label in SHAPES:
        action = owner.action(panel, label, lambda checked=False, k=kind: select_kind(k))
        action.setCheckable(True)
        action.setChecked(kind == owner.shape_kind)
        action.setIcon(tool_icon('shape_'+kind))
        action.setToolTip(label+'：拖动绘制；Shift 约束比例或角度')
        group.addAction(action)
        owner.shape_actions[kind] = action
        button = QToolButton(panel)
        button.setDefaultAction(action)
        button.setIconSize(QSize(21, 21))
        button.setFixedSize(34, 34)
        button.setAccessibleName(label)
        row.addWidget(button)
    panel.separator(row)
    row.addWidget(QLabel('颜色'))
    owner.shape_palette = ColorPalette(settings, 'shape', panel)
    def apply_color(color):
        owner.current_shape_color = color
        settings.setValue('shape/color', color)
        settings.sync()
        palette.sync_selection()
        custom.setColor(color)
        owner.update_edit_settings()
    palette = FavoriteSwatches(owner.shape_palette, lambda: owner.current_shape_color,
                              apply_color, panel)
    row.addWidget(palette)
    custom = CustomColorButton(owner.current_shape_color, panel)
    custom.setAccessibleName('图形自定义颜色')
    custom.setToolTip('选择图形颜色')
    def choose_color():
        color = QColorDialog.getColor(QColor(owner.current_shape_color), owner, '图形颜色')
        if color.isValid():
            value = color.name()
            owner.shape_palette.add(value)
            apply_color(value)
    custom.clicked.connect(choose_color)
    row.addWidget(custom)
    panel.separator(row)
    row.addWidget(QLabel('线宽'))
    owner.shape_size = QDoubleSpinBox()
    owner.shape_size.setDecimals(1)
    owner.shape_size.setRange(.1, 128)
    owner.shape_size.setSingleStep(.1)
    owner.shape_size.setValue(restore_number(settings.value('shape/width', 2), 2, .1, 128))
    owner.shape_size.setFixedWidth(72)
    owner.shape_size.setAccessibleName('图形线宽')
    owner.shape_size.valueChanged.connect(owner.update_edit_settings)
    owner.shape_size.valueChanged.connect(lambda v: owner.remember_tool_setting('shape/width', v))
    row.addWidget(owner.shape_size)
    row.addStretch()
    row.addWidget(QLabel('拖动绘制 · Shift 约束 · Esc 取消'))
