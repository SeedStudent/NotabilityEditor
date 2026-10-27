"""Read-only diagnostic for denied Windows NTB overwrite operations.

Does not remove, rename, rewrite or unlock the original note. It only probes
its metadata and tests creating and renaming a separate throwaway file nearby.
"""
import os
import stat
import sys
import tempfile
import ctypes
from ctypes import wintypes
from pathlib import Path


def test_delete_rights(path):
    if os.name != 'nt':
        return 'This probe requires Windows'
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = k32.CreateFileW
    fn.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                   wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                   wintypes.HANDLE]
    fn.restype = wintypes.HANDLE
    fn_close = k32.CloseHandle
    fn_close.argtypes = [wintypes.HANDLE]
    fn_close.restype = wintypes.BOOL
    # Ask DELETE access while permitting sharing in every direction.
    h = fn(str(path), 0x10000, 0x7, None, 3, 0x80, None)
    if h == ctypes.c_void_p(-1).value:
        code=ctypes.get_last_error()
        return f'failed: WinError {code} ({ctypes.FormatError(code).strip()})'
    fn_close(h)
    return 'successful; basic delete access can be granted'


def run(name):
    p = Path(name).expanduser().resolve()
    print('NTB OVERWRITE DIAGNOSTIC (original file is never modified)')
    print('path:', p)
    print('is_file:', p.is_file())
    if not p.is_file():
        return 1
    st = p.stat()
    print('size:', st.st_size)
    print('read_only:', not bool(st.st_mode & stat.S_IWRITE))
    from platform_integration.nv_winlockdiag import diagnostic_lines
    for line in diagnostic_lines(p):
        print(line)
    fd, t = tempfile.mkstemp(prefix='.nv-write-check-',suffix='.tmp',dir=p.parent)
    os.close(fd)
    candidate = Path(t)
    renamed = candidate.with_name(candidate.name + '.renamed')
    try:
        os.replace(candidate, renamed)
        print('same-folder new-file rename: SUCCESS')
    except OSError as exc:
        print('same-folder new-file rename: FAILED', repr(exc))
    finally:
        for path in (candidate, renamed):
            if path.exists():
                path.unlink()
    print('When reporting an error, include the Save dialog and this output.')
    return 0

if __name__ == '__main__':
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print('Usage: python tools.diagnose_overwrite.py "C:\\folder\\note.ntb"')
        raise SystemExit(2)
    try:
        raise SystemExit(run(sys.argv[1]))
    except OSError as exc:
        print('Probe error:', repr(exc))
        raise SystemExit(1)
