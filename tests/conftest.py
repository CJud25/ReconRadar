from __future__ import annotations

import os
import socket

import pytest

from tens_hq.synthetic import generate_demo_data


class _BlockedNetwork(OSError):
    """Raised when a test attempts to open an outbound socket connection."""


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """Fail-closed network guard so NO test can reach a live host (offline).

    The build and the entire suite must be provably offline. This autouse
    fixture blocks the outbound-connection primitives -- ``socket.socket.connect``
    / ``connect_ex``, ``socket.create_connection``, and ``socket.getaddrinfo`` --
    so any accidental network call (including through ``urllib``) raises an
    ``OSError`` at the egress boundary. Creating a socket object is still allowed
    (harmless and used by in-process libraries); only reaching the wire is not.

    Because the raised error is an ``OSError``, ``urllib`` wraps it in a
    ``URLError`` and the API connector maps it to a bounded ``ConnectorError`` --
    which is exactly the fail-loud behavior the retrieve path promises.
    """

    def _blocked(*_args, **_kwargs):
        raise _BlockedNetwork("network access is blocked during tests (offline guarantee)")

    monkeypatch.setattr(socket.socket, "connect", _blocked, raising=True)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked, raising=True)
    monkeypatch.setattr(socket, "create_connection", _blocked, raising=True)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked, raising=True)
    yield


@pytest.fixture(scope="session", autouse=True)
def _isolated_evidence_ledger(tmp_path_factory):
    """Point the public-evidence SQLite ledger at a throwaway temp path.

    The BD Feasibility AppTest renders ``bd_page.render_public_bd_page``, which
    opens the case/evidence ledger at ``TENS_HQ_DB_PATH`` (defaulting to
    ``data/runtime/tens_hq.sqlite3`` inside the repo). Isolating it keeps the
    suite from writing into the working tree or sharing a ledger with a live
    demo instance.
    """

    db_path = tmp_path_factory.mktemp("evidence") / "tens_hq_test.sqlite3"
    previous = os.environ.get("TENS_HQ_DB_PATH")
    os.environ["TENS_HQ_DB_PATH"] = str(db_path)
    try:
        yield str(db_path)
    finally:
        if previous is None:
            os.environ.pop("TENS_HQ_DB_PATH", None)
        else:
            os.environ["TENS_HQ_DB_PATH"] = previous


@pytest.fixture(scope="session")
def demo_data():
    return generate_demo_data()


# Counsel-gated C3/C4 vocabulary is with counsel and excluded from every
# rendered surface AND from the packet modules' source text. One canonical
# term list, shared by the R2a-map guard, the whole-packet/export guard,
# the guided-tour copy guard, and the source sweep, so widening the list
# widens every guard at once. Includes the CORRECT citations AND the
# erroneous legacy '4874' citation this project once carried: the guards
# must catch the copy however it is cited. Matching is ORTHOGRAPHY-PROOF
# (adversarial-verify MAJOR): both sides are normalized -- lowercased,
# hyphens/dashes to spaces, periods removed, whitespace collapsed -- so
# hyphenated, undotted ('10 USC 3903'), extra-dotted ('13 C.F.R. 125.6'),
# and plural clause-title forms all match the same canonical terms.
COUNSEL_GATED_C3_C4_TERMS: tuple[str, ...] = (
    "small business goal credit",
    "sb goal credit",
    "10 u.s.c. 3903",
    "10 u.s.c. 4874",
    "2410d",
    "dfars 219.7",
    "limitation on subcontracting",
    "limitations on subcontracting",
    "52.219-14",
    "13 cfr 125.6",
    "los cap",
)


def _normalize_counsel_text(text: str) -> str:
    folded = text.lower()
    for dash in ("-", "‐", "‑", "–", "—"):
        folded = folded.replace(dash, " ")
    folded = folded.replace(".", "")
    return " ".join(folded.split())


def counsel_gate_violations(text: str) -> list[str]:
    """The counsel-gated terms present in ``text`` (normalized match), for
    guards to assert ``== []`` -- a failure then NAMES the matched terms."""

    normalized = _normalize_counsel_text(text)
    return [
        term
        for term in COUNSEL_GATED_C3_C4_TERMS
        if _normalize_counsel_text(term) in normalized
    ]
