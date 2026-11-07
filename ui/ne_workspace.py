"""Home/editor routing around the existing native load/save pipeline."""
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, Qt
from PyQt6.QtWidgets import QStackedWidget, QFileDialog, QProgressDialog, QMessageBox

from ui.home.library import Library, ImportWorker
from ui.home.page import HomePage
from ui.editor.page import EditorPage


class DesktopWorkspace(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.library = Library(owner.color_settings)
        self.importer = None
        self.exiting = False
        self.sidebar_visible = not owner.page_sidebar.isHidden()
        self.editor = EditorPage(owner.takeCentralWidget())
        self.home = HomePage(self.library, new_note=owner.create_new_note,
            open_note=owner.choose_file, import_note=self.import_note,
            import_pdf=owner.import_pdf_as_ntb, open_path=owner.open_recent_file, import_folder=self.import_folder)
        self.home.changed.connect(self.library_changed)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.editor)
        owner.setCentralWidget(self.stack)
        owner._install_drop_target(self.home)
        owner._install_drop_target(self.home.notes.viewport())
        owner._install_drop_target(self.home.categories.viewport())
        file_menu = owner.menus['文件']
        self.home_action = owner.action(owner, '返回主页', self.return_home, 'Alt+Home')
        file_menu.insertAction(file_menu.actions()[0], self.home_action)
        self.import_action = owner.action(owner, '导入笔记到笔记库…', self.import_note)
        owner.import_menu.insertAction(owner.pdf_note_action, self.import_action)
        self.folder_import_action = owner.action(owner, '导入文件夹到笔记库…', self.import_folder)
        owner.import_menu.insertAction(owner.pdf_note_action, self.folder_import_action)
        self.show_home()

    def busy(self):
        owner = self.owner
        return bool(owner.worker or owner.saver or owner.pdf_importer or self.importer
                    or getattr(self.home,'batch_job',None))

    def refresh_state(self):
        busy = self.busy()
        at_home = self.stack.currentWidget() is self.home
        self.home.set_busy(busy)
        self.home_action.setEnabled(not busy and not at_home)
        self.import_action.setEnabled(not busy)
        self.folder_import_action.setEnabled(not busy and at_home)
        self.owner.page_toggle_action.setEnabled(not at_home and not busy)
        for name in ('编辑', '工具', '页面'):
            self.owner.menus[name].setEnabled(not at_home)
        for name, menu in self.owner.menus.items():
            menu.menuAction().setVisible(not at_home or name in ('文件', '设置', '帮助'))
        if at_home:
            self.owner.page_sidebar.hide()

    def record(self, path):
        self.library.record(path)
        self.home.refresh()

    def library_changed(self):
        from ui.ne_menus import refresh_recent_menu
        refresh_recent_menu(self.owner)

    def show_editor(self):
        owner = self.owner
        owner.fullscreen_action.setEnabled(True)
        self.stack.setCurrentWidget(self.editor)
        fullscreen=owner.editor_view.saved is not None
        owner.read_toolbar.setVisible(not fullscreen)
        owner.edit_toolbar.setVisible(not fullscreen)
        owner.page_sidebar.setVisible(self.sidebar_visible and not fullscreen)
        self.refresh_state()
        owner.editor_view.schedule_cursor_refresh()

    def show_home(self):
        owner = self.owner
        owner.editor_view.leave()
        owner.editor_view.cancel_drag()
        owner.fullscreen_action.setEnabled(False)
        self.stack.setCurrentWidget(self.home)
        owner.read_toolbar.hide()
        owner.edit_toolbar.hide()
        owner.page_sidebar.hide()
        self.home.refresh()
        self.refresh_state()
        owner.statusBar().showMessage('主页 · 拖入 NTB 或文件夹导入笔记库，文件夹名称作为分类名')

    def return_home(self):
        if self.busy() or self.stack.currentWidget() is self.home:
            return
        owner = self.owner
        if not owner.confirm_leave(self.return_home, continue_label='返回主页'):
            return
        self.sidebar_visible = not owner.page_sidebar.isHidden()
        old = owner.scroll.takeWidget()
        owner.close_document()
        owner.canvas = None
        owner.disk_bundle = None
        if old is not None:
            old.deleteLater()
        owner.page.setRange(1, 1)
        owner.count_label.setText(' / 0  ')
        self.show_home()
        owner.edit_changed()

    def import_folder(self, source=None):
        if self.busy() or self.stack.currentWidget() is not self.home:return
        if not isinstance(source, (str, Path)):
            source = QFileDialog.getExistingDirectory(self.owner, '导入文件夹 · 保留两级分类')
        if source:self.import_ntb_files([source])

    def import_ntb_files(self, paths):
        if self.busy() or self.stack.currentWidget() is not self.home:
            return
        from ui.home.importing import BatchImportWorker, ntb_sources
        paths = ntb_sources(paths)
        if not paths:
            return
        owner = self.owner
        names = {}
        for key, name in self.library.categories.items():
            parent = self.library.category_parents.get(key)
            parts = (self.library.categories[parent], name) if parent else (name,)
            names[tuple(part.casefold() for part in parts)] = parts
        worker = BatchImportWorker(paths, owner, category_paths=names)
        self.importer = worker
        progress = QProgressDialog('正在准备导入…', '取消', 0, 100, owner)
        progress.setWindowTitle('导入 NTB 笔记与文件夹')
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)
        progress.setAutoClose(False);progress.setAutoReset(False)
        progress.canceled.connect(worker.stop.set)
        imported, failures = [], []
        def update(value, message):
            progress.setLabelText(message);progress.setValue(value)
        worker.progress.connect(update)
        def index(source, target, category):
            try:
                self.library.record_import(target, category)
                from settings.ne_recent_files import add_recent_file
                add_recent_file(owner.color_settings, target)
                imported.append(target)
            except Exception as exc:
                failures.append((source, f'{exc}\n已保留副本：{target}'))
        worker.ready.connect(index)
        def finished():
            cancelled = worker.stop.is_set()
            progress.close();progress.deleteLater()
            self.importer = None
            failures.extend(worker.failures)
            remaining = worker.total - worker.completed
            summary = f'导入完成：成功 {len(imported)} 份，失败 {len(failures)} 份'
            if cancelled:summary = f'已取消导入：成功 {len(imported)} 份，失败 {len(failures)} 份，未导入 {remaining} 份'
            if cancelled and not worker.scanned:summary = '已取消文件夹扫描，未开始导入'
            self.home.result.setText(summary + ('\n' + '\n'.join(
                f'{Path(path).name}：{message}' for path, message in failures[:5]) if failures else ''))
            self.home.result.setToolTip('\n'.join(f'{path}：{message}' for path, message in failures))
            self.home.refresh();self.library_changed()
            from ui.ne_menus import refresh_menu_state
            refresh_menu_state(owner)
            owner.statusBar().showMessage(summary, 10000)
            worker.deleteLater()
        worker.finished.connect(finished)
        from ui.ne_menus import refresh_menu_state
        refresh_menu_state(owner)
        worker.start()

    def import_note(self, source=None):
        if self.busy():
            return
        owner = self.owner
        if not isinstance(source, (str, Path)):
            source, _ = QFileDialog.getOpenFileName(owner, '导入笔记到本机笔记库', '', '笔记文件 (*.ntb *.note)')
        if not source:
            return
        if not owner.confirm_leave(lambda: self.import_note(source), continue_label='导入笔记'):
            return
        worker = ImportWorker(source, owner)
        self.importer = worker
        progress = QProgressDialog('正在复制到本机笔记库…', '取消', 0, 100, owner)
        progress.setWindowTitle('导入笔记')
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(300)
        progress.setAutoClose(False)
        worker.progress.connect(progress.setValue)
        progress.canceled.connect(worker.stop.set)
        worker.failed.connect(lambda message: QMessageBox.warning(owner, '无法导入笔记', message))

        def finished():
            result = worker.result
            progress.close()
            progress.deleteLater()
            self.importer = None
            worker.deleteLater()
            from ui.ne_menus import refresh_menu_state
            refresh_menu_state(owner)
            if result and not self.exiting:
                # The existing reader validates the copy before it is indexed.
                QTimer.singleShot(0, lambda: owner.open_file(result, skip_leave_check=True))
            else:
                owner.statusBar().showMessage('笔记导入已取消或未完成', 4000)

        worker.finished.connect(finished)
        from ui.ne_menus import refresh_menu_state
        refresh_menu_state(owner)
        worker.start()
