"""Focused Home dialogs with validation next to the field being edited."""
from pathlib import Path
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                            QLineEdit, QPushButton, QListWidget, QListWidgetItem)
from ui.ne_toolbar import tool_icon
from .library import validate_category_name
from .operations import is_managed


class NewCategoryDialog(QDialog):
    def __init__(self, parent, library):
        super().__init__(parent)
        self.library = library
        self.created_key = None
        self.setWindowTitle('新建分类')
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFixedWidth(440)
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)
        header = QHBoxLayout()
        header.setSpacing(12)
        icon = QLabel()
        icon.setObjectName('categoryIcon')
        icon.setFixedSize(44, 44)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(tool_icon('open', '#2563eb').pixmap(QSize(26, 26)))
        header.addWidget(icon)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = QLabel('新建分类')
        title.setObjectName('categoryTitle')
        titles.addWidget(title)
        subtitle = QLabel('把同一主题的笔记整理在一起')
        subtitle.setObjectName('categorySubtitle')
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        layout.addLayout(header)
        field = QVBoxLayout()
        field.setSpacing(8)
        caption = QHBoxLayout()
        label = QLabel('分类名称')
        caption.addWidget(label)
        caption.addStretch()
        self.counter = QLabel('0 / 64')
        self.counter.setObjectName('categorySubtitle')
        caption.addWidget(self.counter)
        field.addLayout(caption)
        self.name = QLineEdit()
        self.name.setAccessibleName('分类名称')
        self.name.setPlaceholderText('例如：课程笔记、工作项目')
        self.name.setMaxLength(64)
        self.name.setClearButtonEnabled(True)
        label.setBuddy(self.name)
        field.addWidget(self.name)
        self.hint = QLabel()
        self.hint.setObjectName('categoryHint')
        self.hint.setWordWrap(True)
        self.hint.setMinimumHeight(34)
        field.addWidget(self.hint)
        layout.addLayout(field)
        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addStretch()
        self.cancel = QPushButton('取消')
        self.cancel.setAutoDefault(False)
        self.cancel.clicked.connect(self.reject)
        footer.addWidget(self.cancel)
        self.create = QPushButton('创建分类')
        self.create.setObjectName('createCategory')
        self.create.setDefault(True)
        self.create.clicked.connect(self.submit)
        footer.addWidget(self.create)
        layout.addLayout(footer)
        self.name.textChanged.connect(self.validate)
        self.validate()
        self.name.setFocus()

    def validation_error(self):
        name = self.name.text().strip()
        if not name:
            return ''
        try:
            validate_category_name(name)
        except ValueError:
            if name == '未分类':
                return '“未分类”为系统分类，请换一个名称。'
            return '名称不能包含文件夹禁用字符，也不能使用系统保留名称。'
        if name.casefold() in (n.casefold() for n in self.library.categories.values()):
            return '已有同名分类，请换一个名称。'
        return ''

    def show_error(self, error):
        self.hint.setText(error or '最多 64 个字符，不支持 / \\ : * ? " < > |')
        for widget in (self.name,self.hint):
            widget.setProperty('invalid', bool(error))
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def validate(self):
        error = self.validation_error()
        self.counter.setText(f'{len(self.name.text())} / 64')
        self.show_error(error)
        self.create.setEnabled(bool(self.name.text().strip()) and not error)

    def submit(self):
        self.validate()
        if not self.create.isEnabled():
            return
        self.create.setEnabled(False)
        try:
            self.created_key = self.library.add_category(self.name.text().strip())
        except (OSError,ValueError) as exc:
            self.show_error('创建失败：' + str(exc))
            self.create.setEnabled(True)
            return
        self.accept()


class DeleteNotesDialog(QDialog):
    def __init__(self,parent,paths):
        super().__init__(parent)
        self.paths = tuple(paths)
        self.setWindowTitle('删除笔记')
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint,False)
        self.setFixedWidth(500)
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24,24,24,24)
        layout.setSpacing(16)
        title = QLabel(f'删除选中的 {len(paths)} 本笔记？')
        title.setObjectName('categoryTitle')
        title.setWordWrap(True)
        layout.addWidget(title)
        description = QLabel('文件将移至系统回收站，并从笔记列表移除。\n你可以从回收站恢复文件，再重新打开。')
        description.setObjectName('categorySubtitle')
        description.setWordWrap(True)
        layout.addWidget(description)
        self.files = QListWidget()
        self.files.setAccessibleName('待删除的笔记文件')
        self.files.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.files.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.files.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.files.setFixedHeight(min(176,54*len(paths)+12))
        for path in paths:
            item = QListWidgetItem(Path(path).name+'\n'+str(Path(path).parent))
            item.setToolTip(str(path))
            item.setSizeHint(QSize(420,54))
            self.files.addItem(item)
        layout.addWidget(self.files)
        self.external = sum(not is_managed(path) for path in paths)
        self.warning = QLabel(f'其中 {self.external} 本来自外部位置，外部原文件也会移至回收站。'
            if self.external else '移至回收站后，笔记的打开记录也会一并移除。')
        self.warning.setObjectName('deleteWarning')
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)
        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addStretch()
        self.cancel = QPushButton('取消')
        self.cancel.setDefault(True)
        self.cancel.clicked.connect(self.reject)
        footer.addWidget(self.cancel)
        self.confirm = QPushButton('移至回收站')
        self.confirm.setObjectName('confirmDelete')
        self.confirm.setIcon(tool_icon('delete','#ffffff'))
        self.confirm.setAutoDefault(False)
        self.confirm.clicked.connect(self.accept)
        footer.addWidget(self.confirm)
        layout.addLayout(footer)
        self.cancel.setFocus()


STYLE = """
QDialog { background:#ffffff; }
QLabel { color:#334b6d; font-size:13px; background:transparent; }
QLabel#categoryIcon { background:#edf4ff; border-radius:12px; }
QLabel#categoryTitle { font-size:20px; font-weight:700; color:#1c3558; }
QLabel#categorySubtitle { color:#8090a8; font-size:12px; }
QLabel#categoryHint { color:#8795aa; font-size:12px; }
QLabel#categoryHint[invalid="true"] { color:#c34b55; }
QLineEdit { background:#f8faff; color:#263c5c; border:1px solid #d4dff0;
 border-radius:8px; padding:11px 12px; font-size:14px; selection-background-color:#dce8ff; }
QLineEdit:focus { background:#ffffff; border-color:#4d86ee; }
QLineEdit[invalid="true"] { border-color:#d77d85; background:#fffafb; }
QPushButton { background:#ffffff; color:#526988; border:1px solid #d4dff0;
 border-radius:8px; padding:9px 18px; font-size:13px; min-width:60px; }
QPushButton:hover { background:#f2f6fc; border-color:#a7bfe4; }
QPushButton:focus { border-color:#4d86ee; }
QPushButton#createCategory { background:#2563eb; color:#ffffff; border-color:#2563eb; }
QPushButton#createCategory:hover { background:#1d53cd; border-color:#1d53cd; }
QPushButton#createCategory:disabled { background:#e9eff9; color:#9aaac2; border-color:#e9eff9; }
QLabel#deleteWarning { background:#fff7f7; color:#b85a64; border-radius:7px; padding:10px; font-size:12px; }
QListWidget { background:#f8faff; color:#526988; border:1px solid #e0e7f2; border-radius:8px;
 padding:5px; font-size:12px; outline:0; }
QListWidget::item { padding:0 6px; }
QPushButton#confirmDelete { color:#ffffff; background:#c95765; border-color:#c95765; }
QPushButton#confirmDelete:hover { background:#b84252; border-color:#b84252; }
QPushButton#confirmDelete:focus { border-color:#8e2634; }
"""
