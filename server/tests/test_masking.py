import pytest

from wiki_mcp.core.masking import Masker, load_names

QUERY_LOG = (
    "run_time=25.24 success=Y host=10.1.2.3 service=web company=acme user=kim@example.com "
    "cmd=agg keyword=[에그, 계란] s_date=20250101"
)


def test_masks_query_log_key_values():
    masked = Masker().mask(QUERY_LOG)
    assert "company=<COMPANY>" in masked
    assert "user=<USER>" in masked
    assert "keyword=[<KEYWORD>]" in masked
    assert "host=<IP>" in masked
    assert "kim@example.com" not in masked and "acme" not in masked and "에그" not in masked


def test_masks_free_text_email_and_ip():
    masked = Masker().mask("담당 lee.s@corp.co.kr 확인, 노드 192.168.0.10에서 지연")
    assert masked == "담당 <USER> 확인, 노드 <IP>에서 지연"


@pytest.mark.parametrize("text", ["Elasticsearch 8.12.2", "1.2.3.4.5", "버전 7.17"])
def test_does_not_mask_versions(text):
    assert Masker().mask(text) == text


def test_masks_listed_names_longest_first_case_insensitive():
    masker = Masker(["Acme", "Acme Korea", "뉴엔"])
    assert masker.mask("ACME KOREA와 acme, 뉴엔 고객") == "<COMPANY>와 <COMPANY>, <COMPANY> 고객"


def test_mask_is_idempotent():
    masker = Masker(["뉴엔"])
    once = masker.mask(QUERY_LOG + " 뉴엔")
    assert masker.mask(once) == once


def test_find_leaks_reports_kinds_only():
    masker = Masker(["뉴엔"])
    assert masker.find_leaks("a@b.com 10.0.0.1 뉴엔") == ["이메일", "IPv4", "회사·고객명"]
    assert masker.find_leaks(masker.mask("a@b.com 10.0.0.1 뉴엔")) == []


def test_load_names(tmp_path):
    path = tmp_path / "names.txt"
    path.write_text("# 고객사 목록\nAcme\n\n  뉴엔  \n", encoding="utf-8")
    assert load_names(path) == ["Acme", "뉴엔"]
    assert load_names(None) == []
