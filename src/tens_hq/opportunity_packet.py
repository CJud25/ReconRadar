"""The cited Opportunity Packet surface (A1 walking skeleton).

An analyst pastes a contract identifier (PIID) and a place (county + state); the
packet renders a one-page, fully-cited evidence sheet with up to eleven sections:

0. **Origin -- Radar handoff** -- optional; appended only when an uploaded,
   PIID-matched Radar handoff snapshot is attached (D3/D9). Renders FIRST,
   before the Eligibility Gate, as a caveat-first block of labeled claims from
   that snapshot -- never packet evidence, and never fed into any assessment
   (see :mod:`tens_hq.radar_handoff`, ADR-019).
1. **Eligibility gate** -- optional; the cited analyst-entered set-aside status
   and structural rule, presented before all other evidence without making an
   eligibility or pursuit determination (ADR-003/ADR-013).
2. **Contract Facts** -- only the pasted identifiers, clearly labeled
   *analyst-entered* and not independently verified.
3. **Capture window** -- optional; appended only when live Contract Facts are
   attached. Estimates a BAND for the likely follow-on solicitation date and
   the R2a Procurement-List-addition start-by date from the contract's
   potential end date, anchored to the solicitation clock (not the contract
   end date), with owner-attested, effective-dated lead-time bands (see
   :mod:`tens_hq.capture_window`, ADR-015/ADR-020). Never a single-point
   runway or a determination.
4. **Incumbent & teaming leads / PL-impact context** -- optional; appended only
   when live Contract Facts are attached. Cited competition-posture and
   registration leads, plus optional subaward teaming-posture evidence and an
   AbilityOne-directory name cross-reference (Coincident band, analyst-confirm
   only), and PL-impact side-by-side facts with deliberately no computed share
   (see :mod:`tens_hq.incumbent_leads`, ADR-017). A packet, not a score.
5. **Staffing what-if (ODLH planning indicator)** -- optional; appended only
   when the analyst enters a staffing baseline (independent of live Contract
   Facts). Computes the marginal effect of a contract staffing scenario on
   the agency-wide ODLH ratio as a labeled planning indicator, never an
   official ODLH compliance determination, framed as evidence toward
   suitability criterion (a)(2) only (see :mod:`tens_hq.staffing_whatif`,
   ADR-020/ADR-021).
6. **Geography context** -- one ACS county figure (disability characteristics),
   cited with its source URL, retrieval date, and survey vintage, and labeled as
   *context, not candidate supply* (N2/N4).
7. **Procurement List cross-reference (R2b)** -- optional; appended only when the
   analyst cross-references the worksite against an uploaded PL Services workbook
   (see :mod:`tens_hq.pl_match`). Rendered caveat-first: discovery evidence only,
   never a score, a route, a convertibility claim, or a claim of which agency
   holds a line (ADR-012).
8. **Procurement List activity (Federal Register)** -- optional; appended only
   when the analyst pulls the AbilityOne Commission's own Federal Register
   notice stream (page 1, newest-first, an optional free-text search term).
   Rendered caveat-first: notices are listed, never interpreted -- no
   add-vs-delete classification beyond what a title states, no relevance
   claim, and the Commission's full notice stream (which can include non-PL
   notices) is never silently filtered (see :mod:`tens_hq.pl_activity`,
   ADR-023). A cited national notice list, never a claim about this contract.
9. **R2a determination-support map** -- ALWAYS rendered, last (it synthesizes
   the whole packet). Routes whatever evidence is currently attached above
   (Geography, Staffing what-if, Capture Window, Incumbent leads) onto the
   four suitability criteria of 41 CFR 51-2.4(a), with an honest "no packet
   evidence speaks to this criterion yet" line for any criterion nothing is
   attached to. Structural citation routing only -- never an assessment, a
   met/unmet marker, or a score (see :mod:`tens_hq.r2a_map`, ADR-022).

Invariants this surface must hold:

* **N1 -- packet, not score.** There is no feasibility/PWin/readiness score,
  ranking, or bid/no-bid recommendation anywhere in the output.
* **N3 -- provenance is the promise.** The geography figure never renders
  without its source, retrieval date, and vintage.

The builder is a pure function so it is testable directly and offline; the
Streamlit page reuses it and only performs the (network) ACS pull on an explicit
analyst action.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from .capture_window import assess_capture_window, capture_window_lines
from .connectors import ContractFactsRecord, GeographyRecord, PLNoticesResult, SubawardsResult
from .eligibility_gate import EligibilityGate, assess_eligibility, eligibility_gate_lines
from .incumbent_leads import derive_incumbent_leads, incumbent_leads_lines
from .pl_activity import pl_activity_lines
from .pl_match import PLMatchResult, pl_service_match_lines
from .r2a_map import derive_r2a_map, r2a_map_lines
from .radar_handoff import RadarHandoff, radar_handoff_lines
from .staffing_whatif import StaffingWhatIfResult, staffing_whatif_lines

# The geography panel's standing disclaimer (N2/N4): a county population
# statistic is context, never a claim about who could be hired or partnered.
GEOGRAPHY_CONTEXT_DISCLAIMER = (
    "Geographic context only -- a county-level ACS population statistic. "
    "This is NOT a candidate-supply, hiring-pool, capacity, eligibility, or "
    "partnership claim, and it is not evidence of available workers for this "
    "contract."
)

# The packet's standing framing (N1): a cited evidence sheet, not a decision.
PACKET_FRAMING = (
    "This is a cited evidence packet for analyst review. It contains no numeric "
    "rating, no ranking, and no pursue-or-decline recommendation."
)


# Values here feed single-line Markdown bullets rendered by ``st.markdown`` at
# the UI boundary. Flatten every line boundary to a space first because a line
# break is structural injection; then escape narrowly so ordinary federal codes
# remain readable while link/code/emphasis syntax cannot be injected.
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


def _safe_date(value: object) -> str:
    if not value:
        return "Not reported"
    return _md(str(value).replace(" 00:00:00", ""))


def _money(value: float | None) -> str:
    if value is None:
        return "Not reported"
    return f"${value:,.2f}"


def contract_facts_lines(piid: str, county: str, state: str) -> list[str]:
    """The analyst-entered Contract Facts block (no verification claim)."""

    piid_text = _md((piid or "").strip() or "Not supplied")
    county_text = _md((county or "").strip() or "Not supplied")
    state_text = _md((state or "").strip().upper() or "Not supplied")
    return [
        "## Contract Facts (analyst-entered)",
        "",
        f"- PIID: {piid_text}",
        f"- Place of performance: {county_text}, {state_text}",
        "- Source: analyst paste. These identifiers are analyst-entered and have "
        "not been independently verified against SAM.gov or USAspending.",
    ]


def live_contract_facts_lines(record: ContractFactsRecord) -> list[str]:
    """Render cited, single-award USAspending facts without scoring them."""

    award_type = (
        f"{_reported(record.award_type_code)} — "
        f"{_reported(record.award_type_description)}"
    )
    recipient = (
        f"{_reported(record.recipient_name)}; UEI {_reported(record.recipient_uei)}"
    )
    set_aside = (
        _md(record.set_aside_code)
        if record.set_aside_code is not None and str(record.set_aside_code).strip()
        else "None reported (null)"
    )
    if record.set_aside_description:
        set_aside = f"{set_aside} — {_md(record.set_aside_description)}"

    if record.extent_competed_code:
        extent = (
            f"{_md(record.extent_competed_code)} — "
            f"{_reported(record.extent_competed_description)} "
            f"(FPDS code {_md(record.extent_competed_code)})."
        )
    else:
        extent = "Not reported."

    offers = (
        "Not reported"
        if record.number_of_offers_received is None
        else f"{record.number_of_offers_received:,}"
    )
    pop_fields = (
        record.pop_city_name,
        record.pop_county_name,
        record.pop_state_code,
        record.pop_country_code,
    )
    if all(value is None for value in pop_fields):
        place_lines = ["- Place of performance: Not reported"]
    else:
        place_line = (
            f"- Place of performance — city: {_reported(record.pop_city_name)} · "
            f"county: {_reported(record.pop_county_name)} · "
            f"state: {_reported(record.pop_state_code)}"
        )
        country = record.pop_country_code
        if country is not None and country.strip().upper() != "USA":
            place_line += f" · country: {_reported(country)}"
        place_lines = [
            place_line,
            "- The COUNTY (not the city) keys the ACS Geography section; the CITY is the "
            "R2b worksite key. A base-named city can sit in a county whose name never "
            "appears on the award.",
        ]
    # ADR-025: the bundled offline SYNTHETIC-example record must never render
    # under the live heading/provenance -- both are switched together so the
    # body can never half-claim a live retrieval.
    if record.synthetic_example:
        heading = "## Contract Facts (SYNTHETIC example — offline, not a live retrieval)"
        provenance_line = (
            "- Provenance: bundled SYNTHETIC example, offline — NOT a live "
            "retrieval and does not carry an API_RETRIEVED assurance label."
        )
    else:
        heading = "## Contract Facts (live — USAspending, cited)"
        provenance_line = (
            "- Provenance: LIVE USAspending API retrieval (Assurance API_RETRIEVED). "
            "Distinct from the analyst-entered identifiers below."
        )
    lines = [
        heading,
        "",
        f"- PIID: {_reported(record.piid)}",
        f"- Award type: {award_type}",
        f"- Date signed: {_safe_date(record.date_signed)}",
        f"- Obligated to date: {_money(record.total_obligation)}",
        f"- Ceiling (base + all options): {_money(record.base_and_all_options)} — "
        "this is the potential value with all options, NOT money obligated.",
        f"- Period of performance start: {_safe_date(record.period_start_date)}",
        f"- Current period end: {_safe_date(record.period_end_date)}",
        f"- Potential period end: {_safe_date(record.period_potential_end_date)}",
        f"- Awarding agency: {_reported(record.toptier_agency_name)}",
        f"- Awarding sub-agency: {_reported(record.subagency_name)}",
        f"- Recipient: {recipient}",
        f"- Set-aside (FPDS type_set_aside): {set_aside}",
        "- This same retrieved set-aside value drives the Eligibility Gate above.",
        f"- Extent of competition: {extent}",
        f"- Number of offers received: {offers}",
        f"- NAICS: {_reported(record.naics_code)} — "
        f"{_reported(record.naics_description)}",
        f"- PSC: {_reported(record.psc_code)} — "
        f"{_reported(record.psc_description)}",
        f"- Award description (FPDS free text, as reported): {_reported(record.description)}",
        *place_lines,
        "",
        f"- Source: {_md(record.source_url)}",
        f"- Retrieved at: {_md(record.retrieved_at)}",
        provenance_line,
    ]
    return lines


def geography_lines(geography: GeographyRecord | None) -> list[str]:
    """The cited ACS geography context panel (N2/N3/N4)."""

    lines = ["## Geography context (ACS)", ""]
    if geography is None:
        lines.extend(
            [
                "- Not yet retrieved. Use the live ACS pull to attach county-level "
                "disability context for this place.",
                f"- {GEOGRAPHY_CONTEXT_DISCLAIMER}",
            ]
        )
        return lines
    percent = f"{geography.disability_percent:.1f}%"
    # ACS-derived strings are upstream values and go through the same
    # flatten-then-escape _md as the live contract facts -- same forgery class,
    # same discipline. The numeric fields are typed by the parser and formatted
    # here, so they interpolate directly.
    lines.extend(
        [
            f"- County: {_reported(geography.county_name)} "
            f"(state FIPS {_md(geography.state_fips)}, county FIPS {_md(geography.county_fips)})",
            f"- People with a disability (civilian noninstitutionalized): "
            f"{geography.with_disability:,} of {geography.total_population:,} ({percent})",
            "",
            f"- Source: {_md(geography.source_url)}",
            f"- Retrieved at: {_md(geography.retrieved_at)}",
            f"- Survey / vintage: {_md(geography.acs_survey)}; vintage {_md(geography.acs_vintage_year)}",
            "",
            f"- {GEOGRAPHY_CONTEXT_DISCLAIMER}",
        ]
    )
    return lines


def build_opportunity_packet_markdown(
    *,
    piid: str,
    county: str,
    state: str,
    eligibility: EligibilityGate | None = None,
    geography: GeographyRecord | None = None,
    pl_matches: PLMatchResult | None = None,
    pl_notices: PLNoticesResult | None = None,
    contract_facts: ContractFactsRecord | None = None,
    subawards: SubawardsResult | None = None,
    directory_agency_names: Sequence[str] | None = None,
    radar_handoff: RadarHandoff | None = None,
    staffing: StaffingWhatIfResult | None = None,
    as_of: datetime | None = None,
) -> str:
    """Render the one-page cited packet as Markdown (pure, offline-safe).

    When ``radar_handoff`` is supplied, it MUST already be the PIID-gated
    value (D9): the caller (``bd_page``) compares the handoff's PIID against
    the packet's current PIID input and passes ``None`` on a mismatch, so
    this function never re-derives that gate. The caveat-first Origin section
    (:mod:`tens_hq.radar_handoff`, D3) then renders FIRST, before the
    Eligibility Gate; it never feeds ``eligibility`` or any other assessment
    (§1.1), and ``live_facts_attached=contract_facts is not None`` is passed
    through so its standing "live supersedes" line only appears once live
    Contract Facts are actually attached.
    When ``eligibility`` is supplied, its caveat-first gate renders before
    Contract Facts. When ``contract_facts`` is supplied, a caveat-first
    Capture Window band (estimated solicitation + R2a start-by, roadmap
    SS4.2) is computed from its ``period_potential_end_date`` and ``as_of``
    and rendered right after Contract Facts -- an unparseable/missing date
    renders an honest "unknown" line rather than being omitted or fabricated.
    Also when ``contract_facts`` is supplied, the caveat-first Incumbent &
    teaming leads / PL-impact context section (A5, :mod:`tens_hq.incumbent_leads`)
    is computed and rendered right after the Capture Window; ``subawards`` and
    ``directory_agency_names`` are optional enrichment (D4) -- competition and
    registration leads render with contract_facts alone, and the FSRS absence
    caveat renders whenever no subawards are attached or none were reported.
    When ``staffing`` is supplied (A6, the caller ALREADY assessed it via
    :func:`tens_hq.staffing_whatif.assess_staffing_whatif` -- this builder
    never computes it itself), a caveat-first Staffing what-if section
    renders right after Incumbent leads and before Geography, independent of
    ``contract_facts``. ``staffing`` is only ever non-``None`` when the
    analyst entered a baseline; a ``CANNOT_COMPUTE`` result still renders
    (an honest partial-entry message), so the section's presence tracks
    "was a baseline entered," not "did it validate."
    When ``pl_matches`` is supplied (the analyst ran an R2b cross-reference
    against an uploaded PL Services workbook), a caveat-first Procurement List
    cross-reference section is appended. When it is ``None`` the section is
    omitted entirely, so the section only ever appears for a real cross-reference.
    When ``pl_notices`` is supplied (A4, the analyst pulled the AbilityOne
    Commission's own Federal Register notice stream via
    :func:`tens_hq.connectors.federal_register.pull_pl_notices`), a
    caveat-first Procurement List activity section (:mod:`tens_hq.pl_activity`)
    is appended right after R2b and before the always-last R2a map. When it is
    ``None`` the section is omitted entirely -- a real, empty pull (0 notices)
    still renders, since the analyst DID pull it.
    """

    effective_as_of = as_of or datetime.now(timezone.utc)
    stamp = effective_as_of.isoformat()
    lines: list[str] = [
        "# Opportunity Packet",
        "",
        f"- As of: {stamp}",
        f"- {PACKET_FRAMING}",
        "",
    ]
    if radar_handoff is not None:
        lines.extend(
            radar_handoff_lines(radar_handoff, live_facts_attached=contract_facts is not None)
        )
        lines.append("")
    gate = eligibility
    gate_source_lines = None
    if contract_facts is not None:
        # A live retrieved value supersedes the analyst-typed value. In
        # particular, null remains UNKNOWN rather than becoming unrestricted.
        gate = assess_eligibility(contract_facts.set_aside_code)
        code = (contract_facts.set_aside_code or "").strip()
        if code:
            gate_source_lines = (
                "Source: set-aside code retrieved LIVE from USAspending "
                "(FPDS latest transaction, type_set_aside); not analyst-entered.",
                f"Retrieved from: {contract_facts.source_url}",
                f"Retrieved at: {contract_facts.retrieved_at}",
            )
        else:
            gate_source_lines = (
                "Source: USAspending returned no set-aside on the latest FPDS "
                "transaction (type_set_aside was null). Null = not reported, which is "
                "why this reads UNKNOWN and NOT unrestricted.",
                f"Retrieved from: {contract_facts.source_url}",
                f"Retrieved at: {contract_facts.retrieved_at}",
            )
    if gate is not None:
        lines.extend(eligibility_gate_lines(gate, source_lines=gate_source_lines))
        lines.append("")
    if contract_facts is not None:
        lines.extend(live_contract_facts_lines(contract_facts))
        lines.append("")
    lines.extend(contract_facts_lines(piid, county, state))
    lines.append("")
    # Hoisted (T6, R2a) so the final determination-support map can pass the
    # typed objects through even when contract_facts is absent -- both stay
    # None in that case, and derive_r2a_map renders the honest per-criterion
    # absence line for whatever wasn't attached.
    capture_window = None
    incumbent_leads = None
    if contract_facts is not None:
        capture_window = assess_capture_window(
            contract_facts.period_potential_end_date, effective_as_of.date()
        )
        lines.extend(capture_window_lines(capture_window))
        lines.append("")
        incumbent_leads = derive_incumbent_leads(
            contract_facts,
            subawards=subawards,
            directory_agency_names=directory_agency_names,
        )
        lines.extend(incumbent_leads_lines(incumbent_leads, contract_facts=contract_facts))
        lines.append("")
    if staffing is not None:
        lines.extend(staffing_whatif_lines(staffing))
        lines.append("")
    lines.extend(geography_lines(geography))
    lines.append("")
    if pl_matches is not None:
        lines.extend(pl_service_match_lines(pl_matches))
        lines.append("")
    if pl_notices is not None:
        lines.extend(pl_activity_lines(pl_notices))
        lines.append("")
    # ALWAYS rendered, last: the R2a determination-support map synthesizes
    # the whole packet by routing whatever evidence is attached above onto
    # the four suitability criteria (ADR-022). It computes nothing new, so
    # it never needs its own presence gate the way every other optional
    # section above does -- it simply reflects, honestly, whatever state
    # this render is already in.
    r2a_map = derive_r2a_map(
        capture_window=capture_window,
        incumbent_leads=incumbent_leads,
        geography=geography,
        staffing=staffing,
    )
    lines.extend(r2a_map_lines(r2a_map))
    return "\n".join(lines) + "\n"


__all__ = [
    "GEOGRAPHY_CONTEXT_DISCLAIMER",
    "PACKET_FRAMING",
    "ContractFactsRecord",
    "build_opportunity_packet_markdown",
    "contract_facts_lines",
    "geography_lines",
    "live_contract_facts_lines",
]
