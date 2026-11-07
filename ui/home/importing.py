"""Cancellable background NTB imports; library indexing stays on the UI thread."""
import os
import stat
import threading
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from formats.ne_loader import prepare_note, LoadCancelled
from .library import copy_note, import_category_directory, identity, ImportCancelled
from .hierarchy import import_category_path


def ntb_sources(paths):
    result, seen = [], set()
    for path in paths:
        path = Path(path)
        if not path.is_dir() and (path.suffix.lower() != '.ntb' or not path.is_file()):
            continue
        key = identity(path)
        if key not in seen:
            seen.add(key)
            result.append(str(path.resolve()))
    return tuple(result)


class BatchImportWorker(QThread):
    progress = pyqtSignal(int, str)
    ready = pyqtSignal(str, str, object)

    def __init__(self, paths, parent=None, *, category_paths=None):
        super().__init__(parent)
        self.paths = tuple(paths)
        self.stop = threading.Event()
        self.failures = []
        self.completed = 0
        self.total = 0
        self.scanned = False
        self.category_paths = category_paths or {}

    def category_path(self, parts):
        parts = import_category_path(parts)
        return self.category_paths.get(tuple(name.casefold() for name in parts), parts)

    def scan(self):
        items, seen = [], set()
        def add(path, category):
            key = identity(path)
            if key not in seen:
                seen.add(key);items.append((str(path), category))
        # A selected folder determines the category of overlapping file selections.
        for source in sorted(self.paths, key=lambda path: not Path(path).is_dir()):
            if self.stop.is_set():return items
            source = Path(source)
            found = 0
            try:
                if source.is_file():
                    add(source, ());continue
                category = self.category_path((source.name,))
                pending, visited = [(source, category)], set()
                while pending:
                    if self.stop.is_set():return items
                    directory, category = pending.pop()
                    self.progress.emit(0, '正在扫描文件夹：' + str(directory))
                    try:
                        info = directory.stat()
                        key = (info.st_dev, info.st_ino) if info.st_ino else identity(directory)
                        if key in visited:continue
                        visited.add(key)
                        with os.scandir(directory) as iterator:
                            entries = sorted(iterator, key=lambda entry: entry.name)
                    except OSError as exc:
                        self.failures.append((str(directory), str(exc)));continue
                    folders = []
                    for entry in entries:
                        if self.stop.is_set():return items
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if entry.is_symlink():continue
                            path = Path(entry.path)
                            if stat.S_ISDIR(info.st_mode):
                                if not (getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                                    child = self.category_path(category + (entry.name,)) if directory == source else category
                                    folders.append((path, child))
                            elif stat.S_ISREG(info.st_mode) and path.suffix.lower() == '.ntb':
                                found += 1;add(path, category)
                        except (OSError, ValueError) as exc:
                            self.failures.append((entry.path, str(exc)))
                    pending.extend(reversed(folders))
                if not found:self.failures.append((str(source), '文件夹内未找到可导入的 NTB 笔记。'))
            except (OSError, ValueError) as exc:
                self.failures.append((str(source), str(exc)))
        self.scanned = True
        return items

    def run(self):
        try:
            items = self.scan()
        except Exception as exc:
            self.failures.append(('扫描导入目录', str(exc)))
            return
        total = self.total = len(items)
        for index, (source, category) in enumerate(items):
            if self.stop.is_set():
                break
            target = None
            prepared = None
            created_directories = []
            def report(value, message):
                self.progress.emit(min(99, int((index * 100 + value) / total)),
                    f'{index + 1}/{total} · {Path(source).name}\n{message}')
            try:
                report(0, '正在复制到本机笔记库…')
                directory = import_category_directory(category)
                candidate = directory
                for _ in range(len(category) or 1):
                    if candidate.exists():break
                    created_directories.append(candidate)
                    candidate = candidate.parent
                target = copy_note(source, directory,
                    lambda value: report(value * .35, '正在复制到本机笔记库…'), self.stop.is_set)
                prepared = prepare_note(target,
                    lambda value, message: report(35 + value * .65, message), self.stop.is_set)
                if self.stop.is_set():
                    raise ImportCancelled()
                prepared.cleanup();prepared = None
                self.ready.emit(source, target, category)
                target = None  # A validated copy now belongs to the UI's indexing step.
                self.completed += 1
            except (ImportCancelled, LoadCancelled):
                break
            except Exception as exc:
                self.failures.append((source, str(exc)))
                self.completed += 1
            finally:
                try:
                    if prepared is not None:
                        prepared.cleanup()
                    if target is not None:
                        Path(target).unlink(missing_ok=True)
                except OSError as exc:
                    message = f'无法清理未导入副本：{target}\n{exc}'
                    if self.failures and self.failures[-1][0] == source:
                        self.failures[-1] = (source, self.failures[-1][1] + '\n' + message)
                    else:
                        self.failures.append((source, message))
                for directory in created_directories:
                    try:directory.rmdir()
                    except OSError:pass  # Keep existing directories and every retained notebook.
