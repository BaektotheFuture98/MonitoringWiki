"""LLM에 보내기 전 보고서의 개인정보를 자리표시자로 바꾼다. raw 원문은 바꾸지 않는다."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
# 쿼리 로그의 키-값. 이메일 규칙보다 먼저 적용해야 user=<이메일>이 <USER> 하나로 바뀐다.
KEY_VALUE_RULES = (
    (re.compile(r"\b(user=)[^\s,]+"), r"\1<USER>"),
    (re.compile(r"\b(company=)[^\s,]+"), r"\1<COMPANY>"),
    (re.compile(r"\b(keyword=)\[[^\]]*\]"), r"\1[<KEYWORD>]"),
)


def load_names(path: Path | None) -> list[str]:
    if path is None:
        return []
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        name = line.strip()
        if name and not name.startswith("#"):
            names.append(name)
    return names


class Masker:
    def __init__(self, names: Iterable[str] = ()) -> None:
        # 긴 이름부터 맞춰야 "Acme Korea"가 "Acme"로 먼저 잘리지 않는다.
        unique = sorted({name for name in names if name}, key=len, reverse=True)
        self._names_re = (
            re.compile("|".join(re.escape(name) for name in unique), re.IGNORECASE) if unique else None
        )

    def mask(self, text: str) -> str:
        for pattern, replacement in KEY_VALUE_RULES:
            text = pattern.sub(replacement, text)
        text = EMAIL_RE.sub("<USER>", text)
        text = IPV4_RE.sub("<IP>", text)
        if self._names_re is not None:
            text = self._names_re.sub("<COMPANY>", text)
        return text

    def find_leaks(self, text: str) -> list[str]:
        leaks = []
        if EMAIL_RE.search(text):
            leaks.append("이메일")
        if IPV4_RE.search(text):
            leaks.append("IPv4")
        if self._names_re is not None and self._names_re.search(text):
            leaks.append("회사·고객명")
        return leaks
