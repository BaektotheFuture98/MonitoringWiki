import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from wiki_mcp.store.raw_store import (
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
