"""위키 파일 저장소. 조회·컴파일 코드는 WikiStore 인터페이스만 알고, 구현(지금은 파일, 이후 git)은 조립 단계에서 고른다."""
from __future__ import annotations

import os
import shutil
import threading
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, ContextManager, Protocol

WRITABLE_PREFIX = "wiki/"


class WikiPathError(ValueError):
    """저장소 밖을 가리키거나 쓰기가 허용되지 않은 경로."""


class WikiStore(Protocol):
    def read(self, path: str) -> str: ...

    def exists(self, path: str) -> bool: ...

    def list(self, directory: str) -> list[str]: ...

    def write_atomic(self, path: str, text: str) -> None: ...

    def snapshot(self, dest: Path) -> None: ...

    def write_lock(self) -> ContextManager[Any]: ...


def _parts(path: str) -> tuple[str, ...]:
    pure = PurePosixPath(path)
    if not path or "\\" in path or pure.is_absolute() or ".." in pure.parts:
        raise WikiPathError(f"허용되지 않은 경로입니다: {path!r}")
    return pure.parts


class FileWikiStore:
    """작업 트리의 파일을 직접 읽고 쓴다(PoC). 쓰기는 wiki/ 아래만 허용한다."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    def _resolve(self, path: str) -> Path:
        return self.root.joinpath(*_parts(path))

    def read(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    def exists(self, path: str) -> bool:
        return self._resolve(path).is_file()

    def list(self, directory: str) -> list[str]:
        folder = self._resolve(directory)
        if not folder.is_dir():
            return []
        return [
            f"{directory}/{child.name}"
            for child in sorted(folder.iterdir())
            if child.is_file() and not child.name.startswith(".")
        ]

    def write_atomic(self, path: str, text: str) -> None:
        target = self._resolve(path)
        if not path.startswith(WRITABLE_PREFIX):
            raise WikiPathError(f"wiki/ 아래에만 쓸 수 있습니다: {path!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        # 같은 폴더의 임시 파일에 쓴 뒤 교체해야 읽는 쪽이 반쯤 쓴 파일을 보지 않는다.
        tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)

    def snapshot(self, dest: Path) -> None:
        shutil.copytree(self.root / "wiki", dest)

    def write_lock(self) -> ContextManager[Any]:
        return self._lock
