"""Private originals: confined handles, exclusive publication, verified delivery."""

from contextlib import contextmanager, ExitStack
from pathlib import Path
from uuid import uuid4
import hashlib
import io
import os
import stat
import re

from app.schemas.report_pdf_archive import validate_object_key, PdfCandidate
from app.services.report_pdf_errors import PdfError

MAX_BYTES = 64 * 1024 * 1024


class _HeldReader(io.BufferedReader):
    def __init__(self, raw, stack):
        super().__init__(raw)
        self._stack = stack

    def close(self):
        try:
            super().close()
        finally:
            self._stack.close()


def _windows_handle(path, directory=False):
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    # No FILE_SHARE_DELETE: parent directories cannot be swapped while held.
    handle = kernel.CreateFileW(
        str(path),
        0x80 if directory else 0x80000000,
        3 if directory else 1,
        None,
        3,
        0x00200000 | (0x02000000 if directory else 0),
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    returned = False
    try:
        attrs = (wintypes.DWORD * 2)()
        if not kernel.GetFileInformationByHandleEx(
            handle, 9, attrs, ctypes.sizeof(attrs)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if attrs[0] & 0x400:
            raise PdfError("pdf_storage_unavailable")
        buf = ctypes.create_unicode_buffer(32768)
        length = kernel.GetFinalPathNameByHandleW(handle, buf, len(buf), 0)
        if not length or length >= len(buf):
            raise PdfError("pdf_storage_unavailable")
        actual = buf.value.removeprefix("\\\\?\\")
        if os.path.normcase(actual) != os.path.normcase(os.path.abspath(path)):
            raise PdfError("pdf_storage_unavailable")
        if directory:
            returned = True
            return handle, kernel
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handle = None
        return fd
    finally:
        if handle is not None and not returned:
            kernel.CloseHandle(handle)


class ArchiveStorage:
    def __init__(self, root, *, create=True):
        root = Path(root)
        if not root.is_absolute():
            raise PdfError("pdf_storage_unavailable")
        if create:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not root.is_dir():
            raise PdfError("pdf_storage_unavailable")
        if root.is_symlink() or getattr(root.lstat(), "st_file_attributes", 0) & 0x400:
            raise PdfError("pdf_storage_unavailable")
        self.root = root.resolve(strict=True)
        info = self.root.stat()
        self._root_identity = (info.st_dev, info.st_ino)

    def candidate_path(self, key):
        validate_object_key(key)
        path = self.root.joinpath(*key.split("/"))
        for parent in [self.root, *list(path.relative_to(self.root).parents)[:-1]]:
            candidate = parent if parent.is_absolute() else self.root / parent
            if candidate.exists() and (
                candidate.is_symlink()
                or getattr(candidate.lstat(), "st_file_attributes", 0) & 0x400
            ):
                raise PdfError("pdf_storage_unavailable")
        if not path.resolve().is_relative_to(self.root):
            raise PdfError("pdf_storage_unavailable")
        return path

    @contextmanager
    def _parent(self, key, create=False):
        path = self.candidate_path(key)
        stack = ExitStack()
        try:
            if os.name == "nt":
                current = self.root
                for part in [None, *key.split("/")[:-1]]:
                    if part is not None:
                        current = current / part
                        if create:
                            current.mkdir(exist_ok=True)
                    handle, kernel = _windows_handle(current, True)
                    stack.callback(kernel.CloseHandle, handle)
                yield path, None, stack
            else:
                fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                stack.callback(os.close, fd)
                info = os.fstat(fd)
                if (info.st_dev, info.st_ino) != self._root_identity:
                    raise PdfError("pdf_storage_unavailable")
                for part in key.split("/")[:-1]:
                    if create:
                        try:
                            os.mkdir(part, 0o700, dir_fd=fd)
                        except FileExistsError:
                            pass
                    fd = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                    )
                    stack.callback(os.close, fd)
                yield path, fd, stack
        finally:
            stack.close()

    def open_verified(self, key, sha256, size_bytes):
        if type(size_bytes) is not int or not 1 <= size_bytes <= MAX_BYTES:
            raise PdfError("pdf_original_corrupt")
        try:
            with self._parent(key) as (path, fd, stack):
                file_fd = (
                    _windows_handle(path)
                    if os.name == "nt"
                    else os.open(
                        "document.pdf",
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                        dir_fd=fd,
                    )
                )
                raw = io.FileIO(file_fd, "rb", closefd=True)
                try:
                    if (
                        not stat.S_ISREG(os.fstat(file_fd).st_mode)
                        or os.fstat(file_fd).st_size != size_bytes
                    ):
                        raise PdfError("pdf_original_corrupt")
                    digest = hashlib.sha256()
                    size = 0
                    for chunk in iter(lambda: raw.read(1024 * 1024), b""):
                        size += len(chunk)
                        if size > size_bytes:
                            raise PdfError("pdf_original_corrupt")
                        digest.update(chunk)
                    if size != size_bytes or digest.hexdigest() != sha256:
                        raise PdfError("pdf_original_corrupt")
                    raw.seek(0)
                    return _HeldReader(raw, stack.pop_all())
                except BaseException:
                    raw.close()
                    raise
        except FileNotFoundError:
            raise PdfError("pdf_original_missing") from None
        except OSError:
            raise PdfError("pdf_storage_unavailable") from None

    def write_candidate(self, key, pdf_bytes, *, _restore=False):
        if not isinstance(pdf_bytes, bytes) or not 1 <= len(pdf_bytes) <= MAX_BYTES:
            raise PdfError("pdf_render_failed")
        import fitz

        try:
            with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
                if document.needs_pass or not 1 <= document.page_count <= 200:
                    raise ValueError()
                pages = document.page_count
        except Exception:
            raise PdfError("pdf_render_failed") from None
        temp = f"{uuid4()}.part"
        try:
            with self._parent(key, True) as (path, fd, stack):
                target = path.parent / temp if os.name == "nt" else temp
                raw_fd = os.open(
                    target,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    **({} if os.name == "nt" else {"dir_fd": fd}),
                )
                try:
                    with os.fdopen(raw_fd, "wb") as stream:
                        stream.write(pdf_bytes)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if os.name == "nt":
                        import ctypes
                        from ctypes import wintypes

                        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                        kernel.MoveFileExW.argtypes = [
                            wintypes.LPCWSTR,
                            wintypes.LPCWSTR,
                            wintypes.DWORD,
                        ]
                        if path.exists() and (
                            path.is_symlink()
                            or getattr(path.lstat(), "st_file_attributes", 0) & 0x400
                        ):
                            raise PdfError("pdf_storage_unavailable")
                        if not kernel.MoveFileExW(
                            str(target), str(path), 8 | (1 if _restore else 0)
                        ):
                            raise ctypes.WinError(ctypes.get_last_error())
                    else:
                        if _restore:
                            os.replace(
                                temp, "document.pdf", src_dir_fd=fd, dst_dir_fd=fd
                            )
                        else:
                            os.link(
                                temp,
                                "document.pdf",
                                src_dir_fd=fd,
                                dst_dir_fd=fd,
                                follow_symlinks=False,
                            )
                            os.unlink(temp, dir_fd=fd)
                        os.fsync(fd)
                finally:
                    try:
                        os.unlink(target, **({} if os.name == "nt" else {"dir_fd": fd}))
                    except FileNotFoundError:
                        pass
            return PdfCandidate(
                object_key=key,
                pdf_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
                size_bytes=len(pdf_bytes),
                page_count=pages,
            )
        except FileExistsError:
            raise PdfError("pdf_original_corrupt") from None
        except OSError as error:
            raise PdfError(
                "pdf_storage_full" if error.errno == 28 else "pdf_storage_unavailable"
            ) from None

    def delete_attempt(self, key):
        try:
            with self._parent(key) as (path, fd, stack):
                names = os.listdir(path.parent) if os.name == "nt" else os.listdir(fd)
                for name in names:
                    if name != "document.pdf" and not re.fullmatch(
                        r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\.part", name
                    ):
                        raise PdfError("pdf_storage_unavailable")
                    entry = path.parent / name
                    info = (
                        entry.lstat()
                        if os.name == "nt"
                        else os.stat(name, dir_fd=fd, follow_symlinks=False)
                    )
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or getattr(info, "st_file_attributes", 0) & 0x400
                    ):
                        raise PdfError("pdf_storage_unavailable")
                    os.unlink(entry) if os.name == "nt" else os.unlink(name, dir_fd=fd)
                if os.name != "nt":
                    os.fsync(fd)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            raise PdfError("pdf_storage_unavailable") from None
