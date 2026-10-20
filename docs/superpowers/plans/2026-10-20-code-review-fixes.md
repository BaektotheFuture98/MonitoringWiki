# Code Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 코드 검토에서 발견된 4개 이슈(예외 위치 불일관, dead code, 불필요 코드, `errors="replace"` 불일관)를 수정한다.

**Architecture:** 이슈를 두 태스크로 분리한다. Task 1은 예외 클래스를 `errors.py`로 통일(여러 파일 임포트 변경). Task 2는 나머지 경미한 정리 3건(dead code 제거, `_merge_resources` 단순화, `errors="replace"` 제거)을 하나의 커밋으로 처리한다.

**Tech Stack:** Python 3.12+, pytest

## Global Constraints

- 서버 소스: `server/src/wiki_mcp/`
- 테스트: `server/tests/`
- 테스트 실행: `cd server && .venv/Scripts/python -m pytest -q`
- 기능 변경 없이 리팩터링만 한다. HTTP 응답·공개 인터페이스는 그대로 유지한다.
- 이슈 4(`sections=[]` 버그)는 실제 버그 아님. `if sections`가 `None`과 `[]` 모두 `False`로 처리해 두 경우 모두 전체 섹션을 반환한다.

---

### Task 1: 예외 클래스 `errors.py` 통일

`AuthError`·`ScopeError`는 `auth.py`에, `RateLimited`는 `ratelimit.py`에 정의되어 있어 `rest.py`가 두 곳에서 임포트해야 했다. 세 예외를 `errors.py`로 이동하고 원래 파일은 `errors.py`에서 재임포트해 외부 임포트 경로가 바뀌는 것을 막는다.

**Files:**
- Modify: `server/src/wiki_mcp/core/errors.py`
- Modify: `server/src/wiki_mcp/core/auth.py`
- Modify: `server/src/wiki_mcp/core/ratelimit.py`
- Modify: `server/src/wiki_mcp/core/middleware.py`
- Modify: `server/src/wiki_mcp/routers/rest.py`
- Modify: `server/tests/test_auth.py`
- Modify: `server/tests/test_ratelimit.py`

**Interfaces:**
- Produces: `core/errors.py`에서 `AuthError`, `ScopeError`, `RateLimited` 추가 익스포트

- [ ] **Step 1: 현재 테스트가 통과하는지 확인**

```
cd server && .venv/Scripts/python -m pytest -q
```
Expected: `257 passed, 3 skipped`

- [ ] **Step 2: `errors.py`에 세 예외 추가**

파일 끝에 다음 세 클래스를 추가한다:

```python
# server/src/wiki_mcp/core/errors.py (끝에 추가)

class AuthError(Exception):
    """토큰이 없거나 유효하지 않음(HTTP 401)."""


class ScopeError(Exception):
    """토큰에 필요한 스코프가 없음(HTTP 403)."""


class RateLimited(Exception):
    """허용 횟수를 넘음."""
```

- [ ] **Step 3: `auth.py`에서 클래스 정의 제거 → `errors.py`에서 임포트**

`auth.py`에서 `AuthError`·`ScopeError` 클래스 블록(4줄)을 제거하고, 파일 상단 임포트에 추가한다.

변경 전 (`auth.py` 6~19번째 줄):
```python
from pathlib import Path

VALID_SCOPES = frozenset({"read", "submit", "infra"})


class AuthError(Exception):
    """토큰이 없거나 유효하지 않음(HTTP 401)."""


class ScopeError(Exception):
    """토큰에 필요한 스코프가 없음(HTTP 403)."""
```

변경 후:
```python
from pathlib import Path

from wiki_mcp.core.errors import AuthError, ScopeError  # noqa: F401 — 외부 임포트 경로 유지

VALID_SCOPES = frozenset({"read", "submit", "infra"})
```

- [ ] **Step 4: `ratelimit.py`에서 클래스 정의 제거 → `errors.py`에서 임포트**

`ratelimit.py`에서 `RateLimited` 클래스 블록(2줄)을 제거하고, 상단 임포트에 추가한다.

변경 전 (`ratelimit.py` 8~10번째 줄):
```python
from typing import Callable


class RateLimited(Exception):
    """허용 횟수를 넘음."""
```

변경 후:
```python
from typing import Callable

from wiki_mcp.core.errors import RateLimited  # noqa: F401 — 외부 임포트 경로 유지
```

- [ ] **Step 5: `middleware.py` 임포트 수정**

변경 전:
```python
from wiki_mcp.core.auth import AuthError, TokenStore
```

변경 후:
```python
from wiki_mcp.core.auth import TokenStore
from wiki_mcp.core.errors import AuthError
```

- [ ] **Step 6: `rest.py` 임포트 통합**

변경 전 (`rest.py` 11~19번째 줄):
```python
from wiki_mcp.core.auth import AuthError, ScopeError
from wiki_mcp.core.errors import (
    JobNotFound,
    JobNotRetryable,
    ReportRejected,
    ReportTooLarge,
    WikiReadError,
)
from wiki_mcp.core.ratelimit import RateLimited
```

변경 후:
```python
from wiki_mcp.core.errors import (
    AuthError,
    JobNotFound,
    JobNotRetryable,
    RateLimited,
    ReportRejected,
    ReportTooLarge,
    ScopeError,
    WikiReadError,
)
```

- [ ] **Step 7: `test_auth.py` 임포트 수정**

변경 전:
```python
from wiki_mcp.core.auth import AuthError, ScopeError, TokenStore, hash_token, main, require_scope
```

변경 후:
```python
from wiki_mcp.core.auth import TokenStore, hash_token, main, require_scope
from wiki_mcp.core.errors import AuthError, ScopeError
```

- [ ] **Step 8: `test_ratelimit.py` 임포트 수정**

변경 전:
```python
from wiki_mcp.core.ratelimit import RateLimited, RateLimiter
```

변경 후:
```python
from wiki_mcp.core.errors import RateLimited
from wiki_mcp.core.ratelimit import RateLimiter
```

- [ ] **Step 9: 테스트 실행**

```
cd server && .venv/Scripts/python -m pytest -q
```
Expected: `257 passed, 3 skipped` (수치 변동 없음)

- [ ] **Step 10: 커밋**

```bash
git add server/src/wiki_mcp/core/errors.py \
        server/src/wiki_mcp/core/auth.py \
        server/src/wiki_mcp/core/ratelimit.py \
        server/src/wiki_mcp/core/middleware.py \
        server/src/wiki_mcp/routers/rest.py \
        server/tests/test_auth.py \
        server/tests/test_ratelimit.py
git commit -m "refactor: 예외 클래스 AuthError·ScopeError·RateLimited를 errors.py로 통일"
```

---

### Task 2: 소규모 정리 3건

각각 1~2줄 변경이고 논리적으로 동일한 "불필요 코드 제거" 범주이므로 하나의 커밋으로 처리한다.

**Files:**
- Modify: `server/src/wiki_mcp/app.py` (line 38–40)
- Modify: `server/src/wiki_mcp/services/wiki_service.py` (line 240–243)
- Modify: `server/src/wiki_mcp/repositories/raw_store.py` (line 85)

**정리 내용:**
- **이슈 3**: `_gemini_generator`의 `ConfigError` 체크 — `config.py`의 `_required`가 이미 빈 값을 거부하므로 이 분기는 절대 실행되지 않는다.
- **이슈 5**: `_merge_resources`의 `extra` 변수 — `RESOURCES`에 없는 리소스는 `parse_plan`에서 이미 검증해 걸러지므로 항상 빈 리스트다.
- **이슈 6**: `raw_store._find_duplicate`의 `errors="replace"` — 저장 시 UTF-8 strict로 쓰므로 저장된 파일은 항상 유효한 UTF-8이다.

- [ ] **Step 1: 현재 테스트 통과 확인**

```
cd server && .venv/Scripts/python -m pytest -q
```
Expected: `257 passed, 3 skipped`

- [ ] **Step 2: `app.py` dead code 제거**

변경 전 (`app.py` 36~43번째 줄):
```python
def _gemini_generator(settings: Settings, wiki: WikiStore) -> GeminiPlanGenerator:
    if not settings.gemini_api_key or not settings.llm_model:
        raise ConfigError("GEMINI_API_KEY와 WIKI_LLM_MODEL이 필요합니다(.env 또는 환경 변수).")
    combined = wiki.read("AGENTS.md") + "\n\n" + wiki.read("docs/wiki-spec.md")
    return GeminiPlanGenerator(
```

변경 후:
```python
def _gemini_generator(settings: Settings, wiki: WikiStore) -> GeminiPlanGenerator:
    combined = wiki.read("AGENTS.md") + "\n\n" + wiki.read("docs/wiki-spec.md")
    return GeminiPlanGenerator(
```

이어서 `app.py` 상단 임포트에서 `ConfigError`를 제거한다:

변경 전:
```python
from wiki_mcp.core.config import ConfigError, Settings, load_env_file, load_settings
```

변경 후:
```python
from wiki_mcp.core.config import Settings, load_env_file, load_settings
```

- [ ] **Step 3: `_merge_resources` 단순화**

변경 전 (`wiki_service.py` 240~243번째 줄):
```python
def _merge_resources(old: Sequence[str], new: Sequence[str]) -> tuple[str, ...]:
    known = [resource for resource in RESOURCES if resource in old or resource in new]
    extra = [resource for resource in old if resource not in RESOURCES]
    return tuple(known + extra)
```

변경 후:
```python
def _merge_resources(old: Sequence[str], new: Sequence[str]) -> tuple[str, ...]:
    return tuple(resource for resource in RESOURCES if resource in old or resource in new)
```

- [ ] **Step 4: `raw_store._find_duplicate`의 `errors="replace"` 제거**

변경 전 (`raw_store.py` 85번째 줄):
```python
            existing = path.read_text(encoding="utf-8", errors="replace")
```

변경 후:
```python
            existing = path.read_text(encoding="utf-8")
```

- [ ] **Step 5: 테스트 실행**

```
cd server && .venv/Scripts/python -m pytest -q
```
Expected: `257 passed, 3 skipped`

- [ ] **Step 6: 커밋**

```bash
git add server/src/wiki_mcp/app.py \
        server/src/wiki_mcp/services/wiki_service.py \
        server/src/wiki_mcp/repositories/raw_store.py
git commit -m "refactor: dead code 제거 및 불필요 코드 단순화"
```
