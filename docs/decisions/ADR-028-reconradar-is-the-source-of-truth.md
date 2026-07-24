# ADR-028: ReconRadar is the development source of truth; ReconOps is a frozen private archive

## Status

Accepted

## Date

2026-07-24

## Context

Until now, `CJud25/ReconRadar` (public) has been a fresh-history,
packet-only MIRROR of the private `CJud25/ReconOps`: development happened
in ReconOps, and a manual allowlist overlay periodically copied an
allowed subset of files across into ReconRadar's independent history.

That process produced a recurring class of drift defects, not a one-off
mistake:

- **An ADR-number collision.** ReconOps's EDGE gate-decision-log slice was
  numbered ADR-024 on the private side. ReconRadar had already shipped its
  own, unrelated ADR-024 (governance-page-parity) by the time that slice
  was cut, because the two repos' ADR sequences were never a single
  authority -- they only happened to agree by convention, until they
  didn't.
- **A stale-clone near-revert.** An overlay run from a local ReconOps
  clone that was not freshly pulled nearly reverted public-only fixes that
  existed in ReconRadar but not yet in the stale clone -- the overlay had
  no way to distinguish "ReconOps doesn't have this yet" from "ReconOps
  deliberately doesn't have this."
- **Eight public-only files a naive overlay would have reverted.**
  ReconRadar has accumulated its own fixes and files that never existed in
  ReconOps (or existed differently there); an allowlist overlay run
  carelessly would silently discard them, because the overlay's mental
  model was "ReconOps is truth," which stopped being accurate the moment
  ReconRadar started diverging.

The root cause in all three is the same: **two independently-edited
repositories, kept in sync by a human running a manual, allowlist-shaped
overlay, with no single source of truth.** That shape does not converge;
it drifts, and each drift defect was caught only by a subsequent manual
audit, not by anything structural.

ReconOps's own git history additionally contains material that must never
be made public: a pre-scrub employer name, session URLs, and machine paths
from early development, predating the security-sweep discipline this
project now follows. That history cannot be cleaned in place without
rewriting it, and even a rewritten ReconOps would still be the repository
that once held that material. ReconRadar, by contrast, was cut with fresh
history from the start and has independently passed multiple security/PII
sweeps as a public repository.

## Decision

1. **ReconRadar becomes the development source of truth for the
   Opportunity Packet and public-evidence case tracker.** Feature work,
   ADRs, and doc changes happen here first, in the open, reviewed the same
   way any public open-source change is: a branch, a gate-green PR, a
   merge. There is no longer an "original" repository this one mirrors.
2. **The manual mirror/overlay process is retired.** No more allowlist
   overlay runs, no more stale-clone risk, no more silent-revert risk --
   because there is nothing left to reconcile between two independently
   edited trees.
3. **ReconOps is frozen as a private archive.** It keeps its own commit
   history exactly as it is (including the material named above, which is
   precisely why it stays private) and is never made public and never
   merged back into ReconRadar. It is read-only from this point forward
   except for archival purposes.
4. **Dev-process artifacts are gitignored, not deleted or ported.**
   `CLAUDE.md`, `AGENTS.md`, `docs/handoffs/`, and `docs/PRODUCT_BLUEPRINT.md`
   are internal working documents from building this repo, not
   user-facing documentation; they are excluded from version control
   here (`.gitignore`) rather than cut down to a publishable subset,
   so a future session can keep using them locally without a repeat risk
   of one landing in a commit.
5. **The App B / recruiting legacy stays in the archive.** ADRs 002, 004,
   005, 009, 010, `src/tens_hq/metrics.py`, `services.py`,
   `tests/test_metrics.py`, and the generated recruiting CSVs are not
   ported. The shipped packet does not depend on them and runs green
   without them; they remain exactly where they were designed for --
   ReconOps, gated behind the same PII/governance concerns App B has
   always carried.

## Alternatives considered

- **Keep the overlay and reverse-port ReconRadar's public-only fixes back
  into ReconOps to re-converge the two trees:** rejected. This treats the
  drift as a one-time reconciliation rather than the structural defect it
  is -- the ADR-number collision and the stale-clone near-revert both
  happened because two people-shaped processes (a human running an
  overlay script from whichever clone happened to be on disk) were the
  only synchronization mechanism. Reverse-porting fixes the symptom for
  one cycle and leaves the same defect class in place for the next one.
- **Publish ReconOps's full history into ReconRadar, including the
  dev-process artifacts, so nothing is "lost":** rejected. This would
  publish the contaminated history this ADR exists partly to keep private
  (pre-scrub employer name, session URLs, machine paths), and it would
  ship internal working notes (`CLAUDE.md`, `AGENTS.md`, handoff logs, the
  product blueprint) that carry process and working detail never meant
  for a stranger reading a portfolio repository. Nothing of product value
  is lost by leaving it in the archive; ADR text that depends on
  archive-side rationale already cites the archive ADRs by number (see
  `docs/decisions/README.md`).
- **Do nothing; keep the two-repo mirror model and just be more careful
  running the overlay:** rejected. "Be more careful" is not a structural
  fix, and the three drift defects above were each individually
  the result of a careful person making a reasonable-seeming assumption
  (the clone is fresh; the allowlist is complete; the ADR numbers will
  naturally stay distinct) that a manual process cannot enforce.

## Consequences

- The overlay/drift defect class is closed structurally: there is exactly
  one tree being edited, so there is nothing left to silently diverge.
- ADR numbering now has a single authority (this repository's
  `docs/decisions/` sequence); a collision like ADR-024's is no longer
  possible by construction.
- Development is now public-by-default. The informal safety net the
  overlay's allowlist used to provide (nothing reaches the public repo
  that wasn't explicitly copied) is gone, so leak discipline moves
  forward to pre-commit review of every diff and to the source-sweep test
  pattern this codebase already uses for other forbidden-content classes
  (`tests/test_counsel_gate_sweep.py` for counsel-gated C3/C4 vocabulary,
  `tests/test_edge_boundary.py` for EDGE contamination) -- the natural
  model for any future automated secret/PII sweep, though no such test
  exists yet and this ADR does not claim one does.
- ReconOps keeps its own history, is never made public, and is never
  merged back into ReconRadar; the App B / synthetic-recruiting-concept
  work and ADRs 002/004/005/009/010 live there permanently.
- `docs/decisions/README.md`'s framing was updated in the same change to
  describe this repository as the source of truth rather than a curated
  public set cut from a private concept, while keeping its existing
  numbering-gaps note intact.
