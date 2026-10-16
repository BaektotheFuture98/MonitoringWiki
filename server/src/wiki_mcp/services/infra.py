"""인프라 구성 입력을 검증하고 wiki/infra/cluster.md 본문으로 만든다(사람이 준 현재 상태로 덮어쓰기)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterator

from wiki_mcp.core.masking import IPV4_RE

NODE_NAME_RE = re.compile(r"RC\d+-\d+", re.IGNORECASE)
_DATE = r"(?:\d{4}[-./]\d{1,2}(?:[-./]\d{1,2})?|\d{4}년\s*\d{1,2}월)"
DATE_RANGE_RE = re.compile(rf"{_DATE}\s*(?:~|〜|–|—|부터|-(?=\s*{_DATE}))")
PAGE_NOTE = (
    "> 기준일 {as_of}의 현재 상태입니다. 구성이 바뀌면 덮어쓰고 `as_of`를 갱신합니다. 노드명과 IP는 적지 않습니다. "
    "랙은 티어가 위치한 곳을 나타내는 정보로만 적습니다. 매일 바뀌는 값(티어별 데이터 보유 기간 등)은 적지 않습니다."
)


class InfraError(ValueError):
    """인프라 입력이 위키 규칙(노드명·IP·매일 바뀌는 값 금지, 노드 수 합계)에 맞지 않음."""


@dataclass(frozen=True)
class Tier:
    name: str
    data_nodes: int
    racks: tuple[str, ...] = ()


@dataclass(frozen=True)
class InfraSpec:
    version: str
    master: int
    client: int
    data: int
    tiers: tuple[Tier, ...] = ()
    notes: tuple[str, ...] = ()
    unconfirmed: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return self.master + self.client + self.data


def _texts(spec: InfraSpec) -> Iterator[tuple[str, str]]:
    yield "version", spec.version
    for i, tier in enumerate(spec.tiers):
        yield f"tiers[{i}].name", tier.name
        for j, rack in enumerate(tier.racks):
            yield f"tiers[{i}].racks[{j}]", rack
    for i, note in enumerate(spec.notes):
        yield f"notes[{i}]", note
    for i, item in enumerate(spec.unconfirmed):
        yield f"unconfirmed[{i}]", item


def validate_infra(spec: InfraSpec) -> None:
    if not spec.version.strip():
        raise InfraError("version이 비어 있습니다.")
    counts = [spec.master, spec.client, spec.data, *(tier.data_nodes for tier in spec.tiers)]
    if min(counts) < 0:
        raise InfraError("노드 수는 0 이상이어야 합니다.")
    names = [tier.name.strip() for tier in spec.tiers]
    if any(not name for name in names):
        raise InfraError("티어 이름이 비어 있습니다.")
    if len(set(names)) != len(names):
        raise InfraError("티어 이름이 중복됩니다.")
    if spec.tiers:
        total = sum(tier.data_nodes for tier in spec.tiers)
        if total != spec.data:
            raise InfraError(f"데이터 노드 수({spec.data})와 티어별 데이터 노드 합계({total})가 다릅니다.")
    for label, text in _texts(spec):
        if "\n" in text or "\r" in text:
            raise InfraError(f"{label}는 한 줄이어야 합니다.")
        if "|" in text:
            raise InfraError(f"{label}에 표 구분자(|)를 쓸 수 없습니다.")
        if IPV4_RE.search(text):
            raise InfraError(f"{label}에 IP를 쓸 수 없습니다.")
        if NODE_NAME_RE.search(text):
            raise InfraError(f"{label}에 노드명을 쓸 수 없습니다(랙 이름만 허용).")
        if DATE_RANGE_RE.search(text):
            raise InfraError(f"{label}에 날짜 범위를 쓸 수 없습니다(매일 바뀌는 값 금지).")


def infra_summary(spec: InfraSpec) -> str:
    nodes = f"{spec.total}노드(마스터 {spec.master}, 클라이언트 {spec.client}, 데이터 {spec.data}"
    if spec.tiers:
        nodes += " = " + " / ".join(f"{tier.name} {tier.data_nodes}" for tier in spec.tiers)
    parts = [f"Elasticsearch {spec.version}", nodes + ")"]
    racks = ["·".join(tier.racks) for tier in spec.tiers if tier.racks]
    if racks:
        parts.append("티어별 랙 " + " / ".join(racks))
    return ", ".join(parts)


def render_infra(spec: InfraSpec, *, as_of: date, source: str) -> str:
    day = as_of.isoformat()
    lines = [
        "---", "id: infra-cluster", f"summary: {infra_summary(spec)}", f"as_of: {day}", f"source: {source}", "---",
        "# 클러스터 구성", "",
        PAGE_NOTE.format(as_of=day), "",
        "## 버전", f"- Elasticsearch {spec.version}", "",
        f"## 노드 구성 (총 {spec.total}대)",
        "| 역할 | 수 |", "|---|---|",
        f"| 마스터 | {spec.master} |", f"| 클라이언트(코디네이팅) | {spec.client} |", f"| 데이터 | {spec.data} |", "",
    ]
    if spec.tiers:
        lines += ["## 데이터 티어", "| 티어 | 데이터 노드 수 | 랙 |", "|---|---|---|"]
        lines += [f"| {tier.name} | {tier.data_nodes} | {', '.join(tier.racks)} |" for tier in spec.tiers]
        lines += [f"| 합계 | {spec.data} | |", ""]
    if spec.notes:
        lines += ["## 참고", *(f"- {note}" for note in spec.notes), ""]
    unconfirmed = [f"- {item}" for item in spec.unconfirmed] or ["- 없음"]
    lines += ["## 미확인 항목 (설명 받으면 채움)", *unconfirmed, ""]
    return "\n".join(lines)
