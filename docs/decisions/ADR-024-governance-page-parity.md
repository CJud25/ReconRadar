# ADR-024: Governance-page Decision boundaries and inventory framing describe only shipped capabilities

## Status

Accepted for the product-legibility one-shot

## Date

2026-07-23

## Context

ADR-016 (2026-07-20) deleted the manufactured-score capture board and its
engine (`feasibility.py`, `metrics.opportunity_readiness`) and corrected
"display vocabulary that promised the deleted engine" across the README,
architecture doc, and "governance surfaces in `pages.py`" — but that
correction was partial. `render_governance`'s "Decision boundaries" block
(`pages.py:115-123`) still read:

- "Site views are internal planning indicators."
- "Organization scenarios use summed hours, but remain synthetic."
- "Eligibility/document statuses activate only after the synthetic
  start-stage gate."
- "Source scores use mature cohorts and small-sample shrinkage."

A tree grep confirms no site-view, source-score, organization-scenario, or
shrinkage logic exists anywhere in `src`. This is the review report's
highest-severity finding (§5.1): the one page whose entire job is to earn a
compliance reader's trust described a *more invasive* product than the one
shipped — a "Source scores" boundary sitting two lines above the page's own
no-score thesis statement. Nothing about this is a new deletion; it is the
same ADR-016 vocabulary correction, finally reaching the last surface it
missed.

The "Data inventory" table (person-shaped synthetic frames: contacts,
outreach, applicants, stage history, etc.) sits directly under the same
header. Report §12.5 floats dropping those frames outright, but
`validation.py:26-99` and `tests/test_synthetic.py` pin their exact row
counts and referential integrity, and `scripts/validate_demo_data.py`
depends on them. Removing them is a large, high-risk change with no
load-bearing defect to justify it — the frames are not wrong, the *silence*
about what they are is (an unlabeled "1,500 applicants" row beside a
no-PII claim reads, to a skimming compliance reviewer, like it might be
live data).

## Decision

Content-only change to `render_governance` (`pages.py`), no frame removal:

1. **Rewrite the "Decision boundaries" bullets** to mirror
   `docs/ARCHITECTURE.md`'s "Trust and storage boundaries" list and the
   packet's actual behavior — every bullet now names a capability that
   ships: the packet is cited/non-numeric/never a score; live sources pull
   only on explicit analyst action and fail loud with source URL +
   retrieval time + assurance label; public workbook rows and synthetic
   data never join; the case ledger is local pilot infrastructure, not an
   auth/encryption/backup/multi-user boundary; analyst-typed and
   analyst-uploaded values are attestations, not independently verified
   evidence. The four capability-that-does-not-exist bullets (site views,
   organization scenarios, start-stage gate, source scores/shrinkage) are
   removed, not reworded — there is no shipped capability to correctly
   describe in their place.
2. **Add one caption under "Data inventory"** naming what the table is:
   deterministic synthetic validation fixtures, none real people or
   organizations, none joined to public evidence. The frames themselves are
   retained exactly as-is (Finding drift #4 / this ADR's own scope: no row
   removed, no count changed).
3. **"Deliberately excluded" block is left as-is.** Its items ("Automated
   email sending", "Person-level disability or worth scoring", "Final
   bid/no-bid automation") are honest as *exclusions* — a list of things the
   app does NOT do — and none of them claim a shipped feature.

## Alternatives considered

- **Drop the person-shaped synthetic frames from the inventory (report
  §12.5):** rejected — no test or code defect requires it, `validate_demo_data.py`
  and `test_synthetic.py` depend on the exact counts, and the actual defect
  (unlabeled inventory next to a no-PII claim) is fully addressed by naming
  the frames as inert fixtures instead of deleting them.
- **Soften the boundary bullets instead of removing the four
  capability-that-doesn't-exist ones:** rejected — a softened
  "Source scores use conservative assumptions" still implies a scoring
  engine exists; the honest fix is removal, not a gentler wrong claim.
- **Rewrite `render_governance` wholesale (new layout, new sections):**
  rejected as unnecessarily large for a content-only defect; the page
  structure (inventory / exclusions / boundaries / value statement /
  primary-source framing) is otherwise sound and untouched.

## Consequences

- The governance page's Decision-boundary bullets now correspond 1:1 to
  capabilities that ship, closing the ADR-016 vocabulary-correction gap on
  its last remaining surface.
- The person-shaped synthetic frames (contacts, outreach, applicants,
  stage history, etc.) are **retained**, not deleted — they remain
  load-bearing for `validation.py`'s referential-integrity checks and
  `tests/test_synthetic.py`'s row-count pins — but are now explicitly
  labeled inert synthetic validation fixtures rather than left to speak for
  themselves.
- New guard test `test_governance_page_describes_only_shipped_capabilities`
  (`tests/test_app_runtime.py`) asserts the six forbidden phrases ("site
  views", "source scores", "organization scenarios", "small-sample
  shrinkage", "start-stage gate", "summed hours") are absent from the
  rendered governance markdown and that the on-thesis "never a feasibility
  score" / "bid/no-bid" bullet is present — locking this correction against
  regression.
