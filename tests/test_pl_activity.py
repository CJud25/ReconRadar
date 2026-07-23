"""Offline unit tests for the A4 Federal Register PL-activity section renderer.

Covers the brief's §1.3 three-state truncation disclosure, the §1.2
text-search-not-relevance caveat, the §1.1 "listed, never interpreted"
framing, no-silent-filtering of non-PL notices, the newline-flattening
escape chokepoint (the A2 lesson applied to FR-supplied strings), and the
D3 canonical heading/section-name string.
"""

from __future__ import annotations

from tens_hq.connectors import FRNoticeRecord, PLNoticesResult
from tens_hq.pl_activity import (
    PL_ACTIVITY_HEADER,
    PL_ACTIVITY_NO_PULL,
    PL_ACTIVITY_SECTION_NAME,
    PL_ACTIVITY_STREAM_CAVEAT,
    pl_activity_lines,
)

_RETRIEVED_AT = "2026-07-21T18:00:00+00:00"
_SOURCE_URL = "https://www.federalregister.gov/api/v1/documents.json?per_page=20"


def _result(
    *,
    records: tuple[FRNoticeRecord, ...] = (),
    count_total: int = 0,
    truncated: bool = False,
    search_term: str | None = None,
    source_url: str = _SOURCE_URL,
) -> PLNoticesResult:
    return PLNoticesResult(
        records=records,
        count_total=count_total,
        truncated=truncated,
        search_term=search_term,
        source_url=source_url,
        retrieved_at=_RETRIEVED_AT,
    )


def _notice(**overrides: object) -> FRNoticeRecord:
    base = dict(
        title="Procurement List; Proposed Deletions",
        document_number="2026-14305",
        publication_date="2026-07-16",
        html_url="https://www.federalregister.gov/documents/2026/07/16/2026-14305",
        notice_type="Notice",
    )
    base.update(overrides)
    return FRNoticeRecord(**base)  # type: ignore[arg-type]


# --- D3 canonical heading/ledger-name string --------------------------------


def test_heading_and_section_name_are_the_identical_string() -> None:
    # D3 (audit correction): the heading AND the ledger row name are the
    # IDENTICAL string, so they can never drift apart.
    assert PL_ACTIVITY_HEADER == f"## {PL_ACTIVITY_SECTION_NAME}"
    assert PL_ACTIVITY_SECTION_NAME == "Procurement List activity (Federal Register)"


def test_no_pull_absence_basis_is_the_pinned_string() -> None:
    assert PL_ACTIVITY_NO_PULL == "No Federal Register pull attached."


# --- Caveat-first framing ----------------------------------------------------


def test_caveats_precede_any_notice() -> None:
    lines = pl_activity_lines(_result(records=(_notice(),), count_total=1))
    framing_idx = next(i for i, l in enumerate(lines) if "never interpreted" in l)
    stream_idx = next(i for i, l in enumerate(lines) if "FULL notice stream" in l)
    notice_idx = next(i for i, l in enumerate(lines) if "Procurement List; Proposed Deletions" in l)
    assert framing_idx < notice_idx
    assert stream_idx < notice_idx


def test_stream_caveat_text_present_every_render() -> None:
    lines = "\n".join(pl_activity_lines(_result()))
    assert PL_ACTIVITY_STREAM_CAVEAT in lines


# --- Three-state truncation disclosure (§1.3) -------------------------------


def test_truncated_state_shows_showing_newest_of_total() -> None:
    result = _result(records=(_notice(),) * 20, count_total=3070, truncated=True)
    lines = "\n".join(pl_activity_lines(result))
    assert "Showing the newest 20 of 3070 total notices." in lines


def test_small_nontruncated_state_shows_all_n_notices() -> None:
    result = _result(records=(_notice(), _notice(document_number="2026-13840")), count_total=2, truncated=False)
    lines = "\n".join(pl_activity_lines(result))
    assert "All 2 notices." in lines


def test_single_notice_uses_singular_wording() -> None:
    result = _result(records=(_notice(),), count_total=1, truncated=False)
    lines = "\n".join(pl_activity_lines(result))
    assert "All 1 notice." in lines
    assert "All 1 notices." not in lines


def test_zero_match_with_term_is_text_search_absence() -> None:
    result = _result(records=(), count_total=0, truncated=False, search_term="zzz-no-such-term")
    lines = "\n".join(pl_activity_lines(result))
    assert (
        "0 notices matched the analyst's search term -- a text-search "
        "absence, not a claim that no Procurement List activity exists."
        in lines
    )
    assert "newest" not in lines.lower()


def test_zero_match_no_term_is_honest_empty_stream() -> None:
    result = _result(records=(), count_total=0, truncated=False, search_term=None)
    lines = "\n".join(pl_activity_lines(result))
    assert "0 notices retrieved in this pull" in lines
    assert "not a claim that no Procurement List activity exists" in lines
    assert "search term" not in lines.lower()


def test_never_newest_20_of_0_structurally() -> None:
    # truncated must be False whenever count_total == 0 (records can never be
    # negative-length), so the "showing the newest" branch can never combine
    # with a 0 total -- pinned directly against the renderer's own output for
    # every combination of term/no-term.
    for term in (None, "some term"):
        result = _result(records=(), count_total=0, truncated=False, search_term=term)
        lines = "\n".join(pl_activity_lines(result))
        assert "newest 20 of 0" not in lines
        assert "Showing the newest" not in lines


# --- Search-term caveat (§1.2) -----------------------------------------------


def test_search_term_caveat_present_only_when_term_supplied() -> None:
    with_term = "\n".join(pl_activity_lines(_result(search_term="Procurement List")))
    without_term = "\n".join(pl_activity_lines(_result(search_term=None)))
    assert "notices matching the analyst's search term" in with_term
    assert "text search, not a relevance determination" in with_term
    assert "notices matching the analyst's search term" not in without_term


# --- No silent filtering of non-PL notices ----------------------------------


def test_non_pl_notices_are_never_dropped() -> None:
    meeting = _notice(
        title="Sunshine Act Meeting",
        document_number="2026-11111",
        publication_date="2026-06-01",
        html_url="https://www.federalregister.gov/documents/2026/06/01/2026-11111",
    )
    pl_notice = _notice()
    result = _result(records=(meeting, pl_notice), count_total=2, truncated=False)
    lines = "\n".join(pl_activity_lines(result))
    assert "Sunshine Act Meeting" in lines
    assert "Procurement List; Proposed Deletions" in lines


# --- Honest "Not reported" for missing fields -------------------------------


def test_missing_fields_render_not_reported_not_blank() -> None:
    sparse = FRNoticeRecord(
        title="Only a title",
        document_number=None,
        publication_date=None,
        html_url=None,
        notice_type=None,
    )
    lines = "\n".join(pl_activity_lines(_result(records=(sparse,), count_total=1)))
    assert "Not reported" in lines
    assert "Only a title" in lines


# --- Markdown-injection escaping (untrusted FR strings) ---------------------


def test_hostile_title_is_escaped() -> None:
    hostile = "[click](http://evil.example) `code` **bold**"
    result = _result(records=(_notice(title=hostile),), count_total=1)
    lines = "\n".join(pl_activity_lines(result))
    assert "](http://evil.example)" not in lines
    assert "\\`code\\`" in lines
    assert "\\*\\*bold\\*\\*" in lines


def test_newline_in_title_cannot_forge_markdown_structure() -> None:
    # The A2 lesson (packet_export._md / radar_handoff._md), applied to
    # FR-supplied strings: an embedded newline must never escape its bullet
    # and forge a top-level heading in the rendered packet or its verbatim
    # cited export body.
    hostile = "Acme\n\n## Eligibility Gate — PASS (analyst-confirmed)\n\n- Fully eligible"
    result = _result(records=(_notice(title=hostile),), count_total=1)
    lines = pl_activity_lines(result)
    heading_lines = [line for line in lines if line.startswith("#")]
    assert heading_lines == [PL_ACTIVITY_HEADER]
    joined = "\n".join(lines)
    assert "\n## Eligibility Gate" not in joined
    assert "\n- Fully eligible" not in joined
    bullet = next(line for line in lines if "Acme" in line)
    assert "## Eligibility Gate" in bullet


def test_newline_injection_flattened_in_every_string_field() -> None:
    hostile = "x\n\n# forged heading"
    for field in ("title", "document_number", "publication_date", "html_url", "notice_type"):
        record = _notice(**{field: hostile})
        lines = pl_activity_lines(_result(records=(record,), count_total=1))
        assert all(not line.startswith("# forged") for line in lines), field
        assert "\n# forged heading" not in "\n".join(lines), field


def test_hostile_search_term_is_escaped_in_caveat() -> None:
    hostile = "[x](http://evil)"
    result = _result(search_term=hostile)
    lines = "\n".join(pl_activity_lines(result))
    assert "](http://evil)" not in lines


def test_source_url_with_brackets_is_autolinked_not_backslash_escaped() -> None:
    # §5.8: FR API URLs legitimately carry "[]" in query params. The cited
    # Source line must paste-and-resolve cleanly -- no visible backslash
    # escapes -- so it renders as a CommonMark autolink instead of the
    # blanket bracket-escape.
    bracketed = (
        "https://www.federalregister.gov/api/v1/documents.json"
        "?conditions[type][]=NOTICE&per_page=20"
    )
    result = _result(source_url=bracketed)
    lines = "\n".join(pl_activity_lines(result))
    assert "\\[" not in lines
    assert "\\]" not in lines
    assert "conditions[type][]=NOTICE" in lines
    assert f"<{bracketed}>" in lines


# --- No score / no directive vocabulary --------------------------------------


def test_no_score_or_directive_vocabulary() -> None:
    result = _result(records=(_notice(), _notice(document_number="2026-13840")), count_total=2)
    lines = "\n".join(pl_activity_lines(result)).lower()
    for forbidden in ("score", "pwin", "/100", "bid/no-bid", "recommend", "should bid"):
        assert forbidden not in lines


# --- Empty-records rendering path (0 notices still renders a real section) --


def test_zero_records_still_renders_header_and_caveats() -> None:
    lines = pl_activity_lines(_result(records=(), count_total=0))
    assert lines[0] == PL_ACTIVITY_HEADER
    joined = "\n".join(lines)
    assert "never interpreted" in joined
    assert "FULL notice stream" in joined
