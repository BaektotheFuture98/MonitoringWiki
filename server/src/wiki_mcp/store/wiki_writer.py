"""검증된 컴파일 계획과 인프라 페이지를 위키에 쓴다.

쓰기 락 아래에서 새 텍스트를 모두 계산한 뒤 스냅샷을 만들고, 패턴 페이지 → 색인 → 로그 순으로 원자적으로 쓴다.
계산 중 오류가 나면 스냅샷도 쓰기도 하지 않는다.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Sequence

from wiki_mcp.service.plan import CompilePlan, PlanError
from wiki_mcp.store.wiki_pages import (
    add_related_link,
    append_log,
    confidence_for,
    index_pattern_ids,
    merge_pattern_update,
    render_new_pattern,
    update_index_infra_line,
    upsert_index_row,
)
from wiki_mcp.store.wiki_reader import INDEX_PATH, INFRA_PATH, LOG_PATH, pattern_path
from wiki_mcp.store.wiki_store import WikiStore

INFRA_SNAPSHOT_LABEL = "infra"


@dataclass(frozen=True)
class ApplyResult:
    created: tuple[str, ...]
    updated: tuple[str, ...]
    snapshot: str


class WikiWriter:
    def __init__(self, store: WikiStore, snapshot_dir: Path, keep: int, now: Callable[[], datetime]) -> None:
        self.store = store
        self.snapshot_dir = snapshot_dir
        self.keep = keep
        self._now = now

    def apply_plan(self, plan: CompilePlan, *, raw_path: str, job_id: str) -> ApplyResult:
        with self.store.write_lock():
            now = self._now()
            index = self.store.read(INDEX_PATH)
            _check_actions(plan, index_pattern_ids(index))
            pages: dict[str, str] = {}
            for pattern in plan.patterns:
                path = pattern_path(pattern.id)
                if pattern.action == "create":
                    pages[path] = render_new_pattern(pattern, raw_path)
                    index = upsert_index_row(
                        index, pattern.id,
                        confidence=confidence_for(len(pattern.resources), 1), last_seen=pattern.last_seen,
                        resources=pattern.resources, summary=pattern.summary, signature=pattern.signature,
                    )
                else:
                    merged = merge_pattern_update(self.store.read(path), pattern, raw_path, now.date())
                    pages[path] = merged.text
                    index = upsert_index_row(
                        index, pattern.id, confidence=merged.confidence, last_seen=merged.last_seen,
                        resources=merged.resources if merged.resources_changed else None,
                    )
            # 관련 패턴은 양쪽 페이지에 링크한다. 상대 페이지에는 링크만 더하고 발생 횟수는 바꾸지 않는다.
            for pattern in plan.patterns:
                for ref in pattern.related:
                    target = pattern_path(ref.id)
                    current = pages[target] if target in pages else self.store.read(target)
                    pages[target] = add_related_link(current, pattern.id, ref.note)
            created = tuple(p.id for p in plan.patterns if p.action == "create")
            updated = tuple(p.id for p in plan.patterns if p.action == "update")
            log = append_log(
                self.store.read(LOG_PATH), when=now, kind="ingest", target=raw_path,
                lines=_ingest_lines(job_id, created, updated, len(plan.infra_candidates)),
            )
            snapshot = self._snapshot(now, job_id)
            for path, text in pages.items():
                self.store.write_atomic(path, text)
            self.store.write_atomic(INDEX_PATH, index)
            self.store.write_atomic(LOG_PATH, log)
        return ApplyResult(created, updated, snapshot)

    def write_infra(self, text: str, *, summary: str, as_of: date, source: str) -> str:
        with self.store.write_lock():
            now = self._now()
            index = update_index_infra_line(self.store.read(INDEX_PATH), summary, as_of)
            log = append_log(
                self.store.read(LOG_PATH), when=now, kind="infra", target="클러스터 구성 갱신",
                lines=[f"{source} 입력으로 `{INFRA_PATH}`를 덮어썼습니다(기준일 {as_of.isoformat()})."],
            )
            snapshot = self._snapshot(now, INFRA_SNAPSHOT_LABEL)
            self.store.write_atomic(INFRA_PATH, text)
            self.store.write_atomic(INDEX_PATH, index)
            self.store.write_atomic(LOG_PATH, log)
        return snapshot

    def _snapshot(self, now: datetime, label: str) -> str:
        base = f"{now:%Y%m%d-%H%M%S}-{label}"
        name, attempt = base, 2
        while (self.snapshot_dir / name).exists():
            name, attempt = f"{base}-{attempt}", attempt + 1
        self.store.snapshot(self.snapshot_dir / name)
        self._prune()
        return name

    def _prune(self) -> None:
        # 이름이 시각으로 시작하므로 이름순이 생성순이다.
        snapshots = sorted(path for path in self.snapshot_dir.iterdir() if path.is_dir())
        for old in snapshots[:-self.keep]:
            shutil.rmtree(old)


def _check_actions(plan: CompilePlan, existing_ids: set[str]) -> None:
    """계획을 만든 뒤 색인이 바뀌었을 수 있으므로 쓰기 직전에 다시 확인한다."""
    for pattern in plan.patterns:
        if pattern.action == "create" and pattern.id in existing_ids:
            raise PlanError(f"이미 있는 패턴입니다: {pattern.id}")
        if pattern.action == "update" and pattern.id not in existing_ids:
            raise PlanError(f"색인에 없는 패턴입니다: {pattern.id}")


def _ingest_lines(job_id: str, created: Sequence[str], updated: Sequence[str], candidates: int) -> list[str]:
    lines = [f"자동 컴파일(작업 {job_id}). 생성: {', '.join(created) or '없음'} / 갱신: {', '.join(updated) or '없음'}"]
    if candidates:
        lines.append(f"인프라 갱신 후보 {candidates}건은 위키에 반영하지 않고 작업 결과로만 보고했습니다.")
    return lines
