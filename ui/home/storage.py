"""Version-independent user data, with atomic writes and a last-good backup."""
import json
import os
from pathlib import Path
import tempfile
import uuid


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

    def save(self, data):
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
