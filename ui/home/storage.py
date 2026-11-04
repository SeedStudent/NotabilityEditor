"""Version-independent user data, with atomic writes and a last-good backup."""
import json
import os
from pathlib import Path
import tempfile
import uuid
import threading
from contextlib import contextmanager
from copy import deepcopy

from PyQt6.QtCore import QLockFile


class LibraryConflictError(OSError):
    """A stale window must not overwrite another editor's changes."""


_MISSING = object()


def merge_library(base, local, remote):
    """Three-way merge: unchanged fields follow disk; conflicting edits fail."""
    def merge(old, ours, theirs, path=()):
        if ours == old:
            return deepcopy(theirs) if theirs is not _MISSING else _MISSING
        if theirs == old or ours == theirs:
            return deepcopy(ours) if ours is not _MISSING else _MISSING
        if all(isinstance(v, dict) for v in (old, ours, theirs)):
            result = {}
            for key in old.keys() | ours.keys() | theirs.keys():
                value = merge(old.get(key, _MISSING), ours.get(key, _MISSING),
                              theirs.get(key, _MISSING), path + (key,))
                if value is not _MISSING:
                    result[key] = value
            return result
        if len(path) == 3 and path[0] == 'notes' and path[2] == 'opened':
            if all(isinstance(v, (int, float)) for v in (ours, theirs)):
                return max(ours, theirs)
        if path == ('movement_history',) and all(isinstance(v, list) for v in (ours, theirs)):
            previous = old if isinstance(old, list) else []
            added = [v for v in ours if v not in previous and v not in theirs]
            return sorted(deepcopy(theirs + added), key=lambda v: v.get('time', 0))[-1000:]
        raise LibraryConflictError('分类或笔记已被另一窗口修改，本次操作未保存。请刷新后重试。')

    result = merge(base, local, remote)
    names = list(result['categories'].values())
    if len({name.casefold() for name in names}) != len(names):
        raise LibraryConflictError('另一窗口已创建同名分类，请刷新后使用其他名称。')
    if any(entry.get('category') and entry['category'] not in result['categories']
           for entry in result['notes'].values()):
        raise LibraryConflictError('分类已被另一窗口删除或修改，本次操作未保存。请刷新后重试。')
    return validate_library(result)


def library_index_path():
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.local' / 'share')
    return base / 'NotabilityEditor' / 'home-library.json'


def validate_library(data):
    if (not isinstance(data, dict)
            or not isinstance(data.get('categories', {}), dict)
            or not isinstance(data.get('notes', {}), dict)):
        raise ValueError('Invalid library index')
    if any(not isinstance(k, str) or not isinstance(v, str)
           for k, v in data.get('categories', {}).items()):
        raise ValueError('Invalid categories')
    for key, entry in data.get('notes', {}).items():
        if (not isinstance(key, str) or not isinstance(entry, dict)
                or not isinstance(entry.get('path'), str)
                or not isinstance(entry.get('category', ''), str)
                or not isinstance(entry.get('opened', 0), (int, float))):
            raise ValueError('Invalid notebook reference')
    data.setdefault('categories', {})
    data.setdefault('notes', {})
    return data


def write_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(prefix=path.name + '.', suffix='.tmp',
                                         dir=path.parent, delete=False) as output:
            name = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


class LibraryStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else library_index_path()
        self.backup = self.path.with_suffix('.json.bak')
        self.notice = ''
        self.recovered = False
        self._mutex = threading.RLock()
        self._lock_depth = 0
        self._file_lock = None

    @contextmanager
    def locked(self):
        # The mutex also makes reentrancy safe when worker threads share a store.
        with self._mutex:
            if not self._lock_depth:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                lock = QLockFile(str(self.path) + '.lock')
                if not lock.tryLock(3000):
                    raise OSError('另一窗口正在更新分类与笔记索引，请稍后重试。')
                self._file_lock = lock
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
                if not self._lock_depth:
                    self._file_lock.unlock()
                    self._file_lock = None

    @staticmethod
    def decode(raw):
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError('Invalid user data')
        version = document.get('schema_version')
        if isinstance(version, int) and version > 1:
            raise OSError('分类数据由更新版本创建，请使用较新版本打开。')
        if version != 1:
            raise ValueError('Invalid user data version')
        return validate_library(document.get('library'))

    def load(self):
        with self.locked():
            return self._load()

    def _load(self):
        broken = []
        for path in (self.path, self.backup):
            try:
                raw = path.read_bytes()
            except FileNotFoundError:
                continue
            try:
                data = self.decode(raw)
            except (ValueError, TypeError, UnicodeError):
                preserved = path.with_name(path.name + '.corrupt-' + uuid.uuid4().hex)
                write_atomic(preserved, raw)
                broken.append(path)
                continue
            if path == self.backup:
                self.recovered = True
                self.notice = '分类数据已从备份恢复；原始文件已保留。' if broken else '分类数据已从备份恢复。'
            return data
        if broken:
            self.notice = '分类数据无法读取，已保留原文件，并尝试恢复旧版设置。'
        return None

    def save(self, data, *, base=None):
        with self.locked():
            current = self._load()
            if base is not None:
                data = merge_library(base, data, current if current is not None else base)
            self._save(data)
            return deepcopy(data)

    def _save(self, data):
        validate_library(data)
        raw = json.dumps(dict(schema_version=1, library=data), ensure_ascii=False,
                         indent=2, allow_nan=False).encode('utf-8')
        try:
            previous = self.path.read_bytes()
        except FileNotFoundError:
            previous = None
        if previous is not None:
            try:
                self.decode(previous)
            except (ValueError, TypeError, UnicodeError):
                previous = None
        if previous is not None:
            write_atomic(self.backup, previous)
        write_atomic(self.path, raw)
