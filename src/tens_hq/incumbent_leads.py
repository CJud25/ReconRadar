"""Incumbent & teaming leads / PL-impact context for the cited Opportunity Packet
(roadmap spine: ... -> Capture Window -> **Incumbent & teaming leads** -> Geography
-> R2b).

Given the live USAspending Contract Facts already attached to the packet (see
:mod:`tens_hq.connectors.usaspending`), this module surfaces:

* **Incumbent competition leads** derived from fields the connector already
  parses (``extent_competed_code``, ``number_of_offers_received``): an FPDS
  code-driven, no-guess classification into competed / not-competed
  (sole-source) family, plus the single-offer entrenchment signal.
* **Incumbent registration facts**: the recipient's ``business_categories``
  (public SAM-registration facts, e.g. small-business status).
* **Teaming-posture leads** from an optional subawards pull (D1 -- scope is
  THIS award only, not a market-wide sweep) cross-referenced by normalized
  EXACT name match (D2 -- no fuzzy matching) against an optional
  analyst-uploaded AbilityOne directory.
* **PL-impact context** (suitability criterion (a)(4)): side-by-side cited
  facts, deliberately with NO computed share/ratio (D3 -- the public
  denominator does not window-match this award; see ADR-017).

This is a **packet, not a score** (N1): no numeric/tiered vulnerability,
willingness, or fit output anywhere in this module.

Honesty invariants (ADR-017):

* **Band vocabulary.** Every rendered lead is prefixed with exactly one band:
  ``Observed`` (a directly-cited field value restated without interpretation),
  ``Lead-corroborated`` (an interpretation supported by >=2 independent
  Observed signals, both named in the text), ``Lead-single`` (rests on exactly
  1 Observed signal, named in the text), or ``Coincident`` (a name
  co-occurrence that suggests but cannot establish a connection -- the
  directory match lives here, analyst-confirm framing, never a relationship,
  partnership, capacity, or willingness claim).
* **No-citation-no-render**, enforced structurally: :class:`Lead` rejects an
  empty ``text``/``source_url``/``retrieved_at`` at construction, and every
  non-``Observed`` lead must also carry a non-empty ``basis`` naming its
  underlying Observed signal(s).
* **Code-not-text reasoning.** Extent-of-competition classification reasons
  off ``extent_competed_code`` (A/D/F = competed; B/C/G = not-competed /
  sole-source family) -- never the free-text description. An unrecognized
  code renders as "competition posture not classified here", never a guess.
* **Single-offer semantics are not conflated.** A single offer on a COMPETED
  award is the entrenchment/contestability signal. On a NOT-competed award
  the offers count is ENTAILED by the sole-source designation (the government
  solicits one vendor by definition), so it is never treated as an
  independent second signal: the sole-source lead stays ``Lead-single`` and
  names the offers count as consistent with -- not corroborating -- the
  designation. ``Lead-corroborated`` is reserved for genuinely independent
  signal pairs; no currently-derived pair qualifies.
* **FSRS absence is never "no teaming history".** Subaward (FSRS/FFATA)
  reporting has a real-world reporting threshold and is materially
  under-reported; zero or unpulled subaward records always render the
  standing absence caveat, never a positive "no subcontracting" claim.
* **Never a directive.** No "call this prime", "pursue X", or bid/no-bid
  recommendation anywhere -- every lead is framed as candidate evidence for
  analyst review; any outreach decision is the analyst's.
* **Markdown escaping.** Every API-derived string (recipient/subawardee
  names, descriptions, business categories, raw codes/dates) is escaped
  through this module's OWN local ``_md``/``_MD_ESCAPE`` (mirrors
  ``pl_match.py`` exactly) before it reaches ``Lead.text`` -- never imported
  from :mod:`tens_hq.opportunity_packet`, which imports THIS module to render
  it (importing back would be circular).

This module is pure (no Streamlit, no network, no case-store imports) and
deterministic: subaward/directory ordering never depends on dict iteration
order or the real clock.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .connectors import ContractFactsRecord, SubawardRecord, SubawardsResult

# FPDS extent-of-competition codes: A/D/F are the competed family; B/C/G are
# the not-competed / sole-source family. Reasoning is off the CODE only, never
# the free-text description (AGENTS #13-style code-not-text discipline).
_COMPETED_CODES = frozenset({"A", "D", "F"})
_NOT_COMPETED_CODES = frozenset({"B", "C", "G"})

_MAX_RENDERED_SUBAWARDEES = 10
_MAX_DESCRIPTION_CHARS = 280


class LeadBand(str, Enum):
    """The four evidentiary bands every rendered lead line is prefixed with."""

    OBSERVED = "OBSERVED"
    LEAD_CORROBORATED = "LEAD_CORROBORATED"
    LEAD_SINGLE = "LEAD_SINGLE"
    COINCIDENT = "COINCIDENT"


# Exact render prefixes (roadmap §4.4 band vocabulary).
_BAND_PREFIX = {
    LeadBand.OBSERVED: "Observed",
    LeadBand.LEAD_CORROBORATED: "Lead-corroborated",
    LeadBand.LEAD_SINGLE: "Lead-single",
    LeadBand.COINCIDENT: "Coincident",
}


@dataclass(frozen=True, slots=True)
class Lead:
    """One cited evidence line. Citation is enforced STRUCTURALLY at construction.

    ``basis`` names the underlying Observed signal(s) an interpretation rests
    on; it is required (non-empty) for every band except ``OBSERVED``, which
    IS the signal and needs no separate basis.
    """

    band: LeadBand
    text: str
    source_url: str
    retrieved_at: str
    basis: str = ""

    def __post_init__(self) -> None:
        if not str(self.text).strip():
            raise ValueError("a lead requires non-empty text")
        if not str(self.source_url).strip():
            raise ValueError("a lead requires a non-empty source_url (no-citation-no-render)")
        if not str(self.retrieved_at).strip():
            raise ValueError("a lead requires a non-empty retrieved_at (no-citation-no-render)")
        if self.band is not LeadBand.OBSERVED and not str(self.basis).strip():
            raise ValueError(
                "a non-Observed lead requires a non-empty basis naming its "
                "underlying observed signal(s)"
            )


@dataclass(frozen=True, slots=True)
class IncumbentLeads:
    """The full incumbent-and-teaming-leads assessment for one resolved award."""

    leads: tuple[Lead, ...]
    subawards_attached: bool
    subawards_record_count: int
    subawards_truncated: bool
    directory_attached: bool
    directory_match_count: int


# --- Markdown escape chokepoint -----------------------------------------------
#
# A LOCAL copy, exactly like pl_match.py:221-227. incumbent_leads.py cannot
# import ``_md`` from opportunity_packet: opportunity_packet imports THIS
# module to render its section, so that import would be circular. A line break
# is itself structural injection; flatten every line boundary to a space before
# escaping.

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


def _display_date(value: object) -> str:
    if value is None or not str(value).strip():
        return "Not reported"
    return _md(str(value).replace(" 00:00:00", ""))


def _money(value: float | None) -> str:
    if value is None:
        return "Not reported"
    return f"${value:,.2f}"


def _normalize_name(value: object) -> str:
    """Casefold + collapse whitespace, mirroring ``pl_match.normalize_service_type``.

    No fuzzy/substring matching (D2, house rule since R2b) -- this is used
    ONLY for an exact-string equality check.
    """

    if value is None:
        return ""
    return " ".join(str(value).casefold().split())


# --- Assessment ----------------------------------------------------------------


def _subaward_sort_key(record: SubawardRecord) -> tuple[bool, float, str, str]:
    """Deterministic order: amount desc, None-amount last, then name, then number."""

    amount_is_none = record.amount is None
    amount_desc = -(record.amount if record.amount is not None else 0.0)
    name = _normalize_name(record.recipient_name)
    number = _normalize_name(record.subaward_number)
    return (amount_is_none, amount_desc, name, number)


def _subawardee_text(record: SubawardRecord) -> str:
    name = _reported(record.recipient_name)
    amount = _money(record.amount)
    date = _display_date(record.action_date)
    number = _reported(record.subaward_number)
    # The description is upstream free text and the widest such field in the
    # section; clamp it before escaping so one verbose row cannot dominate the
    # rendered evidence.
    raw_description = record.description
    if raw_description is not None and len(raw_description) > _MAX_DESCRIPTION_CHARS:
        raw_description = raw_description[:_MAX_DESCRIPTION_CHARS] + "..."
    description = _reported(raw_description)
    return (
        f'Subawardee "{name}" -- {amount}, action date {date}, subaward '
        f"#{number}: {description}."
    )


def _extent_competed_lead(contract_facts: ContractFactsRecord) -> tuple[Lead, bool, bool, str]:
    """Return (Observed extent lead, competed, sole_source, normalized code)."""

    raw_code = contract_facts.extent_competed_code
    code = (raw_code or "").strip().upper()
    competed = code in _COMPETED_CODES
    sole_source = code in _NOT_COMPETED_CODES
    if not code:
        text = "Extent of competition not reported."
    elif competed:
        text = f'Extent of competition = "{_md(raw_code)}" -- competed.'
    elif sole_source:
        text = f'Extent of competition = "{_md(raw_code)}" -- not-competed (sole-source family).'
    else:
        text = f'Extent of competition code "{_md(raw_code)}" -- competition posture not classified here.'
    lead = Lead(LeadBand.OBSERVED, text, contract_facts.source_url, contract_facts.retrieved_at)
    return lead, competed, sole_source, code


def _competition_leads(contract_facts: ContractFactsRecord) -> list[Lead]:
    """Extent-competed + offers Observed leads, plus their interpretation leads.

    Single-offer semantics are never conflated (§3): a single offer on a
    COMPETED award is one signal. On a NOT-competed award the offers count is
    entailed by the sole-source designation, so it never corroborates it --
    the sole-source interpretation stays Lead-single and, when an offers
    count is reported, names it as consistent with (not independent of) the
    designation. Lead-corroborated requires genuinely independent signals.
    """

    extent_lead, competed, sole_source, code = _extent_competed_lead(contract_facts)
    offers = contract_facts.number_of_offers_received
    offers_text = (
        f"Number of offers received = {offers:,}."
        if offers is not None
        else "Number of offers received not reported."
    )
    offers_lead = Lead(
        LeadBand.OBSERVED, offers_text, contract_facts.source_url, contract_facts.retrieved_at
    )

    leads = [extent_lead, offers_lead]

    if sole_source:
        text = (
            f'Extent-competed code "{_md(code)}" places this award in the '
            "not-competed / sole-source family -- a public signal this work "
            "has not recently been tested by competition; this is not a "
            "claim about the incumbent's performance."
        )
        if offers is not None:
            text += (
                f" The reported offers count ({offers:,}) is consistent with, "
                "not independent of, this designation and adds no separate "
                "signal."
            )
        leads.append(
            Lead(
                LeadBand.LEAD_SINGLE,
                text,
                contract_facts.source_url,
                contract_facts.retrieved_at,
                basis=f'extent-competed code "{_md(code)}" (not-competed / sole-source family)',
            )
        )
    if competed and offers == 1:
        leads.append(
            Lead(
                LeadBand.LEAD_SINGLE,
                (
                    "Competed but drew a single offer -- a public signal the field "
                    "did not contest this work; what it means for the follow-on is "
                    "not determinable."
                ),
                contract_facts.source_url,
                contract_facts.retrieved_at,
                basis="number of offers received = 1 on a competed award",
            )
        )
    return leads


def _business_categories_lead(contract_facts: ContractFactsRecord) -> Lead:
    categories = contract_facts.recipient_business_categories
    if categories:
        text = (
            "Recipient business categories (registration-derived, self-reported "
            "via SAM registration; as of the latest transaction): "
            + "; ".join(_md(c) for c in categories)
            + "."
        )
    else:
        text = (
            "Recipient business categories not reported (registration-derived, "
            "self-reported via SAM registration)."
        )
    return Lead(LeadBand.OBSERVED, text, contract_facts.source_url, contract_facts.retrieved_at)


def _subaward_leads(subawards: SubawardsResult) -> list[Lead]:
    ordered = sorted(subawards.records, key=_subaward_sort_key)
    shown = ordered[:_MAX_RENDERED_SUBAWARDEES]
    more = len(ordered) - len(shown)

    count_text = f"{len(ordered)} subaward record(s) reported for this award (USAspending FSRS/FFATA data)"
    if subawards.truncated:
        count_text += "; more subaward records exist than were retrieved (first 100 shown)"
    if more > 0:
        count_text += f"; showing the top {len(shown)} by reported amount, {more} more not shown here"
    count_text += "."

    leads = [Lead(LeadBand.OBSERVED, count_text, subawards.source_url, subawards.retrieved_at)]
    for record in shown:
        leads.append(
            Lead(
                LeadBand.OBSERVED,
                _subawardee_text(record),
                subawards.source_url,
                subawards.retrieved_at,
            )
        )
    return leads


def _directory_leads(
    subawards: SubawardsResult, directory_agency_names: Sequence[str]
) -> tuple[list[Lead], int]:
    directory_norms = {_normalize_name(name) for name in directory_agency_names}
    directory_norms.discard("")
    leads: list[Lead] = []
    seen: set[str] = set()
    for record in sorted(subawards.records, key=_subaward_sort_key):
        norm = _normalize_name(record.recipient_name)
        if not norm or norm in seen or norm not in directory_norms:
            continue
        seen.add(norm)
        leads.append(
            Lead(
                LeadBand.COINCIDENT,
                (
                    f'Subawardee "{_md(record.recipient_name)}" name-matches an entry in '
                    "the uploaded AbilityOne directory (normalized casefold + trim + "
                    "collapsed-whitespace exact match; no fuzzy matching). This is a "
                    "name COINCIDENCE, not a confirmed relationship, partnership, "
                    "capacity, or willingness to team -- candidate teaming evidence "
                    "for analyst review; any outreach decision is the analyst's."
                ),
                subawards.source_url,
                subawards.retrieved_at,
                basis=(
                    f'subawardee recipient_name "{_md(record.recipient_name)}" normalized-exact-'
                    "matches an uploaded directory agency_name"
                ),
            )
        )
    return leads, len(leads)


def derive_incumbent_leads(
    contract_facts: ContractFactsRecord,
    *,
    subawards: SubawardsResult | None = None,
    directory_agency_names: Sequence[str] | None = None,
) -> IncumbentLeads:
    """Derive the full incumbent-and-teaming-leads assessment (pure).

    ``subawards=None`` means "not yet pulled" (D4: the section still renders
    -- competition leads need no extra pull -- but with the FSRS absence
    caveat standing in for teaming evidence). ``directory_agency_names=None``
    means "no directory uploaded"; an empty sequence is a directory that
    parsed to zero usable names, which behaves identically to "no match" once
    combined with any subawards.
    """

    leads: list[Lead] = []
    leads.extend(_competition_leads(contract_facts))
    leads.append(_business_categories_lead(contract_facts))

    subawards_attached = subawards is not None
    record_count = len(subawards.records) if subawards is not None else 0
    subawards_truncated = bool(subawards.truncated) if subawards is not None else False

    directory_match_count = 0
    if subawards is not None and subawards.records:
        leads.extend(_subaward_leads(subawards))
        if directory_agency_names is not None:
            dir_leads, directory_match_count = _directory_leads(subawards, directory_agency_names)
            leads.extend(dir_leads)

    return IncumbentLeads(
        leads=tuple(leads),
        subawards_attached=subawards_attached,
        subawards_record_count=record_count,
        subawards_truncated=subawards_truncated,
        directory_attached=directory_agency_names is not None,
        directory_match_count=directory_match_count,
    )


# --- Rendering -------------------------------------------------------------
#
# Caveat-first, exactly like the rest of the packet: the preamble and the
# standing why-Unknown line always precede any lead, so no lead can be read
# in isolation as a determination.

INCUMBENT_LEADS_HEADER = "## Incumbent & teaming leads / PL-impact context (cited)"

INCUMBENT_LEADS_PREAMBLE = (
    "The recipient shown here is the current contractor on this award; "
    "whether it bids the follow-on is unknown. This section is candidate "
    "teaming evidence for analyst review -- any outreach decision is the "
    "analyst's, never an automated determination."
)

INCUMBENT_LEADS_WHY_UNKNOWN = (
    "Why the incumbent wins or struggles (past-performance ratings, customer "
    "satisfaction, pricing, staffing) is not public data and is not "
    "determinable here."
)

SUBAWARDS_ABSENCE_CAVEAT = (
    "No subaward records were retrieved for this award. This is NOT evidence "
    "the contractor does not subcontract or team -- subaward reporting "
    "(FSRS) applies only above a reporting threshold and is known to be "
    "incomplete."
)

DIRECTORY_NO_MATCH_NOTE = (
    "An AbilityOne directory was provided, but no subawardee name in the "
    "available subaward evidence exact-matched an entry in it (normalized "
    "casefold/whitespace-collapsed exact match only; no fuzzy matching). "
    "This is NOT evidence of no NPA teaming on this award -- the comparison "
    "set is limited to whatever subaward records were retrieved above."
)

PL_IMPACT_HEADER = "### PL-impact context (suitability criterion (a)(4))"

PL_IMPACT_LABEL = (
    "Federal award data only; no share is computed here because the public "
    "denominator (trailing-12-month recipient totals) does not match this "
    "award's period; the Commission's (a)(4) impact test uses total sales "
    "including commercial business, which is not public."
)

_ASSURANCE_API_RETRIEVED = "API_RETRIEVED"
_ASSURANCE_USER_ATTESTED = "USER_ATTESTED"


def _render_group(lines: list[str], group_leads: list[Lead], *, assurance: str) -> None:
    for lead in group_leads:
        prefix = _BAND_PREFIX[lead.band]
        bullet = f"- {prefix}: {lead.text}"
        if lead.band is not LeadBand.OBSERVED:
            bullet += f" (basis: {lead.basis})"
        lines.append(bullet)
    first = group_leads[0]
    lines.append(f"- Source: {_md(first.source_url)}")
    lines.append(f"- Retrieved at: {_md(first.retrieved_at)}")
    if assurance == _ASSURANCE_USER_ATTESTED:
        # The cited URL covers the subawardee fact; the attested component is
        # the analyst-uploaded directory, so the footer names it explicitly.
        lines.append("- Directory: analyst-uploaded (provenance unattested)")
    lines.append(f"- Provenance assurance: {assurance}")
    lines.append("")


def _pl_impact_lines(contract_facts: ContractFactsRecord) -> list[str]:
    categories = contract_facts.recipient_business_categories
    categories_text = "; ".join(_md(c) for c in categories) if categories else "Not reported"
    lines = [
        PL_IMPACT_HEADER,
        "",
        f"- {PL_IMPACT_LABEL}",
        "",
        f"- Obligated to date (this award): {_money(contract_facts.total_obligation)}",
        f"- Period of performance: {_display_date(contract_facts.period_start_date)} to "
        f"{_display_date(contract_facts.period_end_date)} "
        f"(potential end {_display_date(contract_facts.period_potential_end_date)})",
        f"- Recipient business categories (registration-derived, self-reported "
        f"via SAM registration; not a size determination): {categories_text}",
        f"- Source: {_md(contract_facts.source_url)}",
        f"- Retrieved at: {_md(contract_facts.retrieved_at)}",
        "",
    ]
    return lines


def incumbent_leads_lines(assessment: IncumbentLeads, *, contract_facts: ContractFactsRecord) -> list[str]:
    """Render the section as caveat-first Markdown lines (pure).

    Leads are rendered in two evidentiary groups -- (1) competition/
    registration facts sourced from the attached Contract Facts and (2)
    attached subaward evidence -- each closed with its own
    Source/Retrieved-at/Assurance footer, followed by any
    directory cross-reference (Assurance USER_ATTESTED, since the uploaded
    directory is an analyst attestation even though the matched subawardee
    fact itself is API-retrieved) and the PL-impact context block (D3).
    """

    lines: list[str] = [
        INCUMBENT_LEADS_HEADER,
        "",
        f"- {INCUMBENT_LEADS_PREAMBLE}",
        f"- {INCUMBENT_LEADS_WHY_UNKNOWN}",
        "",
    ]

    non_directory = [lead for lead in assessment.leads if lead.band is not LeadBand.COINCIDENT]
    directory_leads = [lead for lead in assessment.leads if lead.band is LeadBand.COINCIDENT]

    for _source_key, group in itertools.groupby(
        non_directory, key=lambda lead: (lead.source_url, lead.retrieved_at)
    ):
        group_leads = list(group)
        assurance = _ASSURANCE_API_RETRIEVED
        if contract_facts.synthetic_example:
            # ADR-025: reuse the manifest's one canonical synthetic assurance.
            # Deferred to avoid packet_export -> opportunity_packet -> this
            # module forming an import cycle during module initialization.
            from .packet_export import _ASSURANCE_SYNTHETIC_EXAMPLE

            assurance = _ASSURANCE_SYNTHETIC_EXAMPLE
        _render_group(lines, group_leads, assurance=assurance)

    if not assessment.subawards_attached or assessment.subawards_record_count == 0:
        lines.append(f"- {SUBAWARDS_ABSENCE_CAVEAT}")
        lines.append("")

    if directory_leads:
        lines.append("### AbilityOne directory cross-reference")
        lines.append("")
        _render_group(lines, directory_leads, assurance=_ASSURANCE_USER_ATTESTED)
    elif assessment.directory_attached:
        lines.append(f"- {DIRECTORY_NO_MATCH_NOTE}")
        lines.append("")

    lines.extend(_pl_impact_lines(contract_facts))
    return lines


__all__ = [
    "DIRECTORY_NO_MATCH_NOTE",
    "INCUMBENT_LEADS_HEADER",
    "INCUMBENT_LEADS_PREAMBLE",
    "INCUMBENT_LEADS_WHY_UNKNOWN",
    "PL_IMPACT_HEADER",
    "PL_IMPACT_LABEL",
    "SUBAWARDS_ABSENCE_CAVEAT",
    "IncumbentLeads",
    "Lead",
    "LeadBand",
    "derive_incumbent_leads",
    "incumbent_leads_lines",
]
