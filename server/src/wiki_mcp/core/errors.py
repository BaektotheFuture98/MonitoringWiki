"""여러 계층이 던지고 라우터가 HTTP 상태로 바꾸는 예외 모음."""
from __future__ import annotations


class WikiReadError(Exception):
    """위키 파일을 읽지 못함."""


class PatternNotFound(WikiReadError):
    """요청한 패턴 페이지가 없음."""


class InvalidRequest(ValueError):
    """도구 입력값이 규칙에 맞지 않음."""


class JobNotFound(LookupError):
    """작업 ID에 해당하는 기록이 없음."""


class JobNotRetryable(ValueError):
    """실패하지 않은 작업은 다시 시도할 수 없음."""


class ReportRejected(ValueError):
    """제출된 보고서가 저장 조건을 만족하지 않음."""


class ReportTooLarge(ReportRejected):
    """보고서가 크기 상한을 넘음."""
