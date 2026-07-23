"""Federal Register PL-activity packet section (A4).

Given a :class:`tens_hq.connectors.federal_register.PLNoticesResult` (the
connector's own ``retrieve``/``parse`` boundary performs the live pull -- see
:mod:`tens_hq.connectors.federal_register`), this module renders it as a
caveat-first Markdown section for the Opportunity Packet, positioned after
R2b and before the always-last R2a determination-support map (D3):

* **Notices are listed, never interpreted (§1.1).** The section renders the
  FR-supplied title/date/document-number/URL verbatim (through the escape
  chokepoint below). No add-vs-delete classification beyond what the title
  itself states, no relevance claim, and no link to the packet's contract
  unless the analyst draws it themselves.
* **A search term is a text search, not a relevance determination (§1.2).**
  When the analyst supplied one, a standing caveat names it explicitly.
* **Truncation is disclosed, three-state (§1.3, audit correction).** Exactly
  one of: truncated -> "showing the newest N of TOTAL total notices";
  0 < count <= 20 -> "all N notice(s)"; count == 0 with a term -> a
  text-search-absence line; count == 0 with no term -> an honest
  empty-stream line. Never "newest 20 of 0" -- structurally guaranteed by
  the connector's own ``truncated = count_total > len(records)`` (see
  ``PLNoticesResult``'s own docstring), not re-derived here.
* **The Commission's FULL notice stream, no silent filtering (§1.3/D3).**
  The stream also carries non-PL notices (meetings, etc.); this module never
  drops one, and the standing caveat says so.

This module is pure (no Streamlit, no network, no case store): the caller
(``bd_page``) performs the live pull via
:func:`tens_hq.connectors.federal_register.pull_pl_notices` on its own
explicit analyst action and hands the result here to render. The Opportunity
Packet builder (:mod:`tens_hq.opportunity_packet`) presence-gates this
section exactly like R2b: rendered ONLY when ``pl_notices is not None`` (the
analyst pulled it), omitted entirely otherwise -- a real, empty
``PLNoticesResult`` (0 notices) still renders, since the analyst DID pull it.
"""

from __future__ import annotations

from .connectors.federal_register import FRNoticeRecord, PLNoticesResult

# A LOCAL copy, exactly like incumbent_leads.py / pl_match.py /
# packet_export.py / radar_handoff.py. This module cannot import ``_md`` from
# opportunity_packet: that module imports THIS one to render its section, so
# the reverse import would be circular (see pl_match.py:221-227 for the
# established convention this follows).
#
# FR-supplied strings (titles especially) are untrusted (the A2 lesson,
# packet_export._md): flatten every line-boundary class BEFORE escaping, or
# an embedded newline in a notice title could forge a top-level Markdown
# heading in the rendered packet and its verbatim cited export body.
_MD_ESCAPE = {ch: "\\" + ch for ch in "\\`*[]()<>"}


def _md(value: object) -> str:
    if value is None:
        return ""
    flat = " ".join(str(value).splitlines())
    return "".join(_MD_ESCAPE.get(ch, ch) for ch in flat)


def _reported(value: object) -> str:
    if value is None or not str(value).strip():
        return "Not reported"
    return _md(value)


# A URL-safe sibling of ``_md``/``_reported`` (§5.8 fix): FR API URLs
# legitimately contain "[]" in query params (e.g. conditions[type][]=NOTICE),
# so the blanket escape above renders visible "\[" / "\]" that break
# paste-and-resolve in both the packet body and the exported deliverable.
# A clean absolute http(s) URL with no whitespace/angle-brackets/pipe is
# rendered as a CommonMark autolink (``<https://...>``), which preserves
# "[]()" literally and cannot itself carry an injection (autolinks cannot
# contain whitespace or angle brackets). Anything else -- a hostile or
# non-URL value -- still falls back to the fully-escaped ``_md`` rendering.
def _md_url(value: object) -> str:
    if value is None:
        return ""
    flat = " ".join(str(value).splitlines())
    if flat.startswith(("http://", "https://")) and not any(
        ch in flat for ch in (" ", "\t", "<", ">", "|")
    ):
        return f"<{flat}>"
    return "".join(_MD_ESCAPE.get(ch, ch) for ch in flat)


def _reported_url(value: object) -> str:
    if value is None or not str(value).strip():
        return "Not reported"
    return _md_url(value)


# D3: the heading AND the Section-ledger row (packet_export.py) are the
# IDENTICAL string (audit correction -- a prior draft let the two drift).
PL_ACTIVITY_SECTION_NAME = "Procurement List activity (Federal Register)"
PL_ACTIVITY_HEADER = f"## {PL_ACTIVITY_SECTION_NAME}"

PL_ACTIVITY_FRAMING = (
    "This section lists notices from the AbilityOne Commission's own Federal "
    "Register notice stream. Notices are listed, never interpreted: no "
    "add-vs-delete classification beyond what a title itself states, no "
    "relevance claim, and no link to this packet's contract unless the "
    "analyst draws it themselves."
)

PL_ACTIVITY_STREAM_CAVEAT = (
    "This is the Commission's FULL notice stream, which can include "
    "non-Procurement-List notices (meetings, etc.). Nothing is filtered out "
    "silently, and no notice's presence here is a claim that it relates to "
    "this contract."
)

# D4: the Section-ledger's honest absence basis, verbatim.
PL_ACTIVITY_NO_PULL = "No Federal Register pull attached."


def _search_term_caveat(term: str | None) -> str | None:
    # "Any notices listed" rather than "Notices below": the same caveat renders
    # in the zero-match state, where "below" would presuppose notices that
    # don't exist (adversarial-verify phrasing nit).
    if not term:
        return None
    return (
        f'Any notices listed are notices matching the analyst\'s search term "'
        f'{_md(term)}" -- a search term is a text search, not a relevance '
        "determination."
    )


def _count_line(result: PLNoticesResult) -> str:
    """The three-state truncation disclosure (§1.3), EXACTLY one branch.

    ``result.truncated`` is ``count_total > len(records)`` (computed by the
    connector, never re-derived here), which can only be ``True`` when
    ``count_total >= 1`` -- so the ``count_total == 0`` branches below can
    never be reached in the ``truncated`` state, and "showing the newest 20
    of 0" is structurally impossible.
    """

    if result.truncated:
        return (
            f"Showing the newest {len(result.records)} of "
            f"{result.count_total} total notices."
        )
    if result.count_total > 0:
        plural = "notice" if result.count_total == 1 else "notices"
        return f"All {result.count_total} {plural}."
    if result.search_term:
        return (
            "0 notices matched the analyst's search term -- a text-search "
            "absence, not a claim that no Procurement List activity exists."
        )
    return (
        "0 notices retrieved in this pull of the Commission's Federal "
        "Register stream -- an honest empty stream, not a claim that no "
        "Procurement List activity exists."
    )


def _record_lines(record: FRNoticeRecord) -> list[str]:
    return [
        f"- {_reported(record.title)}",
        f"  - Type: {_reported(record.notice_type)}; "
        f"Published: {_reported(record.publication_date)}; "
        f"Document number: {_reported(record.document_number)}",
        f"  - {_reported_url(record.html_url)}",
    ]


def pl_activity_lines(result: PLNoticesResult) -> list[str]:
    """Render the Federal Register PL-activity section (caveat-first, pure).

    Every FR-supplied string flows through the newline-flattening ``_md``
    escape chokepoint above (or its ``_reported`` wrapper); the standing
    caveats always precede any notice, and the three-state count/truncation
    line is rendered before the notice list so a reader sees the honest
    "how many, and is this everything" framing first.
    """

    lines: list[str] = [PL_ACTIVITY_HEADER, ""]
    lines.append(f"- {PL_ACTIVITY_FRAMING}")
    lines.append(f"- {PL_ACTIVITY_STREAM_CAVEAT}")
    term_caveat = _search_term_caveat(result.search_term)
    if term_caveat is not None:
        lines.append(f"- {term_caveat}")
    lines.append(f"- {_count_line(result)}")
    lines.append(
        f"- Source: {_reported_url(result.source_url)}; Retrieved at: "
        f"{_reported(result.retrieved_at)}."
    )
    lines.append("")
    if not result.records:
        return lines
    for record in result.records:
        lines.extend(_record_lines(record))
    lines.append("")
    return lines


__all__ = [
    "PL_ACTIVITY_FRAMING",
    "PL_ACTIVITY_HEADER",
    "PL_ACTIVITY_NO_PULL",
    "PL_ACTIVITY_SECTION_NAME",
    "PL_ACTIVITY_STREAM_CAVEAT",
    "pl_activity_lines",
]
