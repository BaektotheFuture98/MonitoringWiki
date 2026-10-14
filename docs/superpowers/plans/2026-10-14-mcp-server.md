# MonitoringWiki MCP 서버 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 외부 에이전트가 MCP로 장애 패턴 위키를 조회하고, 승인 주체가 승인된 보고서를 raw에 제출할 수 있는 Python MCP 서버를 만든다.

**Architecture:** SDK와 무관한 순수 모듈(설정, git 기반 위키 읽기, raw 저장, 인증, 속도 제한, 가이드 추출, 접근 로그, 도구 처리기)을 먼저 만들어 단위 테스트하고, 마지막에 `FastMCP`로 도구를 등록해 streamable HTTP 앱으로 조립한다. 인증(토큰 유효성)은 HTTP 미들웨어가, 인가(스코프)는 도구 처리기가 한다. 서버에 LLM은 없다.

**Tech Stack:** Python 3.11+, `mcp` SDK(`>=1.12,<2`, `FastMCP`), Starlette/uvicorn(SDK 의존성), `filelock`, `tzdata`, pytest, git CLI.

## Global Constraints

설계 문서 `docs/superpowers/specs/2026-10-14-mcp-server-design.md`에서 옮긴 값이다. 모든 태스크에 적용된다.

- 위키는 `git show <WIKI_REF>:<path>`로만 읽는다(기본 ref `main`). 작업 트리의 `wiki/`는 읽지 않는다. 셸을 거치지 않고 인자 목록으로 실행한다.
- `raw/`는 git에 넣지 않는다. 서버는 raw에 **쓰기만** 하며, 조회 도구는 raw 내용이나 경로를 반환하지 않는다. `get_pattern` 응답에서 frontmatter `sources`를 제거한다.
- raw 파일명: 시간대 `Asia/Seoul` 기준 `raw/YYYY-MM-DD/HHMMSS.txt`, 같은 이름이 있으면 `-2`, `-3` … . 최종 파일은 배타적 생성(`"x"` 모드)으로 만든다. 임시 파일 후 rename 금지.
- 중복 검사: 줄바꿈(`\r\n`, `\r` → `\n`), 줄끝 공백, 끝의 빈 줄을 정규화한 UTF-8 텍스트의 SHA-256.
- 제출 검증: 빈 텍스트(공백만 포함) 거부, NUL(`\x00`) 거부, UTF-8 바이트 상한 기본 `1048576`.
- 해시 확인부터 파일 생성까지 프로세스 내 락(`threading.Lock`) + 파일 락(`filelock`, `raw/.submit.lock`)으로 묶는다.
- 스코프는 `read`, `submit` 두 가지. `get_index`, `get_pattern`, `get_infra`는 `read`, `submit_report`는 `submit`.
- `submit_report` 속도 제한: 토큰별 60초에 10회.
- 패턴 id 정규식 `^[a-z0-9][a-z0-9-]*$`(fullmatch). `sections` 허용 값: `원인`, `증상`, `해결방법`, `관련 패턴`.
- 접근 로그는 JSON lines(`time`, `token`, `tool`, `args`, `status`). **보고서 본문은 절대 기록하지 않는다**(길이와 해시 앞 12자만).
- 서버 `instructions`는 `main` ref의 `CLAUDE.md`에서 `## 외부 에이전트용 Query 가이드` 절 본문만 추출한다.
- 제출 성공 응답 문구(정확히): `raw 저장 완료. 컴파일 대기 중(담당자 수동 처리)이며 위키 조회에 반영되기까지 시간이 걸립니다.`
- 중복 응답 문구(정확히): `동일한 내용의 보고서가 이미 저장되어 있어 저장하지 않았습니다.`
- 서버 프로세스는 1개로 운영한다.
- 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`를 붙인다.

## 파일 구조

```
MonitoringWiki/
├─ .gitignore                         # Task 1: raw/와 Python 산출물 제외
└─ server/
   ├─ pyproject.toml                  # Task 1
   ├─ README.md                       # Task 9: 실행·토큰 발급·운영 주의
   ├─ SPIKE.md                        # Task 2: SDK 확인 결과
   ├─ scripts/
   │  ├─ spike_check.py               # Task 2
   │  └─ smoke.py                     # Task 9: 실행 중 서버 접속 확인
   ├─ src/wiki_mcp/
   │  ├─ __init__.py                  # Task 1
   │  ├─ config.py                    # Task 3: 환경 변수 → Settings
   │  ├─ wiki_reader.py               # Task 4: git ref에서 위키 읽기
   │  ├─ raw_store.py                 # Task 5: raw 저장
   │  ├─ auth.py                      # Task 6: 토큰 검증, 스코프, 해시 CLI
   │  ├─ ratelimit.py                 # Task 6
   │  ├─ instructions.py              # Task 7: 외부 가이드 추출
   │  ├─ access_log.py                # Task 7
   │  ├─ handlers.py                  # Task 8: 도구 처리(인가·로그 포함)
   │  ├─ app.py                       # Task 9: FastMCP 조립, 미들웨어, /healthz, main
   │  └─ pending.py                   # Task 10: 컴파일 대기 목록 CLI
   └─ tests/
      ├─ conftest.py                  # Task 1: 임시 git 위키 저장소 픽스처
      └─ test_*.py
```

## 실행 환경 공통

모든 명령은 저장소 루트에서 시작한다(`/c/Users/sun44/vscode/MonitoringWiki`). Python 명령은 `server/` 디렉터리에서 가상환경을 활성화한 뒤 실행한다.

- Windows Git Bash: `cd server && source .venv/Scripts/activate`
- Linux: `cd server && source .venv/bin/activate`

---

### Task 1: 저장소 git 초기화와 서버 프로젝트 골격

**Files:**
- Modify: `.gitignore`
- Create: `server/pyproject.toml`, `server/src/wiki_mcp/__init__.py`, `server/tests/conftest.py`, `server/tests/test_smoke.py`

**Interfaces:**
- Produces: 패키지 `wiki_mcp`(`__version__ = "0.1.0"`), pytest 픽스처 `wiki_repo(tmp_path) -> Path`(`main` 브랜치에 아래 파일이 커밋된 임시 저장소, 빈 `raw/` 디렉터리 포함):
  - `CLAUDE.md`: `## Query`(본문 "내부용 절입니다."), `## 외부 에이전트용 Query 가이드`(본문 "외부 가이드 본문입니다." + "`get_index`로 색인을 읽습니다."), `## Lint`(본문 "린트 절입니다.")
  - `wiki/index.md`(행 `| [p1](patterns/p1.md) | 요약 |` 포함), `wiki/infra/cluster.md`(제목 `# 클러스터 구성`), `wiki/patterns/sample-pattern.md`(`sources: [raw/2026-10-01/101010.txt]`, 섹션 4개), `wiki/log.md`(ingest 항목에 `raw/2026-10-01/101010.txt`)
  - 헬퍼 `git(root, *args)`, `write(root, rel, text)`

- [ ] **Step 0: 사전 조건 확인**

```bash
python --version                                  # 3.11 이상
git --version                                     # 2.28 이상(git init -b 지원)
git config user.name && git config user.email     # 둘 다 출력돼야 커밋 가능
```
Expected: 세 조건 모두 충족. 하나라도 아니면 진행하지 말고 사람에게 보고한다(git 사용자 정보는 사용자가 정할 값이다).

- [ ] **Step 1: 저장소 git 초기화**

```bash
cd /c/Users/sun44/vscode/MonitoringWiki
git init -b main
git status --short
```
Expected: `raw/`가 목록에 없음(이미 `.gitignore`에 있음). `CLAUDE.md`, `wiki/`, `docs/`, `.gitignore`가 미추적으로 보임.

- [ ] **Step 2: `.gitignore`에 Python 산출물 추가**

`.gitignore` 전체를 다음으로 바꾼다.

```gitignore
# 원문 보고서(개인정보 포함)는 git에 넣지 않음. 서버 디스크에 두고 별도 백업.
raw/

# Python
server/.venv/
__pycache__/
*.egg-info/
.pytest_cache/
```

- [ ] **Step 3: 기존 위키를 첫 커밋으로 올림**

```bash
git add .gitignore CLAUDE.md wiki docs
git commit -m "chore: initialize MonitoringWiki repository

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git ls-files | grep -c '^raw/' || true
```
Expected: 마지막 줄 `0`(raw 파일이 커밋되지 않음).

- [ ] **Step 4: `server/pyproject.toml` 작성**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "wiki-mcp"
version = "0.1.0"
description = "MonitoringWiki MCP server"
requires-python = ">=3.11"
dependencies = [
  "mcp>=1.12,<2",
  "filelock>=3.12",
  "tzdata>=2024.1",
  "uvicorn>=0.30",
]

[project.optional-dependencies]
dev = ["pytest>=8", "httpx>=0.27"]

[project.scripts]
wiki-mcp = "wiki_mcp.app:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 5: 실패하는 스모크 테스트 작성** — `server/tests/test_smoke.py`

```python
import subprocess

import wiki_mcp


def test_package_imports():
    assert wiki_mcp.__version__ == "0.1.0"


def test_fixture_repo_is_on_main(wiki_repo):
    branch = subprocess.run(
        ["git", "-C", str(wiki_repo), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert branch == "main"
    assert (wiki_repo / "raw").is_dir()
```

- [ ] **Step 6: 가상환경 만들고 실패 확인**

```bash
cd server
python -m venv .venv
source .venv/Scripts/activate   # Linux: source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/test_smoke.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_mcp'` 또는 `fixture 'wiki_repo' not found`.

- [ ] **Step 7: 패키지와 픽스처 작성**

`server/src/wiki_mcp/__init__.py`:

```python
"""MonitoringWiki MCP 서버."""

__version__ = "0.1.0"
```

`server/tests/conftest.py`:

```python
import subprocess
from pathlib import Path

import pytest

CLAUDE_MD = """# 규칙

## Query
내부용 절입니다. `wiki/index.md`를 읽습니다.

## 외부 에이전트용 Query 가이드
외부 가이드 본문입니다.
1. `get_index`로 색인을 읽습니다.

## Lint
린트 절입니다.
"""

INDEX_MD = "# 색인\n\n| 패턴 | 요약 |\n|---|---|\n| [p1](patterns/p1.md) | 요약 |\n"

INFRA_MD = "---\nid: infra-cluster\nas_of: 2026-10-14\n---\n# 클러스터 구성\n"

PATTERN_MD = """---
id: sample-pattern
summary: 샘플 요약
confidence: low
resources: [query]
first_seen: 2026-10-01
last_seen: 2026-10-01
occurrences: 1
sources: [raw/2026-10-01/101010.txt]
solution_origin: report
---
# 샘플 패턴

## 원인
원인 본문

## 증상
- **query**: 증상 본문

## 해결방법
해결 본문

## 관련 패턴
없음
"""

LOG_MD = "# 작업 로그\n\n## [2026-10-01 10:20] ingest | raw/2026-10-01/101010.txt\n- 처리\n"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def wiki_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "test")
    git(root, "config", "core.autocrlf", "false")
    write(root, "CLAUDE.md", CLAUDE_MD)
    write(root, "wiki/index.md", INDEX_MD)
    write(root, "wiki/infra/cluster.md", INFRA_MD)
    write(root, "wiki/patterns/sample-pattern.md", PATTERN_MD)
    write(root, "wiki/log.md", LOG_MD)
    write(root, ".gitignore", "raw/\n")
    git(root, "add", "-A")
    git(root, "commit", "-m", "init")
    (root / "raw").mkdir()
    return root
```

- [ ] **Step 8: 통과 확인**

```bash
python -m pytest tests/test_smoke.py -v
```
Expected: 2 passed.

- [ ] **Step 9: 커밋**

```bash
cd ..
git add .gitignore server/pyproject.toml server/src/wiki_mcp/__init__.py server/tests/conftest.py server/tests/test_smoke.py
git commit -m "feat(server): add MCP server project skeleton and test fixture

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: SDK 확인(스파이크)

설계가 기대는 SDK 기능을 설치 버전에서 확인한다. **하나라도 `MISMATCH`면 이후 태스크를 진행하지 말고 출력 전체와 함께 사람에게 보고한다**(대안 선택은 설계 결정이다).

**Files:**
- Create: `server/scripts/spike_check.py`, `server/SPIKE.md`

**Interfaces:**
- Consumes: Task 1의 가상환경.
- Produces: 이후 태스크가 쓰는 확인된 API — `from mcp.server.fastmcp import FastMCP, Context`, `FastMCP(name, instructions=...)`, `@mcp.tool(description=...)`, `mcp.streamable_http_app()`, `ctx.request_context.request`(HTTP 요청 객체 또는 `None`), 도구 예외가 `isError=True` 결과로 변환됨.

- [ ] **Step 1: 확인 스크립트 작성** — `server/scripts/spike_check.py`

```python
"""설치된 mcp SDK가 설계가 기대는 API를 제공하는지 확인한다."""
import importlib.metadata
import inspect

import anyio


async def check_tool_error() -> tuple[bool, str]:
    from mcp.server.fastmcp import FastMCP
    from mcp.shared.memory import create_connected_server_and_client_session

    server = FastMCP("spike")

    @server.tool()
    def boom() -> str:
        raise ValueError("의도된 오류")

    async with create_connected_server_and_client_session(server._mcp_server) as client:
        result = await client.call_tool("boom", {})
        return bool(result.isError), result.content[0].text


def main() -> int:
    from mcp.server.fastmcp import Context, FastMCP  # noqa: F401
    from mcp.shared.context import RequestContext

    checks: list[tuple[str, bool]] = []
    print("mcp version:", importlib.metadata.version("mcp"))

    init_params = inspect.signature(FastMCP.__init__).parameters
    checks.append(("FastMCP(instructions=...)", "instructions" in init_params))
    checks.append(("FastMCP.streamable_http_app", hasattr(FastMCP, "streamable_http_app")))
    checks.append(("FastMCP.tool(description=...)", "description" in inspect.signature(FastMCP.tool).parameters))
    fields = getattr(RequestContext, "__dataclass_fields__", {})
    checks.append(("RequestContext.request", "request" in fields))

    is_error, text = anyio.run(check_tool_error)
    print("tool error text:", text)
    checks.append(("도구 예외 → isError", is_error))

    for name, ok in checks:
        print(f"{'OK      ' if ok else 'MISMATCH'} {name}")
    all_ok = all(ok for _, ok in checks)
    print("ALL OK" if all_ok else "MISMATCH 있음: 진행 중단 후 보고")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 실행**

```bash
cd server
python scripts/spike_check.py
```
Expected: 다섯 줄이 모두 `OK`, 마지막 줄 `ALL OK`, 종료 코드 0. `MISMATCH`가 하나라도 있으면 여기서 멈추고 보고한다.

- [ ] **Step 3: 배포 환경 관련 수동 확인**

다음을 SDK 소스(`.venv`의 `mcp/server/fastmcp/server.py`, `mcp/server/transport_security.py`가 있으면 그 파일)에서 확인해 메모한다. 확인만 하고 코드는 바꾸지 않는다.
1. streamable HTTP 기본 경로가 `/mcp`인지.
2. Host 헤더 검사(DNS rebinding 보호)가 기본으로 켜지는지, 켜진다면 리버스 프록시 뒤에서 허용 호스트를 설정하는 방법.

- [ ] **Step 4: 결과 기록** — `server/SPIKE.md`

Step 2의 실제 출력 전체를 코드 블록으로 붙이고, Step 3의 두 항목에 대한 확인 결과(파일 경로와 해당 코드 줄 포함)를 적는다. 형식:

````markdown
# SDK 확인 결과 (YYYY-MM-DD)

## spike_check.py 출력
```
(Step 2 출력 전체)
```

## 배포 관련
1. streamable HTTP 기본 경로: (확인 결과, 근거 파일:줄)
2. Host 헤더 검사: (기본 동작, 프록시 뒤 설정 방법, 근거 파일:줄)
````

- [ ] **Step 5: 커밋**

```bash
cd ..
git add server/scripts/spike_check.py server/SPIKE.md
git commit -m "chore(server): verify mcp SDK APIs used by the design

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 설정

**Files:**
- Create: `server/src/wiki_mcp/config.py`, `server/tests/test_config.py`

**Interfaces:**
- Produces: `class ConfigError(Exception)`, `@dataclass(frozen=True) class Settings(wiki_root: Path, wiki_ref: str, tz: str, tokens_file: Path, access_log: Path, max_report_bytes: int, host: str, port: int)`, `load_settings(env: Mapping[str, str] | None = None) -> Settings`.

- [ ] **Step 1: 실패하는 테스트 작성** — `server/tests/test_config.py`

```python
from pathlib import Path

import pytest

from wiki_mcp.config import ConfigError, load_settings

BASE = {
    "WIKI_ROOT": "/repo",
    "WIKI_TOKENS_FILE": "/etc/wiki/tokens.json",
    "WIKI_ACCESS_LOG": "/var/log/wiki/access.jsonl",
}


def test_defaults():
    s = load_settings(BASE)
    assert s.wiki_root == Path("/repo")
    assert s.tokens_file == Path("/etc/wiki/tokens.json")
    assert s.access_log == Path("/var/log/wiki/access.jsonl")
    assert s.wiki_ref == "main"
    assert s.tz == "Asia/Seoul"
    assert s.max_report_bytes == 1_048_576
    assert (s.host, s.port) == ("127.0.0.1", 8000)


def test_overrides():
    s = load_settings({
        **BASE,
        "WIKI_REF": "release",
        "WIKI_TZ": "UTC",
        "WIKI_MAX_REPORT_BYTES": "2048",
        "WIKI_HOST": "0.0.0.0",
        "WIKI_PORT": "9000",
    })
    assert (s.wiki_ref, s.tz, s.max_report_bytes, s.host, s.port) == ("release", "UTC", 2048, "0.0.0.0", 9000)


@pytest.mark.parametrize("missing", ["WIKI_ROOT", "WIKI_TOKENS_FILE", "WIKI_ACCESS_LOG"])
def test_missing_required(missing):
    env = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_settings(env)


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_invalid_port(value):
    with pytest.raises(ConfigError, match="WIKI_PORT"):
        load_settings({**BASE, "WIKI_PORT": value})
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_mcp.config'`.

- [ ] **Step 3: 구현** — `server/src/wiki_mcp/config.py`

```python
"""환경 변수에서 서버 설정을 읽는다."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class ConfigError(Exception):
    """필수 설정이 없거나 값이 잘못됨."""


@dataclass(frozen=True)
class Settings:
    wiki_root: Path
    wiki_ref: str
    tz: str
    tokens_file: Path
    access_log: Path
    max_report_bytes: int
    host: str
    port: int


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key} 환경 변수가 필요합니다.")
    return value


def _optional(env: Mapping[str, str], key: str, default: str) -> str:
    return env.get(key, "").strip() or default


def _positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key}는 정수여야 합니다: {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{key}는 0보다 커야 합니다: {value}")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    return Settings(
        wiki_root=Path(_required(env, "WIKI_ROOT")),
        wiki_ref=_optional(env, "WIKI_REF", "main"),
        tz=_optional(env, "WIKI_TZ", "Asia/Seoul"),
        tokens_file=Path(_required(env, "WIKI_TOKENS_FILE")),
        access_log=Path(_required(env, "WIKI_ACCESS_LOG")),
        max_report_bytes=_positive_int(env, "WIKI_MAX_REPORT_BYTES", 1_048_576),
        host=_optional(env, "WIKI_HOST", "127.0.0.1"),
        port=_positive_int(env, "WIKI_PORT", 8000),
    )
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_config.py -v`
Expected: 8 passed.

- [ ] **Step 5: 커밋**

```bash
cd ..
git add server/src/wiki_mcp/config.py server/tests/test_config.py
git commit -m "feat(server): load settings from environment

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: git ref 기반 위키 읽기

**Files:**
- Create: `server/src/wiki_mcp/wiki_reader.py`, `server/tests/test_wiki_reader.py`

**Interfaces:**
- Consumes: Task 1의 `wiki_repo` 픽스처.
- Produces:
  - 예외: `WikiReadError(Exception)`, `PatternNotFound(WikiReadError)`, `InvalidRequest(ValueError)`
  - 상수: `PATTERN_ID_RE`, `SECTION_NAMES = ("원인", "증상", "해결방법", "관련 패턴")`
  - `check_ref(root: Path, ref: str) -> None` (없으면 `WikiReadError`)
  - `git_show(root: Path, ref: str, path: str) -> str` (없으면 `FileNotFoundError`)
  - `list_files(root: Path, ref: str, directory: str) -> list[str]` (`"wiki/patterns/x.md"` 형태, 디렉터리 없으면 `[]`)
  - `read_index(root, ref) -> str`, `read_infra(root, ref) -> str` (없으면 `WikiReadError`)
  - `split_frontmatter(text: str) -> tuple[list[str], list[str]]`, `drop_field(frontmatter: list[str], field: str) -> list[str]`
  - `read_pattern(root, ref, pattern_id: str, sections: Sequence[str] | None = None) -> str`

- [ ] **Step 1: 실패하는 테스트 작성** — `server/tests/test_wiki_reader.py`

```python
import pytest

from wiki_mcp import wiki_reader as wr


def test_check_ref_ok(wiki_repo):
    wr.check_ref(wiki_repo, "main")


def test_check_ref_missing(wiki_repo):
    with pytest.raises(wr.WikiReadError):
        wr.check_ref(wiki_repo, "no-such-branch")


def test_read_index_ignores_uncommitted_changes(wiki_repo):
    (wiki_repo / "wiki/index.md").write_text("작업 중인 변경\n", encoding="utf-8")
    text = wr.read_index(wiki_repo, "main")
    assert "작업 중인 변경" not in text
    assert "| [p1](patterns/p1.md) | 요약 |" in text


def test_read_infra(wiki_repo):
    assert "# 클러스터 구성" in wr.read_infra(wiki_repo, "main")


def test_read_pattern_drops_sources(wiki_repo):
    text = wr.read_pattern(wiki_repo, "main", "sample-pattern")
    assert "sources:" not in text
    assert "raw/" not in text
    assert "summary: 샘플 요약" in text
    assert "# 샘플 패턴" in text
    for heading in ("## 원인", "## 증상", "## 해결방법", "## 관련 패턴"):
        assert heading in text


def test_read_pattern_selected_sections(wiki_repo):
    text = wr.read_pattern(wiki_repo, "main", "sample-pattern", ["해결방법"])
    assert "## 해결방법" in text and "해결 본문" in text
    assert "## 원인" not in text and "원인 본문" not in text
    assert "# 샘플 패턴" in text


def test_drop_field_multiline_list():
    frontmatter = ["id: x", "sources:", "  - raw/a.txt", "  - raw/b.txt", "summary: s"]
    assert wr.drop_field(frontmatter, "sources") == ["id: x", "summary: s"]


@pytest.mark.parametrize("bad", ["../CLAUDE", "-x", "Sample", "a/b", "", "abc\n"])
def test_read_pattern_rejects_bad_id(wiki_repo, bad):
    with pytest.raises(wr.InvalidRequest):
        wr.read_pattern(wiki_repo, "main", bad)


def test_read_pattern_rejects_unknown_section(wiki_repo):
    with pytest.raises(wr.InvalidRequest):
        wr.read_pattern(wiki_repo, "main", "sample-pattern", ["원인", "근거 한계"])


def test_read_pattern_missing(wiki_repo):
    with pytest.raises(wr.PatternNotFound, match="get_index"):
        wr.read_pattern(wiki_repo, "main", "no-such-pattern")


def test_list_files(wiki_repo):
    assert wr.list_files(wiki_repo, "main", "wiki/patterns") == ["wiki/patterns/sample-pattern.md"]
    assert wr.list_files(wiki_repo, "main", "wiki/missing") == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_wiki_reader.py -v`
Expected: FAIL — `ImportError: cannot import name 'wiki_reader'`.

- [ ] **Step 3: 구현** — `server/src/wiki_mcp/wiki_reader.py`

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_wiki_reader.py -v`
Expected: 16 passed.

- [ ] **Step 5: 실제 위키로 확인**

```bash
python -c "from pathlib import Path; from wiki_mcp import wiki_reader as wr; print(wr.read_pattern(Path('..'), 'main', 'es-index-template-conflict-and-korean-term-tokenization', ['해결방법']))"
```
Expected: frontmatter(`sources` 없음), 제목, `## 해결방법` 섹션만 출력.

- [ ] **Step 6: 커밋**

```bash
cd ..
git add server/src/wiki_mcp/wiki_reader.py server/tests/test_wiki_reader.py
git commit -m "feat(server): read wiki files from a git ref

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: raw 저장

**Files:**
- Create: `server/src/wiki_mcp/raw_store.py`, `server/tests/test_raw_store.py`

**Interfaces:**
- Produces:
  - 상수: `PENDING_MESSAGE`, `DUPLICATE_MESSAGE`, `LOCK_NAME = ".submit.lock"`, `IGNORED_NAMES = {".submit.lock", ".gitkeep"}`
  - `class ReportRejected(ValueError)`
  - `@dataclass(frozen=True) class SaveResult(status: str, path: str, message: str)` — `status`는 `"saved"` 또는 `"duplicate"`, `path`는 저장소 기준 POSIX 경로(`"raw/2026-10-14/111932.txt"`)
  - `normalize_for_hash(text: str) -> str`, `content_hash(text: str) -> str`
  - `class RawStore(root: Path, tz: str, max_bytes: int, now: Callable[[], datetime] | None = None)` — `save(text: str) -> SaveResult`, `iter_raw_files() -> Iterator[Path]`

- [ ] **Step 1: 실패하는 테스트 작성** — `server/tests/test_raw_store.py`

```python
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from wiki_mcp.raw_store import (
    DUPLICATE_MESSAGE,
    PENDING_MESSAGE,
    RawStore,
    ReportRejected,
    content_hash,
)

KST = ZoneInfo("Asia/Seoul")


def fixed(dt):
    return lambda: dt


def make_store(tmp_path, now, max_bytes=1000):
    return RawStore(tmp_path, "Asia/Seoul", max_bytes, now=now)


def test_saves_with_kst_name(tmp_path):
    store = make_store(tmp_path, fixed(datetime(2026, 10, 14, 11, 19, 32, tzinfo=KST)))
    result = store.save("보고서 A\n")
    assert result.status == "saved"
    assert result.path == "raw/2026-10-14/111932.txt"
    assert result.message == PENDING_MESSAGE


def test_utc_clock_converted_to_kst(tmp_path):
    store = make_store(tmp_path, fixed(datetime(2026, 10, 13, 15, 30, 0, tzinfo=timezone.utc)))
    assert store.save("보고서").path == "raw/2026-10-14/003000.txt"


def test_same_second_gets_suffix(tmp_path):
    store = make_store(tmp_path, fixed(datetime(2026, 10, 14, 9, 0, 0, tzinfo=KST)))
    assert store.save("첫째").path == "raw/2026-10-14/090000.txt"
    assert store.save("둘째").path == "raw/2026-10-14/090000-2.txt"
    assert store.save("셋째").path == "raw/2026-10-14/090000-3.txt"


def test_preserves_text_exactly(tmp_path):
    store = make_store(tmp_path, fixed(datetime(2026, 10, 14, 9, 0, 0, tzinfo=KST)))
    text = "줄1\r\n줄2  \n"
    path = store.save(text).path
    assert (tmp_path / path).read_bytes() == text.encode("utf-8")


def test_duplicate_after_normalization(tmp_path):
    store = make_store(tmp_path, fixed(datetime(2026, 10, 14, 9, 0, 0, tzinfo=KST)))
    first = store.save("원인: A\n해결: B\n")
    again = store.save("원인: A   \r\n해결: B\r\n\r\n")
    assert again.status == "duplicate"
    assert again.path == first.path
    assert again.message == DUPLICATE_MESSAGE
    assert len(list((tmp_path / "raw").rglob("*.txt"))) == 1


def test_content_hash_ignores_trailing_whitespace():
    assert content_hash("a \r\nb\n\n") == content_hash("a\nb")
    assert content_hash("a\nb") != content_hash("a\nc")


@pytest.mark.parametrize(
    "text, match",
    [("", "빈"), ("   \n ", "빈"), ("a\x00b", "NUL"), ("가" * 400, "너무 큽니다")],
)
def test_rejects_invalid(tmp_path, text, match):
    store = make_store(tmp_path, fixed(datetime(2026, 10, 14, 9, 0, 0, tzinfo=KST)))
    with pytest.raises(ReportRejected, match=match):
        store.save(text)


def test_concurrent_saves_never_overwrite(tmp_path):
    store = make_store(tmp_path, fixed(datetime(2026, 10, 14, 9, 0, 0, tzinfo=KST)))
    results, errors = [], []

    def worker(i):
        try:
            results.append(store.save(f"보고서 {i}"))
        except Exception as exc:  # 실패 원인을 assert에서 보이도록 수집
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    paths = {r.path for r in results}
    assert len(paths) == 20
    contents = {(tmp_path / p).read_text(encoding="utf-8") for p in paths}
    assert contents == {f"보고서 {i}" for i in range(20)}


def test_ignores_lock_and_gitkeep(tmp_path):
    store = make_store(tmp_path, fixed(datetime(2026, 10, 14, 9, 0, 0, tzinfo=KST)))
    (tmp_path / "raw" / ".gitkeep").write_text("", encoding="utf-8")
    store.save("내용")
    assert {p.name for p in store.iter_raw_files()} == {"090000.txt"}
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_raw_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_mcp.raw_store'`.

- [ ] **Step 3: 구현** — `server/src/wiki_mcp/raw_store.py`

```python
"""승인된 보고서 원문을 raw/에 저장한다. git 작업은 하지 않는다."""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator
from zoneinfo import ZoneInfo

from filelock import FileLock

PENDING_MESSAGE = "raw 저장 완료. 컴파일 대기 중(담당자 수동 처리)이며 위키 조회에 반영되기까지 시간이 걸립니다."
DUPLICATE_MESSAGE = "동일한 내용의 보고서가 이미 저장되어 있어 저장하지 않았습니다."
LOCK_NAME = ".submit.lock"
IGNORED_NAMES = {LOCK_NAME, ".gitkeep"}


class ReportRejected(ValueError):
    """제출된 보고서가 저장 조건을 만족하지 않음."""


@dataclass(frozen=True)
class SaveResult:
    status: str
    path: str
    message: str


def normalize_for_hash(text: str) -> str:
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in unified.split("\n")]
    return "\n".join(lines).rstrip("\n")


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()


class RawStore:
    def __init__(
        self,
        root: Path,
        tz: str,
        max_bytes: int,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = root
        self.raw_dir = root / "raw"
        self.tz = ZoneInfo(tz)
        self.max_bytes = max_bytes
        self._now = now or (lambda: datetime.now(self.tz))
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.Lock()
        self._file_lock = FileLock(str(self.raw_dir / LOCK_NAME))

    def save(self, text: str) -> SaveResult:
        self._validate(text)
        digest = content_hash(text)
        with self._thread_lock, self._file_lock:
            existing = self._find_duplicate(digest)
            if existing is not None:
                return SaveResult("duplicate", existing, DUPLICATE_MESSAGE)
            path = self._create_file(text)
        return SaveResult("saved", path, PENDING_MESSAGE)

    def iter_raw_files(self) -> Iterator[Path]:
        for path in sorted(self.raw_dir.rglob("*")):
            if path.is_file() and path.name not in IGNORED_NAMES:
                yield path

    def _validate(self, text: str) -> None:
        if not text.strip():
            raise ReportRejected("빈 보고서는 저장할 수 없습니다.")
        if "\x00" in text:
            raise ReportRejected("NUL 문자가 포함된 보고서는 저장할 수 없습니다.")
        size = len(text.encode("utf-8"))
        if size > self.max_bytes:
            raise ReportRejected(f"보고서가 너무 큽니다: {size} bytes (상한 {self.max_bytes})")

    def _find_duplicate(self, digest: str) -> str | None:
        for path in self.iter_raw_files():
            existing = path.read_text(encoding="utf-8", errors="replace")
            if content_hash(existing) == digest:
                return self._relative(path)
        return None

    def _create_file(self, text: str) -> str:
        now = self._now().astimezone(self.tz)
        day_dir = self.raw_dir / now.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        base = now.strftime("%H%M%S")
        attempt = 1
        while True:
            name = f"{base}.txt" if attempt == 1 else f"{base}-{attempt}.txt"
            target = day_dir / name
            try:
                with open(target, "x", encoding="utf-8", newline="") as handle:
                    handle.write(text)
            except FileExistsError:
                attempt += 1
                continue
            return self._relative(target)

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_raw_store.py -v`
Expected: 12 passed.

- [ ] **Step 5: 커밋**

```bash
cd ..
git add server/src/wiki_mcp/raw_store.py server/tests/test_raw_store.py
git commit -m "feat(server): store approved reports in raw with dedup and locking

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 토큰 인증과 속도 제한

**Files:**
- Create: `server/src/wiki_mcp/auth.py`, `server/src/wiki_mcp/ratelimit.py`, `server/tests/test_auth.py`, `server/tests/test_ratelimit.py`

**Interfaces:**
- Produces:
  - `auth`: `VALID_SCOPES`, `AuthError(Exception)`(401), `ScopeError(Exception)`(403), `@dataclass(frozen=True) TokenEntry(name: str, sha256: str, scopes: frozenset[str])`, `hash_token(token: str) -> str`, `TokenStore(entries)` + `TokenStore.load(path: Path)` + `authenticate(authorization: str | None) -> TokenEntry`, `require_scope(entry, scope) -> None`, CLI `python -m wiki_mcp.auth <토큰>`(sha256 출력)
  - 토큰 파일 형식(JSON 배열): `[{"name": "query-agent", "sha256": "<64자 hex>", "scopes": ["read"]}]`
  - `ratelimit`: `RateLimited(Exception)`, `RateLimiter(limit: int, window_seconds: float, clock=time.monotonic)` + `check(key: str) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_auth.py`:

```python
import json

import pytest

from wiki_mcp.auth import AuthError, ScopeError, TokenStore, hash_token, main, require_scope


def write_tokens(path, items):
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


@pytest.fixture
def store(tmp_path):
    path = write_tokens(tmp_path / "tokens.json", [
        {"name": "query-agent", "sha256": hash_token("read-secret"), "scopes": ["read"]},
        {"name": "approver", "sha256": hash_token("submit-secret"), "scopes": ["submit"]},
    ])
    return TokenStore.load(path)


def test_authenticate_ok(store):
    assert store.authenticate("Bearer read-secret").name == "query-agent"
    assert store.authenticate("bearer submit-secret").name == "approver"


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer ", "Bearer wrong"])
def test_authenticate_rejects(store, header):
    with pytest.raises(AuthError):
        store.authenticate(header)


def test_require_scope(store):
    entry = store.authenticate("Bearer read-secret")
    require_scope(entry, "read")
    with pytest.raises(ScopeError, match="submit"):
        require_scope(entry, "submit")


def test_load_rejects_unknown_scope(tmp_path):
    path = write_tokens(tmp_path / "t.json", [{"name": "x", "sha256": hash_token("t"), "scopes": ["admin"]}])
    with pytest.raises(ValueError, match="admin"):
        TokenStore.load(path)


def test_load_rejects_bad_hash(tmp_path):
    path = write_tokens(tmp_path / "t.json", [{"name": "x", "sha256": "abc", "scopes": ["read"]}])
    with pytest.raises(ValueError, match="sha256"):
        TokenStore.load(path)


def test_load_rejects_empty(tmp_path):
    with pytest.raises(ValueError):
        TokenStore.load(write_tokens(tmp_path / "t.json", []))


def test_hash_cli(capsys):
    assert main(["read-secret"]) == 0
    assert capsys.readouterr().out.strip() == hash_token("read-secret")
```

`server/tests/test_ratelimit.py`:

```python
import pytest

from wiki_mcp.ratelimit import RateLimited, RateLimiter


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_limits_within_window():
    clock = Clock()
    limiter = RateLimiter(2, 60.0, clock=clock)
    limiter.check("a")
    limiter.check("a")
    with pytest.raises(RateLimited):
        limiter.check("a")
    limiter.check("b")


def test_window_slides():
    clock = Clock()
    limiter = RateLimiter(1, 60.0, clock=clock)
    limiter.check("a")
    clock.t = 60.0
    limiter.check("a")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_auth.py tests/test_ratelimit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_mcp.auth'`(및 `ratelimit`).

- [ ] **Step 3: 구현**

`server/src/wiki_mcp/auth.py`:

```python
"""베어러 토큰 인증과 스코프 확인. 토큰은 sha256 해시로만 보관한다."""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
from dataclasses import dataclass
from pathlib import Path

VALID_SCOPES = frozenset({"read", "submit"})


class AuthError(Exception):
    """토큰이 없거나 유효하지 않음(HTTP 401)."""


class ScopeError(Exception):
    """토큰에 필요한 스코프가 없음(HTTP 403)."""


@dataclass(frozen=True)
class TokenEntry:
    name: str
    sha256: str
    scopes: frozenset[str]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenStore:
    def __init__(self, entries: list[TokenEntry]) -> None:
        if not entries:
            raise ValueError("토큰이 하나 이상 필요합니다.")
        self.entries = entries

    @classmethod
    def load(cls, path: Path) -> "TokenStore":
        data = json.loads(path.read_text(encoding="utf-8"))
        entries: list[TokenEntry] = []
        for item in data:
            scopes = frozenset(item["scopes"])
            unknown = scopes - VALID_SCOPES
            if unknown:
                raise ValueError(f"알 수 없는 스코프 {sorted(unknown)} (토큰 {item['name']})")
            digest = str(item["sha256"]).lower()
            if len(digest) != 64:
                raise ValueError(f"sha256 값이 올바르지 않습니다 (토큰 {item['name']})")
            entries.append(TokenEntry(item["name"], digest, scopes))
        return cls(entries)

    def authenticate(self, authorization: str | None) -> TokenEntry:
        if not authorization:
            raise AuthError("Bearer 토큰이 필요합니다.")
        scheme, _, token = authorization.partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            raise AuthError("Bearer 토큰이 필요합니다.")
        digest = hash_token(token)
        match: TokenEntry | None = None
        for entry in self.entries:
            if hmac.compare_digest(entry.sha256, digest):
                match = entry
        if match is None:
            raise AuthError("유효하지 않은 토큰입니다.")
        return match


def require_scope(entry: TokenEntry, scope: str) -> None:
    if scope not in entry.scopes:
        raise ScopeError(f"토큰 {entry.name}에 '{scope}' 권한이 없습니다.")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("사용법: python -m wiki_mcp.auth <토큰>", file=sys.stderr)
        return 2
    print(hash_token(args[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`server/src/wiki_mcp/ratelimit.py`:

```python
"""토큰별 슬라이딩 윈도 속도 제한(단일 프로세스용)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable


class RateLimited(Exception):
    """허용 횟수를 넘음."""


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = self.clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                raise RateLimited(f"요청이 너무 많습니다. {self.window:.0f}초 동안 최대 {self.limit}회입니다.")
            hits.append(now)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_auth.py tests/test_ratelimit.py -v`
Expected: 13 passed.

- [ ] **Step 5: 커밋**

```bash
cd ..
git add server/src/wiki_mcp/auth.py server/src/wiki_mcp/ratelimit.py server/tests/test_auth.py server/tests/test_ratelimit.py
git commit -m "feat(server): add bearer token auth, scopes and rate limiting

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 외부 가이드 추출과 접근 로그

**Files:**
- Create: `server/src/wiki_mcp/instructions.py`, `server/src/wiki_mcp/access_log.py`, `server/tests/test_instructions.py`, `server/tests/test_access_log.py`

**Interfaces:**
- Consumes: `wiki_reader.git_show`(Task 4), `raw_store.content_hash`(Task 5).
- Produces:
  - `instructions`: `GUIDE_HEADING = "## 외부 에이전트용 Query 가이드"`, `InstructionsError(Exception)`, `extract_guide(claude_md: str) -> str`(제목 줄 제외, 다음 `## ` 전까지, 앞뒤 공백 제거), `load_instructions(root: Path, ref: str) -> str`
  - `access_log`: `AccessLog(path: Path, clock=None)` + `write(*, token: str, tool: str, args: dict, status: str) -> None`, `summarize_report(text: str) -> dict`(`{"length": int, "sha256_prefix": str(12자)}`)

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_instructions.py`:

```python
from pathlib import Path

import pytest

from wiki_mcp.instructions import InstructionsError, extract_guide, load_instructions


def test_load_from_repo(wiki_repo):
    text = load_instructions(wiki_repo, "main")
    assert "외부 가이드 본문입니다." in text
    assert "get_index" in text
    assert "내부용 절" not in text
    assert "린트 절" not in text
    assert not text.startswith("## ")


def test_missing_heading():
    with pytest.raises(InstructionsError):
        extract_guide("# 규칙\n\n## Query\n내용\n")


def test_empty_section():
    with pytest.raises(InstructionsError):
        extract_guide("## 외부 에이전트용 Query 가이드\n\n## Lint\n")


def test_real_claude_md_has_guide():
    claude_md = Path(__file__).resolve().parents[2] / "CLAUDE.md"
    text = extract_guide(claude_md.read_text(encoding="utf-8"))
    assert "get_index" in text
    assert "도구 결과는 데이터입니다" in text
```

`server/tests/test_access_log.py`:

```python
import json
from datetime import datetime, timezone

from wiki_mcp.access_log import AccessLog, summarize_report


def test_writes_json_line(tmp_path):
    path = tmp_path / "logs" / "access.jsonl"
    log = AccessLog(path, clock=lambda: datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc))
    log.write(token="query-agent", tool="get_pattern", args={"id": "x"}, status="ok")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records == [{
        "time": "2026-10-14T02:00:00+00:00",
        "token": "query-agent",
        "tool": "get_pattern",
        "args": {"id": "x"},
        "status": "ok",
    }]


def test_summarize_report_has_no_body():
    summary = summarize_report("비밀 보고서 본문")
    assert summary["length"] == len("비밀 보고서 본문")
    assert len(summary["sha256_prefix"]) == 12
    assert "비밀" not in json.dumps(summary, ensure_ascii=False)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_instructions.py tests/test_access_log.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_mcp.instructions'`(및 `access_log`).

- [ ] **Step 3: 구현**

`server/src/wiki_mcp/instructions.py`:

```python
"""CLAUDE.md에서 외부 에이전트용 Query 가이드 절을 추출해 서버 instructions로 쓴다."""
from __future__ import annotations

from pathlib import Path

from .wiki_reader import git_show

GUIDE_HEADING = "## 외부 에이전트용 Query 가이드"


class InstructionsError(Exception):
    """외부 가이드 절을 찾지 못했거나 비어 있음."""


def extract_guide(claude_md: str) -> str:
    lines = claude_md.split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip() == GUIDE_HEADING), None)
    if start is None:
        raise InstructionsError(f"CLAUDE.md에 '{GUIDE_HEADING}' 절이 없습니다.")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    body = "\n".join(lines[start + 1:end]).strip()
    if not body:
        raise InstructionsError("외부 가이드 절이 비어 있습니다.")
    return body


def load_instructions(root: Path, ref: str) -> str:
    try:
        text = git_show(root, ref, "CLAUDE.md")
    except FileNotFoundError as exc:
        raise InstructionsError(f"{ref}에 CLAUDE.md가 없습니다.") from exc
    return extract_guide(text)
```

`server/src/wiki_mcp/access_log.py`:

```python
"""접근 로그(JSON lines). 보고서 본문은 기록하지 않는다."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .raw_store import content_hash


class AccessLog:
    def __init__(self, path: Path, clock: Callable[[], datetime] | None = None) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()

    def write(self, *, token: str, tool: str, args: dict[str, Any], status: str) -> None:
        record = {
            "time": self._clock().isoformat(),
            "token": token,
            "tool": tool,
            "args": args,
            "status": status,
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock, open(self.path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def summarize_report(text: str) -> dict[str, Any]:
    return {"length": len(text), "sha256_prefix": content_hash(text)[:12]}
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_instructions.py tests/test_access_log.py -v`
Expected: 6 passed.

- [ ] **Step 5: 커밋**

```bash
cd ..
git add server/src/wiki_mcp/instructions.py server/src/wiki_mcp/access_log.py server/tests/test_instructions.py server/tests/test_access_log.py
git commit -m "feat(server): extract external query guide and add access log

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: 도구 처리기

SDK와 독립된 도구 처리 함수. 인증·인가·속도 제한·접근 로그를 한곳에서 처리한다.

**Files:**
- Create: `server/src/wiki_mcp/handlers.py`, `server/tests/test_handlers.py`

**Interfaces:**
- Consumes: `Settings`(Task 3), `wiki_reader`(Task 4), `RawStore`(Task 5), `TokenStore`·`require_scope`·`AuthError`(Task 6), `RateLimiter`(Task 6), `AccessLog`·`summarize_report`(Task 7).
- Produces:
  - `@dataclass Services(settings: Settings, tokens: TokenStore, store: RawStore, limiter: RateLimiter, log: AccessLog)`
  - `handle_get_index(svc, authorization: str | None) -> str`
  - `handle_get_pattern(svc, authorization, pattern_id: str, sections: list[str] | None = None) -> str`
  - `handle_get_infra(svc, authorization) -> str`
  - `handle_submit_report(svc, authorization, text: str) -> dict`(`{"status", "path", "message"}`)
  - 실패 시 원래 예외를 그대로 다시 던진다(`AuthError`, `ScopeError`, `RateLimited`, `ReportRejected`, `InvalidRequest`, `PatternNotFound`, `WikiReadError`). 접근 로그 `status`: 성공 `ok`, 인증 실패 `unauthenticated`(토큰 이름 `-`), 그 외 `error:<예외 클래스명>`.

- [ ] **Step 1: 실패하는 테스트 작성** — `server/tests/test_handlers.py`

```python
import json

import pytest

from wiki_mcp.access_log import AccessLog
from wiki_mcp.auth import AuthError, ScopeError, TokenStore, hash_token
from wiki_mcp.config import Settings
from wiki_mcp.handlers import (
    Services,
    handle_get_index,
    handle_get_infra,
    handle_get_pattern,
    handle_submit_report,
)
from wiki_mcp.ratelimit import RateLimited, RateLimiter
from wiki_mcp.raw_store import PENDING_MESSAGE, RawStore

READ = "Bearer read-secret"
SUBMIT = "Bearer submit-secret"


@pytest.fixture
def svc(wiki_repo, tmp_path):
    tokens = tmp_path / "tokens.json"
    tokens.write_text(json.dumps([
        {"name": "query-agent", "sha256": hash_token("read-secret"), "scopes": ["read"]},
        {"name": "approver", "sha256": hash_token("submit-secret"), "scopes": ["submit"]},
    ]), encoding="utf-8")
    settings = Settings(
        wiki_root=wiki_repo, wiki_ref="main", tz="Asia/Seoul", tokens_file=tokens,
        access_log=tmp_path / "access.jsonl", max_report_bytes=10_000, host="127.0.0.1", port=8000,
    )
    return Services(
        settings=settings,
        tokens=TokenStore.load(tokens),
        store=RawStore(wiki_repo, "Asia/Seoul", 10_000),
        limiter=RateLimiter(2, 60.0),
        log=AccessLog(settings.access_log),
    )


def last_record(svc):
    lines = svc.settings.access_log.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])


def test_get_index_with_read_token(svc):
    assert "| [p1](patterns/p1.md) | 요약 |" in handle_get_index(svc, READ)
    record = last_record(svc)
    assert (record["token"], record["tool"], record["status"]) == ("query-agent", "get_index", "ok")


def test_get_pattern_and_infra(svc):
    assert "sources:" not in handle_get_pattern(svc, READ, "sample-pattern", ["원인"])
    assert last_record(svc)["args"] == {"id": "sample-pattern", "sections": ["원인"]}
    assert "# 클러스터 구성" in handle_get_infra(svc, READ)


def test_missing_token_is_logged(svc):
    with pytest.raises(AuthError):
        handle_get_index(svc, None)
    record = last_record(svc)
    assert (record["token"], record["status"]) == ("-", "unauthenticated")


def test_read_token_cannot_submit(svc):
    with pytest.raises(ScopeError):
        handle_submit_report(svc, READ, "승인된 보고서")
    assert not list((svc.settings.wiki_root / "raw").rglob("*.txt"))
    assert last_record(svc)["status"] == "error:ScopeError"


def test_submit_token_cannot_read(svc):
    with pytest.raises(ScopeError):
        handle_get_index(svc, SUBMIT)


def test_submit_saves_and_logs_without_body(svc):
    result = handle_submit_report(svc, SUBMIT, "비밀 원문 보고서")
    assert result["status"] == "saved"
    assert result["message"] == PENDING_MESSAGE
    assert (svc.settings.wiki_root / result["path"]).read_text(encoding="utf-8") == "비밀 원문 보고서"
    assert "비밀 원문 보고서" not in svc.settings.access_log.read_text(encoding="utf-8")
    assert last_record(svc)["args"]["length"] == len("비밀 원문 보고서")


def test_submit_rate_limited(svc):
    handle_submit_report(svc, SUBMIT, "보고서 1")
    handle_submit_report(svc, SUBMIT, "보고서 2")
    with pytest.raises(RateLimited):
        handle_submit_report(svc, SUBMIT, "보고서 3")
    assert last_record(svc)["status"] == "error:RateLimited"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_handlers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_mcp.handlers'`.

- [ ] **Step 3: 구현** — `server/src/wiki_mcp/handlers.py`

```python
"""MCP 도구의 실제 처리. 인증·인가·속도 제한·접근 로그를 여기서 처리하고 SDK와 독립적으로 테스트한다."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from . import wiki_reader
from .access_log import AccessLog, summarize_report
from .auth import AuthError, TokenEntry, TokenStore, require_scope
from .config import Settings
from .ratelimit import RateLimiter
from .raw_store import RawStore

T = TypeVar("T")


@dataclass
class Services:
    settings: Settings
    tokens: TokenStore
    store: RawStore
    limiter: RateLimiter
    log: AccessLog


def _run(
    svc: Services,
    authorization: str | None,
    tool: str,
    scope: str,
    args: dict[str, Any],
    action: Callable[[TokenEntry], T],
) -> T:
    try:
        entry = svc.tokens.authenticate(authorization)
    except AuthError:
        svc.log.write(token="-", tool=tool, args=args, status="unauthenticated")
        raise
    try:
        require_scope(entry, scope)
        result = action(entry)
    except Exception as exc:
        svc.log.write(token=entry.name, tool=tool, args=args, status=f"error:{type(exc).__name__}")
        raise
    svc.log.write(token=entry.name, tool=tool, args=args, status="ok")
    return result


def handle_get_index(svc: Services, authorization: str | None) -> str:
    s = svc.settings
    return _run(svc, authorization, "get_index", "read", {},
                lambda entry: wiki_reader.read_index(s.wiki_root, s.wiki_ref))


def handle_get_pattern(
    svc: Services,
    authorization: str | None,
    pattern_id: str,
    sections: list[str] | None = None,
) -> str:
    s = svc.settings
    args = {"id": pattern_id, "sections": list(sections) if sections else None}
    return _run(svc, authorization, "get_pattern", "read", args,
                lambda entry: wiki_reader.read_pattern(s.wiki_root, s.wiki_ref, pattern_id, sections))


def handle_get_infra(svc: Services, authorization: str | None) -> str:
    s = svc.settings
    return _run(svc, authorization, "get_infra", "read", {},
                lambda entry: wiki_reader.read_infra(s.wiki_root, s.wiki_ref))


def handle_submit_report(svc: Services, authorization: str | None, text: str) -> dict[str, str]:
    def action(entry: TokenEntry) -> dict[str, str]:
        svc.limiter.check(entry.name)
        result = svc.store.save(text)
        return {"status": result.status, "path": result.path, "message": result.message}

    return _run(svc, authorization, "submit_report", "submit", summarize_report(text), action)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_handlers.py -v`
Expected: 7 passed.

- [ ] **Step 5: 커밋**

```bash
cd ..
git add server/src/wiki_mcp/handlers.py server/tests/test_handlers.py
git commit -m "feat(server): add tool handlers with scope checks and access logging

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 서버 조립, 실행, 운영 문서

**Files:**
- Create: `server/src/wiki_mcp/app.py`, `server/tests/test_app.py`, `server/scripts/smoke.py`, `server/README.md`

**Interfaces:**
- Consumes: Task 2에서 확인한 SDK API, Task 3~8의 모든 모듈.
- Produces:
  - `build_services(settings: Settings) -> Services`
  - `create_mcp(svc: Services, instructions: str) -> FastMCP` — 도구 `get_index`, `get_pattern(id, sections=None)`, `get_infra`, `submit_report(text)` 등록
  - `class BearerAuthMiddleware(app, tokens: TokenStore, open_paths=("/healthz",))` — `/healthz` 외 HTTP 요청에 유효한 토큰이 없으면 401(`WWW-Authenticate: Bearer`)
  - `create_app(settings: Settings)` — ref 확인 → 서비스·가이드 로드 → `streamable_http_app()`에 `GET /healthz` 추가 → 미들웨어로 감싼 ASGI 앱
  - `main() -> None` — `load_settings()` 후 uvicorn 실행(콘솔 스크립트 `wiki-mcp`)
  - 상수 `SUBMIT_LIMIT_PER_MINUTE = 10`

- [ ] **Step 1: 실패하는 테스트 작성** — `server/tests/test_app.py`

```python
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from wiki_mcp.app import _authorization, build_services, create_app, create_mcp
from wiki_mcp.auth import hash_token
from wiki_mcp.config import Settings
from wiki_mcp.wiki_reader import WikiReadError


@pytest.fixture
def settings(wiki_repo, tmp_path):
    tokens = tmp_path / "tokens.json"
    tokens.write_text(json.dumps([
        {"name": "query-agent", "sha256": hash_token("read-secret"), "scopes": ["read"]},
    ]), encoding="utf-8")
    return Settings(
        wiki_root=wiki_repo, wiki_ref="main", tz="Asia/Seoul", tokens_file=tokens,
        access_log=tmp_path / "access.jsonl", max_report_bytes=10_000, host="127.0.0.1", port=8000,
    )


def test_healthz_without_token(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ref": "main"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_mcp_requires_valid_token(settings, headers):
    with TestClient(create_app(settings)) as client:
        response = client.post("/mcp", json={}, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_create_app_fails_without_ref(settings):
    with pytest.raises(WikiReadError):
        create_app(replace(settings, wiki_ref="no-such-branch"))


def test_tools_registered(settings):
    mcp = create_mcp(build_services(settings), "가이드")
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert names == {"get_index", "get_pattern", "get_infra", "submit_report"}


def test_authorization_header_from_request():
    ctx = SimpleNamespace(request_context=SimpleNamespace(
        request=SimpleNamespace(headers={"authorization": "Bearer x"})))
    assert _authorization(ctx) == "Bearer x"


def test_authorization_without_request():
    ctx = SimpleNamespace(request_context=SimpleNamespace(request=None))
    assert _authorization(ctx) is None
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_mcp.app'`.

- [ ] **Step 3: 구현** — `server/src/wiki_mcp/app.py`

```python
"""MCP 서버 조립: 도구 등록, 인증 미들웨어, 상태 확인, 실행.

도구 처리기(git 호출, 파일 락 대기)는 이벤트 루프를 막지 않도록 스레드에서 실행한다.
"""
from __future__ import annotations

import json

import uvicorn
from anyio import to_thread
from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import wiki_reader
from .access_log import AccessLog
from .auth import AuthError, TokenStore
from .config import Settings, load_settings
from .handlers import (
    Services,
    handle_get_index,
    handle_get_infra,
    handle_get_pattern,
    handle_submit_report,
)
from .instructions import load_instructions
from .ratelimit import RateLimiter
from .raw_store import RawStore

SUBMIT_LIMIT_PER_MINUTE = 10

GET_INDEX_DESCRIPTION = "장애 패턴 위키의 색인 전체를 반환합니다. 요약과 대표 시그니처 열을 보고 입력과 의미가 같은 패턴을 고르세요."
GET_PATTERN_DESCRIPTION = "패턴 페이지를 반환합니다. sections로 원인, 증상, 해결방법, 관련 패턴 중 일부만 요청할 수 있습니다."
GET_INFRA_DESCRIPTION = "현재 클러스터 구성(티어, 역할별 노드 수, 버전)을 반환합니다. 패턴 일치 판단의 근거로는 쓰지 마세요."
SUBMIT_DESCRIPTION = (
    "사람이 승인한 장애 보고서 전체(원인 판단·결론·권장 조치 포함)를 원문 그대로 제출합니다. "
    "질문에는 절대 사용하지 마세요. 제출된 보고서는 담당자가 수동으로 컴파일한 뒤 위키에 반영됩니다."
)


def build_services(settings: Settings) -> Services:
    return Services(
        settings=settings,
        tokens=TokenStore.load(settings.tokens_file),
        store=RawStore(settings.wiki_root, settings.tz, settings.max_report_bytes),
        limiter=RateLimiter(SUBMIT_LIMIT_PER_MINUTE, 60.0),
        log=AccessLog(settings.access_log),
    )


def _authorization(ctx: Context) -> str | None:
    request = ctx.request_context.request
    if request is None:
        return None
    return request.headers.get("authorization")


def create_mcp(svc: Services, instructions: str) -> FastMCP:
    mcp = FastMCP("monitoring-wiki", instructions=instructions)

    # ctx는 이벤트 루프 스레드에서 읽고, 처리기만 작업 스레드로 넘긴다.
    @mcp.tool(description=GET_INDEX_DESCRIPTION)
    async def get_index(ctx: Context) -> str:
        authorization = _authorization(ctx)
        return await to_thread.run_sync(lambda: handle_get_index(svc, authorization))

    @mcp.tool(description=GET_PATTERN_DESCRIPTION)
    async def get_pattern(id: str, ctx: Context, sections: list[str] | None = None) -> str:
        authorization = _authorization(ctx)
        return await to_thread.run_sync(lambda: handle_get_pattern(svc, authorization, id, sections))

    @mcp.tool(description=GET_INFRA_DESCRIPTION)
    async def get_infra(ctx: Context) -> str:
        authorization = _authorization(ctx)
        return await to_thread.run_sync(lambda: handle_get_infra(svc, authorization))

    @mcp.tool(description=SUBMIT_DESCRIPTION)
    async def submit_report(text: str, ctx: Context) -> str:
        authorization = _authorization(ctx)
        result = await to_thread.run_sync(lambda: handle_submit_report(svc, authorization, text))
        return json.dumps(result, ensure_ascii=False)

    return mcp


class BearerAuthMiddleware:
    """`/healthz`를 제외한 HTTP 요청에 유효한 Bearer 토큰을 요구한다(인증). 스코프(인가)는 도구 처리기가 확인한다."""

    def __init__(self, app, tokens: TokenStore, open_paths: tuple[str, ...] = ("/healthz",)) -> None:
        self.app = app
        self.tokens = tokens
        self.open_paths = set(open_paths)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["path"] not in self.open_paths:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            try:
                self.tokens.authenticate(headers.get("authorization"))
            except AuthError as exc:
                response = JSONResponse({"error": str(exc)}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(settings: Settings):
    wiki_reader.check_ref(settings.wiki_root, settings.wiki_ref)
    svc = build_services(settings)
    instructions = load_instructions(settings.wiki_root, settings.wiki_ref)
    app = create_mcp(svc, instructions).streamable_http_app()

    async def healthz(request: Request) -> JSONResponse:
        try:
            wiki_reader.check_ref(settings.wiki_root, settings.wiki_ref)
        except wiki_reader.WikiReadError as exc:
            return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)
        return JSONResponse({"status": "ok", "ref": settings.wiki_ref})

    app.router.routes.insert(0, Route("/healthz", healthz, methods=["GET"]))
    return BearerAuthMiddleware(app, svc.tokens)


def main() -> None:
    settings = load_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_app.py -v`
Expected: 7 passed.

- [ ] **Step 5: 실행 확인 스크립트 작성** — `server/scripts/smoke.py`

```python
"""실행 중인 서버에 접속해 instructions, 도구 목록, get_index를 확인한다.

사용법: python scripts/smoke.py http://127.0.0.1:8000/mcp <read-토큰>
"""
import sys

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def run(url: str, token: str) -> None:
    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("instructions 앞부분:", (init.instructions or "")[:80])
            tools = await session.list_tools()
            print("도구:", sorted(tool.name for tool in tools.tools))
            result = await session.call_tool("get_index", {})
            print("get_index isError:", result.isError)
            print(result.content[0].text[:200])


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    anyio.run(run, sys.argv[1], sys.argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: 실제 위키로 실행 확인(수동)**

```bash
mkdir -p ../.local-test
HASH=$(python -m wiki_mcp.auth smoke-read-token)
cat > ../.local-test/tokens.json <<EOF
[{"name": "smoke", "sha256": "$HASH", "scopes": ["read"]}]
EOF
WIKI_ROOT=.. WIKI_TOKENS_FILE=../.local-test/tokens.json WIKI_ACCESS_LOG=../.local-test/access.jsonl wiki-mcp &
sleep 3
python scripts/smoke.py http://127.0.0.1:8000/mcp smoke-read-token
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/mcp
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/mcp \
  -H "Host: wiki-mcp.internal" -H "Authorization: Bearer smoke-read-token" \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
kill %1
```
마지막 `curl`은 리버스 프록시 뒤처럼 다른 Host로 접속했을 때 서버가 거부하는지 확인한다. 결과 코드를 `server/SPIKE.md`의 "Host 헤더 검사" 항목에 추가로 적는다. `200`이 아니면(예: `421`) Host 검사가 켜져 있으므로 README의 프록시 설정이 **필수**다.

Expected:
- `instructions 앞부분:` 뒤에 CLAUDE.md 외부 가이드의 첫 문장
- `도구: ['get_index', 'get_infra', 'get_pattern', 'submit_report']`
- `get_index isError: False`와 `# MonitoringWiki 색인`으로 시작하는 텍스트
- `curl` 결과 `401`

`.local-test/`는 커밋하지 않는다(다음 Step에서 `.gitignore`에 추가).

- [ ] **Step 7: 운영 문서 작성** — `server/README.md`

````markdown
# MonitoringWiki MCP 서버

외부 에이전트가 장애 패턴 위키를 조회하고, 승인 주체가 승인된 장애 보고서를 제출하는 MCP 서버입니다. 서버에는 LLM이 없으며, 제출된 보고서의 컴파일은 담당자가 저장소에서 Claude Code로 수동 실행합니다. 설계: `docs/superpowers/specs/2026-10-14-mcp-server-design.md`

## 설치
```bash
cd server
python -m venv .venv
source .venv/bin/activate        # Windows Git Bash: source .venv/Scripts/activate
pip install -e .
```

## 설정(환경 변수)
| 변수 | 기본값 | 설명 |
|---|---|---|
| `WIKI_ROOT` | (필수) | 위키 저장소 경로 |
| `WIKI_REF` | `main` | 위키를 읽을 git ref |
| `WIKI_TZ` | `Asia/Seoul` | raw 파일명 시간대 |
| `WIKI_TOKENS_FILE` | (필수) | 토큰 파일 경로 |
| `WIKI_ACCESS_LOG` | (필수) | 접근 로그 경로(저장소 밖) |
| `WIKI_MAX_REPORT_BYTES` | `1048576` | 제출 크기 상한 |
| `WIKI_HOST`, `WIKI_PORT` | `127.0.0.1`, `8000` | 바인드 주소 |

## 토큰 발급
1. 토큰 문자열을 만들고 해시를 구합니다: `python -m wiki_mcp.auth <토큰>`
2. 토큰 파일(JSON 배열)에 해시만 저장합니다:
   ```json
   [
     {"name": "query-agent", "sha256": "<해시>", "scopes": ["read"]},
     {"name": "approver", "sha256": "<해시>", "scopes": ["submit"]}
   ]
   ```
3. 서버를 재시작합니다.

**발급 정책:** `submit` 토큰은 승인 주체(사람 또는 승인 시스템)에게만 발급합니다. 질문용 외부 에이전트에는 `read`만 줍니다. 제출 자체가 승인이므로, 질문 에이전트가 `submit`을 가지면 자기 분석을 스스로 승인하게 됩니다.

## 실행
```bash
WIKI_ROOT=/srv/MonitoringWiki WIKI_TOKENS_FILE=/etc/wiki-mcp/tokens.json WIKI_ACCESS_LOG=/var/log/wiki-mcp/access.jsonl wiki-mcp
```
- MCP 엔드포인트: `/mcp`(streamable HTTP), 상태 확인: `GET /healthz`
- HTTPS는 사내 리버스 프록시에서 처리합니다. 응답이 스트리밍(SSE)으로 나가므로 프록시 버퍼링을 꺼야 합니다.
- 서버가 Host 헤더를 검사하는 경우(`SPIKE.md`의 "Host 헤더 검사" 결과) 프록시가 업스트림 Host를 `127.0.0.1:<WIKI_PORT>`로 전달해야 합니다. nginx 예:
  ```nginx
  location /mcp {
      proxy_pass http://127.0.0.1:8000;
      proxy_set_header Host 127.0.0.1:8000;
      proxy_buffering off;
      proxy_read_timeout 300s;
  }
  ```
- 서버 프로세스는 1개로 운영합니다.

## 담당자 작업
- 컴파일 대기 목록: `WIKI_ROOT=<저장소> python -m wiki_mcp.pending`
- 컴파일 규칙은 저장소의 `CLAUDE.md` Ingest 절을 따르고, 끝나면 `main`에 커밋해야 조회에 반영됩니다.

## 주의
- `raw/`는 git에 넣지 않습니다. 개인정보가 포함된 원문이므로 **서버 디스크 백업을 반드시 따로 구성**하세요.
- 외부 instructions는 `main`의 `CLAUDE.md` "외부 에이전트용 Query 가이드" 절에서 서버 시작 시 읽습니다. 바꾸면 커밋 후 재시작하세요.
````

- [ ] **Step 8: 전체 테스트와 커밋**

`.gitignore` 끝에 다음 두 줄을 추가한다.

```gitignore

# 로컬 실행 확인용
.local-test/
```

```bash
python -m pytest -q
cd ..
git add .gitignore server/src/wiki_mcp/app.py server/tests/test_app.py server/scripts/smoke.py server/README.md
git commit -m "feat(server): assemble MCP app with auth middleware and healthz

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected(pytest): 모든 테스트 통과(0 failed).

---

### Task 10: 컴파일 대기 목록

**Files:**
- Create: `server/src/wiki_mcp/pending.py`, `server/tests/test_pending.py`

**Interfaces:**
- Consumes: `wiki_reader.git_show`, `list_files`, `split_frontmatter`, `check_ref`(Task 4), `raw_store.IGNORED_NAMES`(Task 5), `wiki_repo` 픽스처의 `git`, `write` 헬퍼(Task 1).
- Produces: `RAW_PATH_RE`, `referenced_raw_paths(root: Path, ref: str) -> set[str]`, `pending_raw_files(root: Path, ref: str) -> list[str]`, CLI `python -m wiki_mcp.pending`.
- 규칙: `main`의 `wiki/patterns/*.md` frontmatter `sources`, 또는 `main`의 `wiki/log.md` **ingest 항목**(`## [...] ingest | ...` 제목부터 다음 `## ` 전까지)에 경로가 있으면 컴파일된 것으로 본다. 다른 항목(lint 등)에만 있는 경로는 대기로 본다.

- [ ] **Step 1: 실패하는 테스트 작성** — `server/tests/test_pending.py`

```python
from conftest import git, write

from wiki_mcp.pending import main, pending_raw_files, referenced_raw_paths


def add_raw(root, rel, text="보고서"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_referenced_from_sources_and_ingest_log(wiki_repo):
    write(wiki_repo, "wiki/log.md",
          "# 작업 로그\n\n"
          "## [2026-10-01 10:20] ingest | raw/2026-10-01/101010.txt\n- 처리\n\n"
          "## [2026-10-02 09:10] ingest | 보고서\n- 원본: `raw/2026-10-02/080000.txt` 처리\n\n"
          "## [2026-10-02 10:00] lint | raw/2026-10-02/090000.txt 언급만\n")
    git(wiki_repo, "commit", "-am", "log")
    assert referenced_raw_paths(wiki_repo, "main") == {
        "raw/2026-10-01/101010.txt",
        "raw/2026-10-02/080000.txt",
    }


def test_pending_lists_uncompiled_raw(wiki_repo):
    add_raw(wiki_repo, "raw/2026-10-01/101010.txt")
    add_raw(wiki_repo, "raw/2026-10-02/120000.txt")
    (wiki_repo / "raw" / ".submit.lock").write_text("", encoding="utf-8")
    assert pending_raw_files(wiki_repo, "main") == ["raw/2026-10-02/120000.txt"]


def test_uncommitted_compile_is_still_pending(wiki_repo):
    add_raw(wiki_repo, "raw/2026-10-02/120000.txt")
    write(wiki_repo, "wiki/patterns/new-pattern.md", "---\nid: new-pattern\nsources: [raw/2026-10-02/120000.txt]\n---\n# 새 패턴\n")
    assert pending_raw_files(wiki_repo, "main") == ["raw/2026-10-02/120000.txt"]


def test_cli_output(wiki_repo, monkeypatch, capsys):
    add_raw(wiki_repo, "raw/2026-10-02/120000.txt")
    monkeypatch.setenv("WIKI_ROOT", str(wiki_repo))
    assert main() == 0
    out = capsys.readouterr().out
    assert "컴파일 대기 1건" in out
    assert "raw/2026-10-02/120000.txt" in out


def test_cli_nothing_pending(wiki_repo, monkeypatch, capsys):
    monkeypatch.setenv("WIKI_ROOT", str(wiki_repo))
    assert main() == 0
    assert "컴파일 대기 중인 raw가 없습니다." in capsys.readouterr().out


def test_cli_requires_root(monkeypatch, capsys):
    monkeypatch.delenv("WIKI_ROOT", raising=False)
    assert main() == 2


def test_cli_bad_ref(wiki_repo, monkeypatch, capsys):
    monkeypatch.setenv("WIKI_ROOT", str(wiki_repo))
    monkeypatch.setenv("WIKI_REF", "no-such-branch")
    assert main() == 1
    assert "no-such-branch" in capsys.readouterr().err
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_pending.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_mcp.pending'`.

- [ ] **Step 3: 구현** — `server/src/wiki_mcp/pending.py`

```python
"""담당자용: 아직 컴파일되지 않은 raw 파일 목록을 출력한다.

사용법: WIKI_ROOT=<저장소> [WIKI_REF=main] python -m wiki_mcp.pending
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from . import wiki_reader
from .raw_store import IGNORED_NAMES

RAW_PATH_RE = re.compile(r"raw/\d{4}-\d{2}-\d{2}/[^\s`'\"\],)]+")
INGEST_HEADING_RE = re.compile(r"^## \[[^\]]*\] ingest\b")


def _sources_text(frontmatter: list[str]) -> str:
    collected: list[str] = []
    inside = False
    for line in frontmatter:
        if line.startswith("sources:"):
            inside = True
            collected.append(line)
        elif inside and line.startswith((" ", "\t", "-")):
            collected.append(line)
        else:
            inside = False
    return "\n".join(collected)


def _ingest_entries(log_text: str) -> str:
    collected: list[str] = []
    inside = False
    for line in log_text.split("\n"):
        if line.startswith("## "):
            inside = bool(INGEST_HEADING_RE.match(line))
        if inside:
            collected.append(line)
    return "\n".join(collected)


def referenced_raw_paths(root: Path, ref: str) -> set[str]:
    referenced: set[str] = set()
    for path in wiki_reader.list_files(root, ref, "wiki/patterns"):
        if not path.endswith(".md"):
            continue
        frontmatter, _ = wiki_reader.split_frontmatter(wiki_reader.git_show(root, ref, path))
        referenced.update(RAW_PATH_RE.findall(_sources_text(frontmatter)))
    try:
        log_text = wiki_reader.git_show(root, ref, "wiki/log.md")
    except FileNotFoundError:
        log_text = ""
    referenced.update(RAW_PATH_RE.findall(_ingest_entries(log_text)))
    return referenced


def pending_raw_files(root: Path, ref: str) -> list[str]:
    raw_dir = root / "raw"
    if not raw_dir.exists():
        return []
    referenced = referenced_raw_paths(root, ref)
    files = [
        path.relative_to(root).as_posix()
        for path in sorted(raw_dir.rglob("*"))
        if path.is_file() and path.name not in IGNORED_NAMES
    ]
    return [path for path in files if path not in referenced]


def main() -> int:
    root_value = os.environ.get("WIKI_ROOT", "").strip()
    if not root_value:
        print("WIKI_ROOT 환경 변수가 필요합니다.", file=sys.stderr)
        return 2
    root = Path(root_value)
    ref = os.environ.get("WIKI_REF", "").strip() or "main"
    try:
        wiki_reader.check_ref(root, ref)
    except wiki_reader.WikiReadError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    pending = pending_raw_files(root, ref)
    if not pending:
        print("컴파일 대기 중인 raw가 없습니다.")
        return 0
    print(f"컴파일 대기 {len(pending)}건:")
    for path in pending:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_pending.py -v`
Expected: 7 passed.

- [ ] **Step 5: 실제 저장소로 확인**

```bash
WIKI_ROOT=.. python -m wiki_mcp.pending
```
Expected: `컴파일 대기 중인 raw가 없습니다.` (현재 raw 4개가 모두 패턴 `sources`에 있음). 다른 결과가 나오면 출력된 경로가 왜 미참조인지 확인해 보고한다.

- [ ] **Step 6: 전체 테스트와 커밋**

```bash
python -m pytest -q
cd ..
git add server/src/wiki_mcp/pending.py server/tests/test_pending.py
git commit -m "feat(server): add pending raw list for manual compile

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected(pytest): 모든 테스트 통과.
