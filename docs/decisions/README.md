# ReconRadar decision lineage

ReconRadar is the development source of truth for the Opportunity Packet and public-evidence case tracker; this file records that lineage.
The former private original, ReconOps, is now a frozen archive: it holds the App B / synthetic-recruiting-concept decisions and its own history, and is never merged back here (ADR-028).
Numbering gaps are intentional, not lost history.
ADRs 002, 004, 005, 009, 010 and the App B / recruiting-track decisions belong only to the ReconOps archive and are deliberately not included here.
Retained ADR text may cite those archive-side ADRs or the out-of-repo `AGENTS.md` guardrails; those references preserve rationale.
ADR-003 remains because ADR-013 and `opportunity_packet.py` rely on its status-only eligibility boundary.
ADR-027 records the EDGE gate-decision log kit, an append-only corpus of the team's own pursue/pass/watch calls, external to the packet.
ADR-028 records the repo-model decision itself: why ReconRadar became the source of truth and the mirror/overlay process was retired.
