"""Persistent references and categories; importing never overwrites the source."""
import json
import os
import re
from pathlib import Path
import tempfile
import threading
import time
import uuid
from copy import deepcopy

from PyQt6.QtCore import QSettings, QThread, pyqtSignal
from settings.ne_recent_files import canonical_path, read_recent_files
from .storage import LibraryStore, validate_library


def identity(path):
    return os.path.normcase(canonical_path(path))


class Library:
    KEY = 'windows_home/library'

    def __init__(self, settings, *, index_path=None):
        self.settings = settings
        self.store = LibraryStore(index_path)
        self.data = self.store.load()
        migrated = self.data is None
        self.storage_notice = self.store.notice
        if migrated:
            raw = settings.value(self.KEY, '', type=str)
            try:
                self.data = validate_library(json.loads(raw) if raw else {})
            except (ValueError, TypeError):
                settings.setValue(self.KEY + '_recovery', raw)
                self.data = validate_library({})
        self._committed_data = deepcopy(self.data)
        try:
            changed = self.adopt_legacy_history()
            if (migrated or self.store.recovered) and not changed:
                self.commit()
        except OSError as exc:
            self.storage_notice = str(exc)

    def adopt_legacy_history(self):
        """0.7.6-Beta uses the same QSettings namespace and array schema.

        Promote references into the library index without copying notebooks or
        changing the original recent-file/reading-position records. Missing
        files remain indexed and are hidden by entries() until available.
        """
        positions={}
        count=self.settings.beginReadArray('view/last-pages')
        try:
            for i in range(count):
                self.settings.setArrayIndex(i)
                path=self.settings.value('path','',type=str)
                try:updated=float(self.settings.value('updated_at',0))
                except (TypeError,ValueError):updated=0
                if path:positions[identity(path)]=updated
        finally:
            self.settings.endArray()
        changed=False
        recent=read_recent_files(self.settings)
        for rank,path in enumerate(recent):
            key=identity(path)
            if key in self.data['notes']:continue
            self.data['notes'][key]=dict(path=path,category='',
                opened=positions.get(key) or time.time()-rank)
            changed=True
        if changed:self.commit()
        return changed

    @property
    def categories(self):
        return self.data['categories']

    def commit(self):
        try:
            self.store.save(self.data)
        except (OSError, ValueError) as exc:
            self.data = deepcopy(self._committed_data)
            raise OSError('无法保存分类与笔记索引，请检查用户数据目录：'
                          + str(self.store.path.parent)) from exc
        self._committed_data = deepcopy(self.data)
        # Retain a compatibility mirror for older releases; JSON is authoritative.
        if (os.environ.get('NV_DISABLE_RECENT_FILES') == '1'
                and self.settings.format() == QSettings.Format.NativeFormat):
            return
        self.settings.setValue(self.KEY, json.dumps(self.data, ensure_ascii=False))
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            self.storage_notice = '分类已保存到用户数据文件，旧版设置同步未完成。'

    def record(self, path):
        path = canonical_path(path)
        entry = self.data['notes'].setdefault(identity(path), {'path': path, 'category': ''})
        entry.update(path=path, opened=time.time())
        self.commit()

    def add_category(self, name):
        name = validate_category_name(name)
        if name.casefold() in (n.casefold() for n in self.categories.values()):
            raise ValueError('已有同名分类。')
        key = uuid.uuid4().hex
        category_directory(name).mkdir(parents=True, exist_ok=True)
        self.categories[key] = name
        self.commit()
        return key

    def rename_category(self, key, name):
        name = validate_category_name(name)
        if any(k != key and n.casefold() == name.casefold() for k, n in self.categories.items()):
            raise ValueError('已有同名分类。')
        from .operations import NotebookOperations
        NotebookOperations(self).reorganize_category(key, name=name)

    def remove_category(self, key):
        from .operations import NotebookOperations
        NotebookOperations(self).reorganize_category(key, remove=True)

    def classify(self, path, category):
        if category and category not in self.categories:
            raise ValueError('分类不存在。')
        path = canonical_path(path)
        from .operations import NotebookOperations, is_managed
        if is_managed(path) and Path(path).is_file():
            return NotebookOperations(self).move_category(path, category)
        entry = self.data['notes'].setdefault(identity(path), {'path': path})
        entry['category'] = category
        self.commit()

    def entries(self):
        entries = {key: dict(value) for key, value in self.data['notes'].items()}
        recent = read_recent_files(self.settings)
        for path in recent:
            entries.setdefault(identity(path), {'path': path, 'category': '', 'opened': 0})
        rank = {identity(path): i for i, path in enumerate(recent)}
        return sorted((e for e in entries.values() if Path(e['path']).is_file()), key=lambda e: (
            rank.get(identity(e['path']), len(rank)), -e.get('opened', 0), e['path']))


def library_directory():
    override = os.environ.get('NE_LIBRARY_DIR')
    if override:
        return Path(override)
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.local' / 'share')
    return base / 'NotabilityEditor' / 'library'


def validate_category_name(name):
    name = name.strip()
    if (not name or len(name) > 64 or name == '未分类' or name.endswith(('.', ' '))
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name, re.I)):
        raise ValueError('分类名称需要 1～64 个有效文件夹字符，“未分类”为系统默认分类。')
    return name


def category_directory(name='未分类'):
    if name != '未分类':
        validate_category_name(name)
    root = library_directory().resolve()
    directory = root / name
    if not directory.resolve().is_relative_to(root):
        raise ValueError('分类目录必须位于本机笔记库内。')
    return directory


class ImportCancelled(Exception):
    pass


def copy_note(source, directory, progress=lambda value: None, cancelled=lambda: False):
    """Commit into a unique directory; partial files never become library entries."""
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() not in ('.ntb', '.note') or not source.is_file():
        raise ValueError('导入笔记仅支持 NTB 和 NOTE 文件。')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='note-', dir=directory))
    target = folder / source.name
    partial = folder / '.importing'
    try:
        with source.open('rb') as incoming, partial.open('xb') as outgoing:
            before = os.fstat(incoming.fileno())
            total = 0
            while True:
                if cancelled():
                    raise ImportCancelled()
                block = incoming.read(1024 * 1024)
                if not block:
                    break
                outgoing.write(block)
                total += len(block)
                progress(min(99, round(total * 100 / max(1, before.st_size))))
            after = os.fstat(incoming.fileno())
            if total != before.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise OSError('源文件在导入期间发生变化，请稍后重试。')
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if cancelled():
            raise ImportCancelled()
        os.replace(partial, target)
        progress(100)
        return str(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        folder.rmdir()
        raise


class ImportWorker(QThread):
    progress = pyqtSignal(int)
    ready = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source
        self.stop = threading.Event()
        self.result = None

    def run(self):
        try:
            self.result = copy_note(self.source, category_directory(), self.progress.emit, self.stop.is_set)
            self.ready.emit(self.result)
        except ImportCancelled:
            pass
        except Exception as exc:
            self.failed.emit(str(exc))
