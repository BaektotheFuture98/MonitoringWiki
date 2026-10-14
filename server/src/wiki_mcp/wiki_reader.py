"""git ref에 커밋된 위키 파일을 읽는다. 작업 트리는 읽지 않는다."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Sequence

PATTERN_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
SECTION_NAMES = ("원인", "증상", "해결방법", "관련 패턴")


class WikiReadError(Exception):
    """git에서 위키 파일을 읽지 못함."""


class PatternNotFound(WikiReadError):
    """요청한 패턴 페이지가 ref에 없음."""


class InvalidRequest(ValueError):
    """도구 입력값이 규칙에 맞지 않음."""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True)


def check_ref(root: Path, ref: str) -> None:
    result = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if result.returncode != 0:
        raise WikiReadError(f"git ref를 읽을 수 없습니다: {ref} ({root})")


def git_show(root: Path, ref: str, path: str) -> str:
    result = _git(root, "show", f"{ref}:{path}")
    if result.returncode != 0:
        raise FileNotFoundError(f"{ref}:{path}")
    return result.stdout.decode("utf-8")


def list_files(root: Path, ref: str, directory: str) -> list[str]:
    result = _git(root, "ls-tree", "--name-only", f"{ref}:{directory}")
    if result.returncode != 0:
        return []
    names = result.stdout.decode("utf-8").splitlines()
    return [f"{directory}/{name}" for name in names if name]


def _read(root: Path, ref: str, path: str) -> str:
    try:
        return git_show(root, ref, path)
    except FileNotFoundError as exc:
        raise WikiReadError(f"{path}를 {ref}에서 찾을 수 없습니다.") from exc


def read_index(root: Path, ref: str) -> str:
    return _read(root, ref, "wiki/index.md")


def read_infra(root: Path, ref: str) -> str:
    return _read(root, ref, "wiki/infra/cluster.md")


def split_frontmatter(text: str) -> tuple[list[str], list[str]]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return [], lines
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], lines[i + 1:]
    return [], lines


def drop_field(frontmatter: list[str], field: str) -> list[str]:
    kept: list[str] = []
    skipping = False
    for line in frontmatter:
        if skipping and line.startswith((" ", "\t", "-")):
            continue
        skipping = False
        if line.startswith(f"{field}:"):
            skipping = True
            continue
        kept.append(line)
    return kept


def _split_sections(body: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    head: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body:
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = [line]
        elif current is None:
            head.append(line)
        else:
            sections[current].append(line)
    return head, sections


def read_pattern(root: Path, ref: str, pattern_id: str, sections: Sequence[str] | None = None) -> str:
    if not PATTERN_ID_RE.fullmatch(pattern_id):
        raise InvalidRequest(f"패턴 id 형식이 올바르지 않습니다: {pattern_id!r}")
    wanted = set(sections) if sections else set(SECTION_NAMES)
    unknown = sorted(wanted - set(SECTION_NAMES))
    if unknown:
        raise InvalidRequest(f"알 수 없는 섹션: {unknown}. 가능한 값: {list(SECTION_NAMES)}")
    try:
        text = git_show(root, ref, f"wiki/patterns/{pattern_id}.md")
    except FileNotFoundError as exc:
        raise PatternNotFound(f"패턴 {pattern_id}가 없습니다. get_index로 id를 확인하세요.") from exc

    frontmatter, body = split_frontmatter(text)
    head, found = _split_sections(body)
    parts = ["---", *drop_field(frontmatter, "sources"), "---", *head]
    for name in SECTION_NAMES:
        if name in wanted and name in found:
            parts.extend(found[name])
    return "\n".join(parts).rstrip("\n") + "\n"
