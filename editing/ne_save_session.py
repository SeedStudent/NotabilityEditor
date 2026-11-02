"""Immutable save inputs and local crash recovery, independent of the canvas.

The session baseline retains original assets for undo after structural saves.
Every NTB is rebuilt from that baseline plus cumulative edits, never from an
already rewritten archive. Recovery files are private application data.
"""
import copy
from document_core import SnapshotStore
from document_core.snapshot import FrozenDict
from collections import OrderedDict
from dataclasses import dataclass, fields
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import uuid
from zipfile import ZipFile

from PyQt6.QtCore import QLockFile, QThread, pyqtSignal
from editing.ne_edits import Stroke
from formats.ne_loader import LoadCancelled


def recovery_root():
    override = os.environ.get('NE_RECOVERY_DIR')
    if override:
        return Path(override).resolve()
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share'))) / 'NotabilityEditor' / 'recovery'


def file_stamp(path):
    try:
        stat = Path(path).stat()
        return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except FileNotFoundError:
        return None


@dataclass(frozen=True)
class SaveSnapshot:
    revision: int
    token: object
    image_digest: str
    native_digest: str
    data: dict


def capture(canvas, revision, thumbnail=None):
    """Called on the GUI thread after a gesture, with no live model references."""
    edits = canvas.edits
    core = edits.core if hasattr(edits, 'core') else edits
    store = getattr(canvas, '_save_snapshot_store', None)
    if store is None:
        store = canvas._save_snapshot_store = SnapshotStore()
    keys = tuple(edits.order) if hasattr(edits, 'order') else tuple(range(canvas.page_count))
    native = canvas.official_image_edits
    image_digest = canvas.image_layers._digest()
    native_digest = native.save_digest()
    ink_revision = (core.token, core.cursor, keys, getattr(canvas, 'page_edit_kind', None))
    hidden, added, plan = store.get('ink', ink_revision, lambda: (
        *edits.native_changes(), edits.page_plan() if hasattr(edits, 'page_plan') else None))
    def images():
        pages = canvas.image_layers.serialize(keys)
        return pages, canvas.image_layers.referenced_assets(pages)
    payload = store.get('images', (keys, image_digest), images)
    changes, locks, deletions, layers = store.get('native', native_digest, lambda: (
        native.changes, native.lock_changes, native.deletion_changes, native.layer_changes))
    data = FrozenDict(hidden=hidden, added=added, thumbnail=thumbnail, page_plan=plan,
                     image_payload=payload, native_image_changes=changes,
                     native_image_lock_changes=locks, native_image_deletions=deletions,
                     native_image_layer_changes=layers)
    return SaveSnapshot(revision, edits.token, image_digest, native_digest, data)


def _atomic_bytes(path, blob):
    descriptor, name = tempfile.mkstemp(prefix='.ne-snapshot-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _encode(value, folder, cancelled):
    if cancelled():
        raise LoadCancelled()
    if isinstance(value, Stroke):
        return {'type': 'stroke', 'value': _encode({f.name: getattr(value, f.name) for f in fields(Stroke)}, folder, cancelled)}
    if isinstance(value, bytes):
        digest = hashlib.sha256(value).hexdigest()
        path = folder / digest
        if not path.exists():
            _atomic_bytes(path, value)
        return {'type': 'blob', 'value': digest}
    if isinstance(value, dict):
        return {'type': 'dict', 'value': [[_encode(k, folder, cancelled), _encode(v, folder, cancelled)] for k, v in value.items()]}
    if isinstance(value, (tuple, list, set, frozenset)):
        return {'type': 'tuple' if isinstance(value, tuple) else 'set' if isinstance(value, (set, frozenset)) else 'list',
                'value': [_encode(v, folder, cancelled) for v in value]}
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise TypeError('不支持的快照字段：' + type(value).__name__)


def _decode(value, folder):
    if not isinstance(value, dict):
        return value
    kind, data = value['type'], value['value']
    if kind == 'blob':
        if len(data) != 64 or any(c not in '0123456789abcdef' for c in data):
            raise ValueError('恢复素材路径无效')
        blob = (folder / data).read_bytes()
        if hashlib.sha256(blob).hexdigest() != data:
            raise ValueError('恢复素材校验失败')
        return blob
    if kind == 'dict':
        return {_decode(k, folder): _decode(v, folder) for k, v in data}
    if kind == 'stroke':
        return Stroke(**_decode(data, folder))
    constructors = {'tuple': tuple, 'list': list, 'set': set}
    return constructors[kind](_decode(v, folder) for v in data)


class SaveSession:
    def __init__(self, source, bundle):
        self.source = str(Path(source).resolve())
        self.bundle = bundle
        self.source_stamp = file_stamp(source)
        self.folder = recovery_root() / uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.lock = QLockFile(str(self.folder / 'owner.lock'))
        if not self.lock.tryLock(0):
            raise OSError('无法创建编辑会话')
        self.baseline = self.folder / 'baseline.ntb'
        self.mutex = threading.RLock()
        self.revision = -1
        self.saved_revision = -1
        self.validation_cache = OrderedDict()
        self.closed = False

    def ensure_baseline(self, cancelled=lambda: False):
        with self.mutex:
            if self.closed:
                raise LoadCancelled()
            if self.baseline.exists():
                return str(self.baseline)
            if file_stamp(self.source) != self.source_stamp:
                raise ValueError('原文件已被外部修改；当前编辑仍保留，请另存或重新打开。')
            temporary = self.folder / 'baseline.tmp'
            try:
                with open(self.source, 'rb') as original, temporary.open('wb') as output:
                    while True:
                        if cancelled():
                            raise LoadCancelled()
                        chunk = original.read(4 * 1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                with ZipFile(temporary) as archive:
                    if archive.read('noteBundle') != self.bundle:
                        raise ValueError('原文件与打开时的笔记基准不一致，已停止保存。')
                if file_stamp(self.source) != self.source_stamp:
                    raise ValueError('建立保存基准时原文件发生变化，已停止保存。')
                os.replace(temporary, self.baseline)
            finally:
                temporary.unlink(missing_ok=True)
            return str(self.baseline)

    def persist(self, snapshot, target, cancelled=lambda: False):
        with self.mutex:
            self.ensure_baseline(cancelled)
            if snapshot.revision < self.revision or snapshot.revision <= self.saved_revision:
                return
            blobs = self.folder / 'blobs'
            blobs.mkdir(exist_ok=True)
            payload = dict(version=1, source=self.source, target=str(target),
                           revision=snapshot.revision, updated=datetime.now(timezone.utc).isoformat(),
                           data=_encode(snapshot.data, blobs, cancelled))
            if cancelled():
                raise LoadCancelled()
            _atomic_bytes(self.folder / 'snapshot.json', json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'))
            self.revision = snapshot.revision

    def saved(self, revision):
        with self.mutex:
            self.saved_revision=max(self.saved_revision,revision)
            # A newer recovery snapshot can already contain edits made while
            # the save worker was writing. Never remove that newer snapshot.
            if self.revision <= revision:
                (self.folder / 'snapshot.json').unlink(missing_ok=True)

    def close(self):
        with self.mutex:
            self.validation_cache.clear()
            self.closed = True
            self.lock.unlock()
            remove_recovery(self.folder)


class SnapshotWorker(QThread):
    failed = pyqtSignal(str)
    baseline_ready = pyqtSignal(str)
    def __init__(self, session, snapshot, target, parent=None):
        super().__init__(parent)
        self.session, self.snapshot, self.target = session, snapshot, target
        self.stop = threading.Event()

    def run(self):
        try:
            self.baseline_ready.emit(self.session.ensure_baseline(self.stop.is_set))
            self.session.persist(self.snapshot, self.target, self.stop.is_set)
        except LoadCancelled:
            pass
        except Exception as exc:
            self.failed.emit(str(exc))


def remove_recovery(folder):
    folder = Path(folder).resolve()
    root = recovery_root().resolve()
    if folder.parent != root or len(folder.name) != 32 or any(c not in '0123456789abcdef' for c in folder.name):
        raise ValueError('恢复目录不在应用专属空间')
    shutil.rmtree(folder)


def pending_recoveries():
    result = []
    root = recovery_root()
    if not root.exists():
        return result
    for entry in root.glob('*/snapshot.json'):
        lock = QLockFile(str(entry.parent / 'owner.lock'))
        if not lock.tryLock(0):
            continue  # Another running editor owns this session.
        try:
            payload = json.loads(entry.read_text(encoding='utf-8'))
            if payload.get('version') == 1 and (entry.parent / 'baseline.ntb').is_file():
                result.append((entry.parent, payload))
        except (OSError, ValueError):
            continue
        finally:
            lock.unlock()
    return sorted(result, key=lambda pair: pair[1].get('updated', ''), reverse=True)


def read_recovery(folder):
    folder = Path(folder)
    payload = json.loads((folder / 'snapshot.json').read_text(encoding='utf-8'))
    if payload.get('version') != 1:
        raise ValueError('不支持的恢复快照版本')
    return _decode(payload['data'], folder / 'blobs')
