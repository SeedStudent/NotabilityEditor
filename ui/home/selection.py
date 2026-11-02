"""Home notebook list with explicit batch selection and scoped shortcuts."""
from PyQt6.QtCore import Qt, QItemSelectionModel, pyqtSignal
from PyQt6.QtWidgets import QListWidget, QAbstractItemView


class NotebookList(QListWidget):
    batchChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.batch = False
        self.anchor = None
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.itemSelectionChanged.connect(self._selection_changed)
        self.setAccessibleName('笔记列表')
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def _selection_changed(self):
        if len(self.selectedItems()) > 1:
            self.batch = True
        if not self.selectedItems():
            self.batch = False
        self.viewport().update()
        self.batchChanged.emit()

    def selectAll(self):
        if not self.isEnabled():
            return
        self.batch = bool(self.count())
        super().selectAll()
        self.batchChanged.emit()
        self.viewport().update()

    def cancel_selection(self):
        self.batch = False
        self.anchor = None
        self.clearSelection()
        self.setCurrentRow(-1)
        self.batchChanged.emit()
        self.viewport().update()

    def mousePressEvent(self, event):
        self._handled_press = False
        index = self.indexAt(event.position().toPoint())
        if event.button() != Qt.MouseButton.LeftButton or not index.isValid():
            if index.isValid():
                super().mousePressEvent(event)
            return
        rect = self.visualRect(index)
        checkbox = self.itemDelegate().check_rect(rect)
        modifiers = event.modifiers()
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        toggle = bool(modifiers & Qt.KeyboardModifier.ControlModifier) or checkbox.contains(event.position())
        if self.batch or toggle or shift:
            self._handled_press = True
            self.batch = True
            if shift and self.anchor is not None:
                if not (modifiers & Qt.KeyboardModifier.ControlModifier):
                    self.clearSelection()
                for row in range(min(self.anchor,index.row()),max(self.anchor,index.row())+1):
                    self.item(row).setSelected(True)
            else:
                self.item(index.row()).setSelected(not self.item(index.row()).isSelected())
                self.anchor = index.row()
            self.selectionModel().setCurrentIndex(index,QItemSelectionModel.SelectionFlag.NoUpdate)
            self.batch = bool(self.selectedItems())
            self._selection_changed()
            event.accept()
            return
        self.anchor = index.row()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self,'_handled_press',False):
            self._handled_press = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.batch:
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_selection()
            event.accept()
        elif event.key() == Qt.Key.Key_Space and self.currentItem():
            self.batch = True
            self.currentItem().setSelected(not self.currentItem().isSelected())
            self._selection_changed()
            event.accept()
        elif self.batch and event.key() in (Qt.Key.Key_Enter,Qt.Key.Key_Return):
            event.accept()
        else:
            super().keyPressEvent(event)
