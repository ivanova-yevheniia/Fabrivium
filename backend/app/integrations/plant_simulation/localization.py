"""
Plant Simulation localises its CLASS identifiers but not its METHODS, and —
critically — the localisation follows the MODEL, not the installation. A
model created by `NewModel()` on this machine answers to `.Modelle.Modell`
and `.Materialfluss.Einzelstation`, while the bundled English tutorial in
the same session answers to `.Models.Model` and `.MaterialFlow.Station`.

Both were confirmed against the installed product:

    German model                     English model
    .Modelle.Modell                  .Models.Model
    .Materialfluss.Einzelstation     .MaterialFlow.Station
    .Materialfluss.Quelle            .MaterialFlow.Source
    .Materialfluss.Senke             .MaterialFlow.Drain
    .Materialfluss.Puffer            .MaterialFlow.Buffer
    .Materialfluss.Kante             .MaterialFlow.Connector      <- the one that blocked Phase 15
    .Materialfluss.Parallelstation   .MaterialFlow.ParallelProc
    createObject(frame, x, y)        createObject(frame, x, y)    <- method: not localised
    .ProcTime                        .ProcTime                    <- attribute: not localised
    .XDim / .YDim                    .XDim / .YDim                <- attribute: not localised

The connector is the trap: "Kante" is German for *edge*, which is nothing a
translation of "Connector" would suggest. It was found by enumerating
candidate identifiers against the live product, not by guessing.

So the adapter never assumes a language: it asks the model which root it
answers to and picks the matching table.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Identifiers:
    """The localised class paths one model answers to."""

    language: str
    root: str
    library: str
    station: str
    parallel_station: str
    source: str
    drain: str
    buffer: str
    connector: str

    def cls(self, name: str) -> str:
        return f"{self.library}.{name}"

    def path(self, object_name: str) -> str:
        return f"{self.root}.{object_name}"

    @property
    def event_controller(self) -> str:
        return f"{self.root}.EventController"


ENGLISH = Identifiers(
    language="en",
    root=".Models.Model",
    library=".MaterialFlow",
    station="Station",
    parallel_station="ParallelProc",
    source="Source",
    drain="Drain",
    buffer="Buffer",
    connector="Connector",
)

GERMAN = Identifiers(
    language="de",
    root=".Modelle.Modell",
    library=".Materialfluss",
    station="Einzelstation",
    parallel_station="Parallelstation",
    source="Quelle",
    drain="Senke",
    buffer="Puffer",
    connector="Kante",
)

KNOWN_LOCALES: tuple[Identifiers, ...] = (ENGLISH, GERMAN)


class LocalizationError(RuntimeError):
    """Raised when no known identifier set resolves against the open model.
    """


def detect(probe) -> Identifiers:
    """Ask the OPEN MODEL which identifiers it answers to.

    `probe` is a callable taking a SimTalk expression and returning
    ``(ok, value)``. It is injected so this module stays testable without a
    Plant Simulation installation.
    """
    for candidate in KNOWN_LOCALES:
        ok, _ = probe(f"-> string; return {candidate.root}.Name")
        if ok:
            ok_lib, _ = probe(f"-> string; return {candidate.cls(candidate.station)}.Name")
            if ok_lib:
                return candidate
    raise LocalizationError(
        "This Plant Simulation model does not answer to any identifier set Fabrivium knows "
        f"({', '.join(c.language for c in KNOWN_LOCALES)}). The handoff was stopped rather than "
        "guessing an identifier."
    )
