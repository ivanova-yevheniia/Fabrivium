"""
Siemens Tecnomatix Plant Simulation adapter 

Builds a real, connected, runnable Plant Simulation model from a
:class:`FactoryMindExchange` package, through Siemens' own documented COM
automation interface (`Tecnomatix.PlantSimulation.RemoteControl`).

This module is the only place in the codebase that knows Siemens exists. It
depends on the exchange model and nothing else from the app — no domain
import, no simulation import, no FastAPI import. Fabrivium's simulator,
ranking and golden values are untouched by design, not by discipline.


* ``ExecuteSimTalk`` requires a return-type declaration: ``-> integer; ...``
* ``<class>.createObject(frame, x, y)`` creates and places an object
* ``.Name`` and ``.ProcTime`` are writable and readable
* ``<connector class>.connect(a, b)`` links two objects; the result is
  readable as ``a.succ`` / ``b.pred``
* ``SaveModel`` writes a real ``.spp``; topology survives a reload
  (checked at run time by ``_reopen_and_verify``, not merely assumed)
* ``StartSimulation(controller, True)`` runs fast-forward
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.integrations.plant_simulation.exchange_schema import FactoryMindExchange
from app.integrations.plant_simulation.layout import (
    MIN_SEPARATION_UNITS,
    LayoutPlan,
    collisions,
    plan_layout,
)
from app.integrations.plant_simulation.localization import Identifiers, LocalizationError, detect

#: Siemens' registered ProgID. 
_MIN_PLAUSIBLE_MODEL_BYTES = 100_000

#: Added to Plant Simulation's ``EventController.End`` so that a completion
#: scheduled at EXACTLY the horizon is counted.
HORIZON_EPSILON = 1e-6

PROG_IDS = (
    "Tecnomatix.PlantSimulation.RemoteControl",
    "Tecnomatix.PlantSimulation.RemoteControl.24.4",
)


def _product_version(app: Any) -> str | None:
    """The Plant Simulation release, as the product itself reports it.

    RemoteControl exposes no version property and no SimTalk equivalent —
    both were probed against the live installation and neither exists. What
    IS available is the COM type library's own description, e.g.
    "Plant Simulation 2404 Type Library", which Siemens writes, not us.

    It is read off the OBJECT's type library first. The earlier version of
    this function looked only at Python docstrings, which works for an
    early-bound proxy and never for the late-bound ``Dispatch`` the adapter
    actually uses: against the live 2404 installation ``type(app).__doc__``
    is pywin32's own "The dynamic class used as a last resort", so the
    version came back None on every real run. Asking the type library
    instead returns "Plant Simulation 2404 Type Library" — measured.

    The docstring paths are kept as a fallback for an early-bound proxy and
    for the test doubles, which have no COM type information at all.

    Returns None when nothing trustworthy is available. None means UNKNOWN
    and must be shown as UNKNOWN — guessing a version for a version-bound
    file format would be worse than admitting we do not know.
    """
    import sys  # noqa: PLC0415

    candidates: list[str] = []

    try:
        type_info = app._oleobj_.GetTypeInfo()  # noqa: SLF001 - the documented pywin32 route
        library, _index = type_info.GetContainingTypeLib()
        candidates.append(library.GetDocumentation(-1)[1] or "")
    except Exception:  # noqa: BLE001 - no type info is simply no version
        pass

    candidates.append(type(app).__doc__ or "")
    candidates.append(getattr(sys.modules.get(type(app).__module__, None), "__doc__", "") or "")

    for text in candidates:
        if "Plant Simulation" in text:
          
            words = text.split()
            for index, word in enumerate(words):
                if word.rstrip(".,;:") != "Simulation" or index + 1 >= len(words):
                    continue
                candidate = words[index + 1].rstrip(".,;:")
                if candidate.isdigit():
                    return f"Plant Simulation {candidate}"
    return None


def simtalk_identifier(name: str) -> str:
    """A SimTalk-legal object name derived from a Fabrivium station name.
    """

    cleaned = []
    for char in name.strip():
        if char.isalnum():
            cleaned.append(char)
        elif char in " -/.":
            cleaned.append("_")
        
    identifier = "".join(cleaned).strip("_")
    while "__" in identifier:
        identifier = identifier.replace("__", "_")
    if not identifier or identifier[0].isdigit():
        identifier = f"S_{identifier}"
    return identifier



RESERVED_IDENTIFIERS = frozenset({"Source", "Drain"})


def assign_identifiers(package: "FactoryMindExchange") -> dict[str, str]:
    """Every station and buffer id mapped to a UNIQUE SimTalk identifier.
    """
    taken: set[str] = set(RESERVED_IDENTIFIERS)
    mapping: dict[str, str] = {}

    for object_id, name in _named_objects(package):
        base = simtalk_identifier(name)
        candidate = base
        suffix = 2
        while candidate in taken:
            candidate = f"{base}_{suffix}"
            suffix += 1
        taken.add(candidate)
        mapping[object_id] = candidate

    return mapping


def _named_objects(package: "FactoryMindExchange") -> list[tuple[str, str]]:
    """(id, Fabrivium name) for everything that becomes a frame object.
    """
    return [(station.id, station.name) for station in package.stations] + [
        (buffer.id, buffer.name) for buffer in package.buffers
    ]


def _simtalk_string(value: str) -> str:
    """A value safe to paste inside a double-quoted SimTalk literal.
    """
    return (
        value.replace("\\", "\\\\")
        .replace('"', "'")
        .replace("\r", " ")
        .replace("\n", " ")
    )


class PlantSimulationUnavailable(RuntimeError):
    """Plant Simulation could not be reached at all.
    """


@dataclass
class StationCheck:
    station_id: str
    source_name: str
    name_expected: str
    name_actual: str | None = None
    cycle_time_expected: float = 0.0
    cycle_time_actual: float | None = None
    # How many units the stage may process at once. 
    capacity_expected: int = 1
    capacity_actual: int | None = None
    error: str | None = None

    @property
    def verified(self) -> bool:
        if (
            self.error
            or self.name_actual is None
            or self.cycle_time_actual is None
            or self.capacity_actual is None
        ):
            return False
        return (
            self.name_actual == self.name_expected
            and abs(self.cycle_time_actual - self.cycle_time_expected) < 1e-6
            and self.capacity_actual == self.capacity_expected
        )


@dataclass
class BufferCheck:
    """One intermediate buffer, verified like everything else by read-back.
    """

    buffer_id: str
    source_name: str
    name_expected: str
    name_actual: str | None = None
    capacity_expected: int = 1
    capacity_actual: int | None = None
    error: str | None = None

    @property
    def verified(self) -> bool:
        if self.error or self.name_actual is None or self.capacity_actual is None:
            return False
        return (
            self.name_actual == self.name_expected
            and self.capacity_actual == self.capacity_expected
        )


@dataclass
class LinkCheck:
    from_name: str
    to_name: str
    actual_successor: str | None = None
    error: str | None = None

    @property
    def verified(self) -> bool:
        return self.error is None and self.actual_successor == self.to_name


@dataclass
class PositionCheck:
    """Where an object was asked to go, and where it actually ended up.
    """

    name: str
    x_expected: int
    y_expected: int
    x_actual: int | None = None
    y_actual: int | None = None
    error: str | None = None

    @property
    def verified(self) -> bool:
        if self.error or self.x_actual is None or self.y_actual is None:
            return False
        return self.x_actual == self.x_expected and self.y_actual == self.y_expected

    @property
    def actual(self) -> tuple[int, int] | None:
        if self.x_actual is None or self.y_actual is None:
            return None
        return (self.x_actual, self.y_actual)


@dataclass
class EquipmentCheck:
    """The equipment under consideration, carried into the model as metadata.
    """

    station_name: str
    manufacturer_expected: str | None = None
    model_expected: str | None = None
    manufacturer_actual: str | None = None
    model_actual: str | None = None
    error: str | None = None

    @property
    def verified(self) -> bool:
        if self.error:
            return False
        return (
            self.manufacturer_actual == self.manufacturer_expected
            and self.model_actual == self.model_expected
        )


class VerificationTier(str, Enum):
    """One layer of the handoff claim, verified independently of the others.

      STRUCTURE  the right objects exist and hold the right values
      LAYOUT     they are in distinct, non-overlapping, readable places
      FLOW       Source reaches Drain through every one of them
      RUNTIME    a unit was actually put through and came out

    """

    STRUCTURE = "STRUCTURE"
    LAYOUT = "LAYOUT"
    FLOW = "FLOW"
    RUNTIME = "RUNTIME"


class TierStatus(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class TierResult:
    tier: str
    status: str
    detail: str


@dataclass
class HandoffResult:
    """What actually happened. Every count is derived from read-back."""

    ok: bool = False
    language: str | None = None
    product_version: str | None = None
    model_path: str | None = None
    model_bytes: int | None = None
    stations: list[StationCheck] = field(default_factory=list)
    buffers: list[BufferCheck] = field(default_factory=list)
    links: list[LinkCheck] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


    layout_mode: str | None = None
    layout_reason: str | None = None
    layout_min_separation: int | None = None
    positions: list[PositionCheck] = field(default_factory=list)
    overlaps: list[str] = field(default_factory=list)


    route_walked: list[str] = field(default_factory=list)
    route_complete: bool | None = None
    disconnected: list[str] = field(default_factory=list)

    traversal_units: int | None = None
    traversal_verified: bool | None = None

    def tiers(self) -> list[TierResult]:
        """The four verdicts, each derived from evidence already read back.
        """
        results: list[TierResult] = []

        # STRUCTURE 
        station_total = len(self.stations)
        stations_ok = sum(1 for s in self.stations if s.verified)
        cycles_ok = sum(
            1
            for s in self.stations
            if s.cycle_time_actual is not None
            and abs(s.cycle_time_actual - s.cycle_time_expected) < 1e-6
        )
        buffers_ok = sum(1 for b in self.buffers if b.verified)
        structure_ok = (
            station_total > 0
            and stations_ok == station_total
            and cycles_ok == station_total
            and buffers_ok == len(self.buffers)
        )
        results.append(
            TierResult(
                VerificationTier.STRUCTURE.value,
                TierStatus.VERIFIED.value if structure_ok else TierStatus.FAILED.value,
                f"{stations_ok}/{station_total} stations, {cycles_ok}/{station_total} cycle times, "
                f"{buffers_ok}/{len(self.buffers)} buffers read back from the reopened model",
            )
        )

        # LAYOUT
        positions_ok = sum(1 for p in self.positions if p.verified)
        layout_ok = bool(self.positions) and positions_ok == len(self.positions) and not self.overlaps
        results.append(
            TierResult(
                VerificationTier.LAYOUT.value,
                TierStatus.VERIFIED.value if layout_ok else TierStatus.FAILED.value,
                (
                    f"{positions_ok}/{len(self.positions)} objects at the position they were given; "
                    f"closest pair {self.layout_min_separation} units apart"
                    if not self.overlaps
                    else "; ".join(self.overlaps)
                ),
            )
        )

        # FLOW 
        links_ok = sum(1 for link in self.links if link.verified)
        flow_ok = bool(self.route_complete) and links_ok == len(self.links) and not self.disconnected
        results.append(
            TierResult(
                VerificationTier.FLOW.value,
                TierStatus.VERIFIED.value if flow_ok else TierStatus.FAILED.value,
                (
                    f"{links_ok}/{len(self.links)} connections; Source to Drain through "
                    f"{len(self.route_walked)} objects"
                    if flow_ok
                    else f"{links_ok}/{len(self.links)} connections; "
                    + (
                        f"off the route: {', '.join(self.disconnected)}"
                        if self.disconnected
                        else "no complete Source-to-Drain walk"
                    )
                ),
            )
        )

        # RUNTIME
        if self.traversal_verified is None and self.traversal_units is None:
            runtime = TierStatus.NOT_RUN.value
            detail = "no smoke run was attempted"
        elif self.traversal_verified:
            runtime = TierStatus.VERIFIED.value
            detail = f"{self.traversal_units} unit(s) reached the drain in a short run"
        else:
            runtime = TierStatus.FAILED.value
            detail = f"{self.traversal_units or 0} unit(s) reached the drain"
        results.append(TierResult(VerificationTier.RUNTIME.value, runtime, detail))

        return results

    @property
    def fully_verified(self) -> bool:
        """Every layer that RAN passed, and none failed.

        RUNTIME being NOT_RUN does not make this false — a handoff without a
        smoke run is a legitimate, weaker claim — but the UI must show the
        tier as NOT_RUN rather than absorbing it into a single green word.
        """
        return all(tier.status != TierStatus.FAILED.value for tier in self.tiers())

    # equipment metadata 
    equipment: list[EquipmentCheck] = field(default_factory=list)

    reopened_positions: list[PositionCheck] = field(default_factory=list)

    #: None  = no round trip was attempted (nothing was saved).
    #: False = the file could not be re-opened, or its contents disagreed.
    #: True  = every station and link was found again in the reloaded file.
    saved_model_verified: bool | None = None
    reopened_stations: list[StationCheck] = field(default_factory=list)
    reopened_buffers: list[BufferCheck] = field(default_factory=list)
    reopened_links: list[LinkCheck] = field(default_factory=list)

    simulated_units: float | None = None
    simulated_seconds: float | None = None
    station_utilisation: dict[str, float] = field(default_factory=dict)

    @property
    def stations_verified(self) -> int:
        return sum(1 for s in self.stations if s.verified)

    @property
    def buffers_verified(self) -> int:
        return sum(1 for b in self.buffers if b.verified)

    @property
    def reopened_buffers_verified(self) -> int:
        return sum(1 for b in self.reopened_buffers if b.verified)

    @property
    def links_verified(self) -> int:
        return sum(1 for link in self.links if link.verified)

    @property
    def reopened_stations_verified(self) -> int:
        return sum(1 for s in self.reopened_stations if s.verified)

    @property
    def reopened_links_verified(self) -> int:
        return sum(1 for link in self.reopened_links if link.verified)

    @property
    def positions_verified(self) -> int:
        return sum(1 for p in self.positions if p.verified)

    @property
    def equipment_verified(self) -> int:
        return sum(1 for e in self.equipment if e.verified)

    @property
    def geometry_verified(self) -> bool:
        """Every object is where it was put, and no two of them overlap.
        """
        return (
            bool(self.positions)
            and self.positions_verified == len(self.positions)
            and not self.overlaps
        )

    @property
    def fully_verified(self) -> bool:
        """The only condition under which a handoff may be called complete.
        """
        in_session = (
            not self.errors
            and bool(self.stations)
            and self.stations_verified == len(self.stations)
            and self.buffers_verified == len(self.buffers)
            and self.links_verified == len(self.links)
            and self.geometry_verified
            and self.route_complete is True
            and not self.disconnected
            and self.equipment_verified == len(self.equipment)
        )
    
        if self.traversal_verified is False:
            return False
        if self.saved_model_verified is None:
            return in_session
        return in_session and self.saved_model_verified

    def summary(self) -> dict[str, Any]:
        return {
            "ok": self.fully_verified,
            "language": self.language,
            "product_version": self.product_version,
            "model_path": self.model_path,
            "model_bytes": self.model_bytes,
            "stations_transferred": f"{self.stations_verified}/{len(self.stations)}",
            "cycle_times_verified": f"{self.stations_verified}/{len(self.stations)}",
            "buffers_verified": f"{self.buffers_verified}/{len(self.buffers)}",
            "flow_connections_verified": f"{self.links_verified}/{len(self.links)}",
            "layout_mode": self.layout_mode,
            "layout_reason": self.layout_reason,
            "layout_min_separation": self.layout_min_separation,
            "positions_verified": f"{self.positions_verified}/{len(self.positions)}",
            "overlaps": self.overlaps,
            "route_complete": self.route_complete,
            "route_walked": self.route_walked,
            "disconnected": self.disconnected,
            "traversal_units": self.traversal_units,
            "traversal_verified": self.traversal_verified,
            "equipment_verified": f"{self.equipment_verified}/{len(self.equipment)}",
            "saved_model_verified": self.saved_model_verified,
            "saved_model_stations_verified": (
                f"{self.reopened_stations_verified}/{len(self.reopened_stations)}"
                if self.reopened_stations
                else None
            ),
            "saved_model_connections_verified": (
                f"{self.reopened_links_verified}/{len(self.reopened_links)}"
                if self.reopened_links
                else None
            ),
            "simulated_units": self.simulated_units,
            "simulated_seconds": self.simulated_seconds,
            "station_utilisation": self.station_utilisation,
            "errors": self.errors,
        }


@dataclass
class ExecutionResult:
    """What Plant Simulation actually produced when the model was RUN.
    """

    executed: bool = False
    horizon_seconds: float | None = None
    sim_time: str | None = None
    reached_horizon: bool | None = None
    had_error: bool | None = None
    timed_out: bool = False

    release_interval_seconds: float | None = None
    units_to_release: int | None = None

    finished_units: int | None = None
    units_admitted: int | None = None

    station_utilisation: dict[str, float] = field(default_factory=dict)
    station_blocking: dict[str, float] = field(default_factory=dict)
    station_waiting: dict[str, float] = field(default_factory=dict)

    errors: list[str] = field(default_factory=list)

    @property
    def limiting_station(self) -> str | None:
        """The busiest station — Plant Simulation's own bottleneck evidence."""
        if not self.station_utilisation:
            return None
        return max(self.station_utilisation, key=lambda k: self.station_utilisation[k])

    def summary(self) -> dict[str, Any]:
        return {
            "executed": self.executed,
            "horizon_seconds": self.horizon_seconds,
            "sim_time": self.sim_time,
            "reached_horizon": self.reached_horizon,
            "had_error": self.had_error,
            "timed_out": self.timed_out,
            "release_interval_seconds": self.release_interval_seconds,
            "units_to_release": self.units_to_release,
            "finished_units": self.finished_units,
            "units_admitted": self.units_admitted,
            "limiting_station": self.limiting_station,
            "station_utilisation": self.station_utilisation,
            "station_blocking": self.station_blocking,
            "station_waiting": self.station_waiting,
            "errors": self.errors,
        }


class PlantSimulationAdapter:
    """Drives one Plant Simulation session.

    `dispatch` is injected so the whole class is testable without Siemens
    installed
    """

    def __init__(self, dispatch=None) -> None:
        self._dispatch = dispatch or self._default_dispatch
        self.app: Any = None
        self.ids: Identifiers | None = None
        #: The ProgID that actually answered, and the product version the
        #: automation type library reports. Both are recorded rather than
        #: assumed: an .spp is version-bound, so whoever receives one needs
        #: to know which release wrote it.
        self.prog_id: str | None = None
        self.product_version: str | None = None

    # connection 

    @staticmethod
    def _default_dispatch(prog_id: str):
        try:
            import win32com.client  
        except ImportError as exc:  
            raise PlantSimulationUnavailable(
                "pywin32 is not installed, so Fabrivium cannot reach Plant Simulation on this machine."
            ) from exc
        return win32com.client.Dispatch(prog_id)

    def connect(self, visible: bool = False) -> None:
        last: Exception | None = None
        for prog_id in PROG_IDS:
            try:
                self.app = self._dispatch(prog_id)
                self.prog_id = prog_id
                break
            except Exception as exc: 
                last = exc
        if self.app is None:
            raise PlantSimulationUnavailable(
                "Siemens Plant Simulation is not installed on this machine, or its automation "
                f"interface is not registered. Last error: {last}"
            )
        self.product_version = _product_version(self.app)
        self.app.SetNoMessageBox(True)
        self.app.SetTrustModels(True)
        self.app.SetVisible(visible)
        for setter in ("SetSuppressStartOf3D", "SetSuppressOpenGL"):
            try:
                getattr(self.app, setter)(not visible)
            except Exception:  
                pass

    def close(self) -> None:
        if self.app is not None:
            try:
                self.app.Quit()
            except Exception:  
                pass
            self.app = None

    #  SimTalk 

    def _st(self, expr: str):
        return self.app.ExecuteSimTalk(expr)

    def _try(self, expr: str) -> tuple[bool, Any]:
        """Run SimTalk, returning Plant Simulation's own message on failure.

        The COM exception carries the SimTalk diagnostic in its excepinfo
        tuple; surfacing that verbatim is what makes a failure diagnosable
        instead of "COM error".
        """
        try:
            return True, self._st(expr)
        except Exception as exc:  # noqa: BLE001
            detail = exc.args[2] if len(exc.args) > 2 and exc.args[2] else None
            return False, (detail[2] if detail and len(detail) > 2 else str(exc))


    def route_of(
        self, package: FactoryMindExchange
    ) -> tuple[list[str], dict[str, tuple[float, float]], dict[str, tuple[str | None, str | None]], bool]:
        """The material-flow route, in order, as Plant Simulation will name it.

        Returns the chain, Fabrivium's conceptual coordinates for the
        objects that have them, each object's route neighbours, and whether
        EVERY station carried a coordinate.
        """
        names = assign_identifiers(package)
        chain = ["Source"]
        concept: dict[str, tuple[float, float]] = {}
        for index, station in enumerate(package.stations):
            name = names[station.id]
            chain.append(name)
            if station.x is not None and station.y is not None:
                concept[name] = (float(station.x), float(station.y))
            if index + 1 < len(package.stations):
                nxt = package.stations[index + 1].id
                between = next(
                    (
                        b
                        for b in package.buffers
                        if b.upstream_station_id == station.id and b.downstream_station_id == nxt
                    ),
                    None,
                )
                if between is not None:
                    chain.append(names[between.id])
        chain.append("Drain")

        neighbours = {
            name: (
                chain[index - 1] if index > 0 else None,
                chain[index + 1] if index + 1 < len(chain) else None,
            )
            for index, name in enumerate(chain)
        }
        return chain, concept, neighbours, len(concept) == len(package.stations)

    def plan_for(self, package: FactoryMindExchange) -> LayoutPlan:
        """The collision-free Plant Simulation placement for this package."""
        chain, concept, neighbours, complete = self.route_of(package)
        return plan_layout(
            chain,
            concept_points=concept if complete else None,
            neighbours=neighbours,
            fallback_reason=(
                None
                if complete
                else (
                    "the concept carries no layout coordinates"
                    if not concept
                    else "not every station carries a concept coordinate, so the arrangement "
                    "could not be transferred without inventing the missing ones"
                )
            ),
        )

    def build(
        self,
        package: FactoryMindExchange,
        save_path: str | None = None,
        *,
        verify_traversal: bool = True,
    ) -> HandoffResult:
        """Create the model, then verify it by reading it back."""
        result = HandoffResult()
        if self.app is None:
            result.errors.append("Not connected to Plant Simulation.")
            return result

        self.app.NewModel()
        try:
            self.ids = detect(self._try)
        except LocalizationError as exc:
            result.errors.append(str(exc))
            return result
        ids = self.ids
        result.language = ids.language
        result.product_version = self.product_version

        # geometry 
        # Fabrivium's floor coordinates are METRES; 
        plan = self.plan_for(package)
        result.layout_mode = plan.mode
        result.layout_reason = plan.reason
        result.layout_min_separation = plan.min_separation


        names = assign_identifiers(package)

        #  source 
        source_x, source_y = plan.position("Source")
        ok, detail = self._try(
            f'-> string; var o : object := '
            f'{ids.cls(ids.source)}.createObject({ids.root}, {source_x}, {source_y}); '
            f'o.Name := "Source"; return o.Name'
        )
        if not ok:
            result.errors.append(f"Could not create the source: {detail}")
            return result
        #: Objects that were actually created, so the flow chain and the
        #: geometry check only ever ask about objects that exist.
        created: set[str] = {"Source"}

        # stations
        for station in package.stations:
            object_name = names[station.id]
            x, y = plan.position(object_name)
            
            if station.capacity > 1:
                create = (
                    f'-> string; var o : object := '
                    f'{ids.cls(ids.buffer)}.createObject({ids.root}, {x}, {y}); '
                    f'o.Name := "{object_name}"; '
                    f'o.ProcTime := {station.cycle_time_seconds}; '
                    f'o.Capacity := {station.capacity}; '
                    f'return o.Name'
                )
            else:
                create = (
                    f'-> string; var o : object := '
                    f'{ids.cls(ids.station)}.createObject({ids.root}, {x}, {y}); '
                    f'o.Name := "{object_name}"; '
                    f'o.ProcTime := {station.cycle_time_seconds}; '
                    f'o.Capacity := {station.capacity}; '
                    f'return o.Name'
                )
            ok, detail = self._try(create)
            if not ok:
                result.errors.append(f"Could not create station '{station.name}': {detail}")
                continue
            created.add(object_name)
            self._write_equipment_metadata(station, object_name, result)

        # drain 
        drain_x, drain_y = plan.position("Drain")
        ok, detail = self._try(
            f'-> string; var o : object := '
            f'{ids.cls(ids.drain)}.createObject({ids.root}, {drain_x}, {drain_y}); '
            f'o.Name := "Drain"; return o.Name'
        )
        if not ok:
            result.errors.append(f"Could not create the drain: {detail}")
        else:
            created.add("Drain")

        #  buffers
        for buffer in package.buffers:
            object_name = names[buffer.id]
            check = BufferCheck(
                buffer_id=buffer.id,
                source_name=buffer.name,
                name_expected=object_name,
                capacity_expected=buffer.capacity,
            )
            if object_name not in plan.positions:
                check.error = "not between two consecutive stations on the route"
                result.errors.append(
                    f"Buffer '{buffer.name}' does not sit between two consecutive stations on the "
                    f"route, so it has no position on the material flow and was not transferred."
                )
                result.buffers.append(check)
                continue
            buffer_x, buffer_y = plan.position(object_name)
            ok, detail = self._try(
                f'-> string; var o : object := {ids.cls(ids.buffer)}.createObject({ids.root}, '
                f'{buffer_x}, {buffer_y}); '
                f'o.Name := "{object_name}"; '
                f'o.Capacity := {buffer.capacity}; '
                # A Fabrivium buffer is storage, not a process step
                f'o.ProcTime := 0; '
                f'return o.Name'
            )
            if not ok:
                check.error = str(detail)
                result.errors.append(f"Could not create buffer '{buffer.name}': {detail}")
            else:
                created.add(object_name)
            result.buffers.append(check)

        # flow 
        # The connector chain IS the layout chain. They were built
        # separately before, which is how a model could be fully connected
        chain = [name for name in plan.chain if name in created]
        for a, b in zip(chain, chain[1:]):
            check = LinkCheck(from_name=a, to_name=b)
            ok, detail = self._try(
                f'-> string; {ids.cls(ids.connector)}.connect({ids.path(a)}, {ids.path(b)}); return "ok"'
            )
            if not ok:
                check.error = str(detail)
            result.links.append(check)

        # verification: read everything back 
        # The build-time buffer checks recorded WHAT WAS ATTEMPTED; _verify
        # replaces them with what the model actually answers.
        attempted_buffer_errors = {b.buffer_id: b.error for b in result.buffers if b.error}
        result.buffers = []
        self._verify(package, result)
        for check in result.buffers:
            check.error = check.error or attempted_buffer_errors.get(check.buffer_id)

        # verification: is it GEOMETRICALLY a factory? 
        self._verify_geometry(plan, created, result, result.positions)
        self._verify_route(chain, created, result)

        # save, then CHECK THE FILE IS THERE 
        if save_path:
            try:
                self.app.SaveModel(save_path)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"Could not save the model: {str(exc)[:200]}")
            else:
                # SaveModel returning is not a file existing.
                import os  # noqa: PLC0415

                try:
                    size = os.path.getsize(save_path)
                except OSError:
                    result.errors.append(
                        f"Plant Simulation reported the model saved, but no file exists at {save_path}."
                    )
                else:
                    if size < _MIN_PLAUSIBLE_MODEL_BYTES:
                        result.errors.append(
                            f"The saved model is only {size} bytes, which is too small to be a "
                            f"Plant Simulation model."
                        )
                    else:
                        result.model_path = save_path
                        result.model_bytes = size
                        self._reopen_and_verify(package, result, save_path)

        # verification: does a unit actually GET to the drain? 
        if verify_traversal and not result.errors:
            self._verify_traversal(package, result)

        result.ok = result.fully_verified
        return result

    #  geometry, route and traversal verification 

    def _write_equipment_metadata(self, station, object_name: str, result: HandoffResult) -> None:
        """Carry the equipment under consideration into the model as METADATA.

        Written as user-defined attributes (measured: ``createAttr`` accepts
        them, and they survive a save/reload round trip), never into
        ProcTime, Capacity or any other value the simulation reads. The
        manufacturer's published figures were not verified by Fabrivium,
        so overwriting a verified concept parameter with one would ship a
        number nobody checked.
        """
        if not (station.selected_manufacturer or station.selected_model):
            return
        ids = self.ids
        assert ids is not None
        path = ids.path(object_name)
        statements = [
            f'{path}.createAttr("FM_Manufacturer", "string")',
            f'{path}.createAttr("FM_Model", "string")',
            f'{path}.createAttr("FM_SourceURL", "string")',
            f'{path}.createAttr("FM_ParameterSource", "string")',
            f'{path}.FM_Manufacturer := "{_simtalk_string(station.selected_manufacturer or "")}"',
            f'{path}.FM_Model := "{_simtalk_string(station.selected_model or "")}"',
            f'{path}.FM_SourceURL := "{_simtalk_string(station.selected_source_url or "")}"',
            # Stated in the model itself so the receiving engineer cannot
            # mistake the process values for the manufacturer's.
            f'{path}.FM_ParameterSource := "Fabrivium verified concept — '
            f'manufacturer figures are NOT applied"',
        ]
        ok, detail = self._try("-> string; " + "; ".join(statements) + '; return "ok"')
        if not ok:
            result.errors.append(
                f"Could not attach the selected equipment to '{station.name}': {detail}"
            )

    def _verify_geometry(
        self,
        plan: LayoutPlan,
        created: set[str],
        result: HandoffResult,
        into: list[PositionCheck],
    ) -> None:
        """Ask the model where every object IS, and check nothing overlaps.
        """
        ids = self.ids
        assert ids is not None
        actual: dict[str, tuple[int, int]] = {}
        for name in plan.chain:
            if name not in created:
                continue
            x_expected, y_expected = plan.position(name)
            check = PositionCheck(name=name, x_expected=x_expected, y_expected=y_expected)
            ok, value = self._try(
                f'-> string; return to_str({ids.path(name)}.XPos) + "," + to_str({ids.path(name)}.YPos)'
            )
            if not ok:
                check.error = str(value)[:200]
            else:
                try:
                    raw_x, raw_y = str(value).split(",")
                    check.x_actual = int(float(raw_x))
                    check.y_actual = int(float(raw_y))
                    actual[name] = (check.x_actual, check.y_actual)
                except (TypeError, ValueError):
                    check.error = f"position read back as {value!r}, which is not a coordinate"
            into.append(check)

        clamped = [c for c in into if c.error is None and not c.verified]
        if clamped:
            result.errors.append(
                "Plant Simulation did not place "
                + ", ".join(
                    f"{c.name} at ({c.x_expected}, {c.y_expected}) — it reports "
                    f"({c.x_actual}, {c.y_actual})"
                    for c in clamped[:4]
                )
                + ". The model is structurally present but geometrically wrong."
            )

        overlapping = collisions(actual)
        if overlapping:
            result.overlaps = [
                f"{a} and {b} are {gap} units apart, inside the {MIN_SEPARATION_UNITS}-unit icon"
                for a, b, gap in overlapping
            ]
            result.errors.append(
                f"{len(overlapping)} pair(s) of objects overlap in the Plant Simulation frame, so "
                f"the model would open as a pile rather than as a line: {result.overlaps[0]}."
            )

    def _verify_route(self, chain: list[str], created: set[str], result: HandoffResult) -> None:
        """WALK the model from Source to Drain and report where it leads.
        """
        ids = self.ids
        assert ids is not None
        walked: list[str] = []
        current = "Source"
        seen: set[str] = set()
        while current and current not in seen and len(walked) <= len(chain) + 1:
            walked.append(current)
            seen.add(current)
            if current == "Drain":
                break
            ok, value = self._try(f"-> string; return {ids.path(current)}.succ.Name")
            if not ok:
                result.errors.append(
                    f"The material flow could not be followed past '{current}': {value}"
                )
                break
            current = str(value) if value else ""
            if not current:
                result.errors.append(
                    f"The material flow stops at '{walked[-1]}' — it has no successor, so nothing "
                    f"downstream of it can ever be reached."
                )
                break

        result.route_walked = walked
        expected = [name for name in chain if name in created]
        result.disconnected = [name for name in expected if name not in walked]
        result.route_complete = walked == expected

        if result.disconnected:
            result.errors.append(
                "These objects exist in the model but are not on the route from Source to Drain: "
                + ", ".join(result.disconnected)
                + "."
            )
        elif not result.route_complete:
            result.errors.append(
                "The route through the model is not the route that was sent. Expected "
                + " → ".join(expected)
                + "; the model walks "
                + " → ".join(walked)
                + "."
            )

    def _verify_traversal(self, package: FactoryMindExchange, result: HandoffResult) -> None:
        """Prove a unit can actually travel the route, by running the model.
        """
        import time  # noqa: PLC0415 

        ids = self.ids
        if ids is None or self.app is None:
            return

        cycle_total = sum(s.cycle_time_seconds for s in package.stations)
        slowest = max((s.cycle_time_seconds for s in package.stations), default=1.0)
        units = 3
        horizon = cycle_total + units * slowest + 60.0

        for expr in (
            f"{ids.event_controller}.End := {horizon}",
            f'{ids.path("Source")}.Interval := {max(1.0, slowest)}',
            f'{ids.path("Source")}.Number := {units}',
        ):
            ok, detail = self._try(f'-> string; {expr}; return "ok"')
            if not ok:
                result.traversal_verified = False
                result.errors.append(f"The verification run could not be set up: {detail}")
                return

        try:
            self.app.ResetSimulation(ids.event_controller)
            self.app.StartSimulation(ids.event_controller, True)
        except Exception as exc:  # noqa: BLE001
            result.traversal_verified = False
            result.errors.append(f"The verification run could not be started: {str(exc)[:200]}")
            return

        started = time.time()
        while self.app.IsSimulationRunning() and time.time() - started < 60.0:
            time.sleep(0.2)
        if self.app.IsSimulationRunning():
            try:
                self.app.StopSimulation()
            except Exception:  # noqa: BLE001 
                pass
            result.traversal_verified = False
            result.errors.append(
                "The verification run did not finish within 60s, so it is not evidence that "
                "material can traverse the route."
            )
            return

        ok, value = self._try(f'-> string; return to_str({ids.path("Drain")}.StatNumIn)')
        if not ok:
            result.traversal_verified = False
            result.errors.append(f"The drain did not report a unit count: {value}")
            return
        try:
            result.traversal_units = int(float(value))
        except (TypeError, ValueError):
            result.traversal_verified = False
            result.errors.append(f"The drain reported {value!r}, which is not a unit count.")
            return

        result.traversal_verified = result.traversal_units >= 1
        if not result.traversal_verified:
            result.errors.append(
                "No unit reached the drain in the verification run. The model is connected on "
                "paper but nothing travels the route."
            )

    def _reopen_and_verify(
        self, package: FactoryMindExchange, result: HandoffResult, save_path: str
    ) -> None:
        """Load the saved file back and read the topology out of IT.
        """
        # Plant Simulation refuses to load over an open model ("Model already
        # loaded"), so the session is closed first. 
        try:
            self.app.CloseModel()
        except Exception:  # noqa: BLE001 
            pass

        try:
            self.app.LoadModel(save_path)
        except Exception as exc:  # noqa: BLE001
            result.saved_model_verified = False
            result.errors.append(
                f"The saved model could not be re-opened for verification: {str(exc)[:200]}"
            )
            return

        try:
            reopened = HandoffResult()
            reopened.links = [
                LinkCheck(from_name=link.from_name, to_name=link.to_name) for link in result.links
            ]
            self._verify(package, reopened)
        except Exception as exc:  # noqa: BLE001
            result.saved_model_verified = False
            result.errors.append(
                f"The saved model was re-opened but could not be read back: {str(exc)[:200]}"
            )
            return

        plan = self.plan_for(package)
        created = {name for name in plan.chain}
        geometry = HandoffResult()
        self._verify_geometry(plan, created, geometry, result.reopened_positions)

        result.reopened_stations = reopened.stations
        result.reopened_buffers = reopened.buffers
        result.reopened_links = reopened.links
        positions_held = bool(result.reopened_positions) and all(
            p.verified for p in result.reopened_positions
        )
        matched = (
            bool(reopened.stations)
            and reopened.stations_verified == len(reopened.stations)
            and reopened.buffers_verified == len(reopened.buffers)
            and reopened.links_verified == len(reopened.links)
            and positions_held
            and not geometry.overlaps
            and reopened.equipment_verified == len(reopened.equipment)
        )
        result.saved_model_verified = matched
        if not matched:
            result.errors.append(
                f"The saved file does not match the model that was built: "
                f"{reopened.stations_verified}/{len(reopened.stations)} stations, "
                f"{reopened.links_verified}/{len(reopened.links)} connections and "
                f"{sum(1 for p in result.reopened_positions if p.verified)}/"
                f"{len(result.reopened_positions)} positions survived the save."
            )
            result.errors.extend(geometry.errors)

    def _verify(self, package: FactoryMindExchange, result: HandoffResult) -> None:
        ids = self.ids
        assert ids is not None
        names = assign_identifiers(package)

        for station in package.stations:
            object_name = names[station.id]
            check = StationCheck(
                station_id=station.id,
                source_name=station.name,
                name_expected=object_name,
                cycle_time_expected=station.cycle_time_seconds,
                capacity_expected=station.capacity,
            )
            try:
                check.name_actual = self.app.GetValue(f"{ids.path(object_name)}.Name")
                check.cycle_time_actual = float(self.app.GetValue(f"{ids.path(object_name)}.ProcTime"))
                check.capacity_actual = int(float(self.app.GetValue(f"{ids.path(object_name)}.Capacity")))
            except Exception as exc:  # noqa: BLE001
                check.error = str(exc)[:200]
            result.stations.append(check)

            
            if station.selected_manufacturer or station.selected_model:
                equipment = EquipmentCheck(
                    station_name=object_name,
                    manufacturer_expected=_simtalk_string(station.selected_manufacturer or ""),
                    model_expected=_simtalk_string(station.selected_model or ""),
                )
                ok_maker, maker = self._try(
                    f"-> string; return {ids.path(object_name)}.FM_Manufacturer"
                )
                ok_model, model = self._try(f"-> string; return {ids.path(object_name)}.FM_Model")
                if not (ok_maker and ok_model):
                    equipment.error = str(maker if not ok_maker else model)[:200]
                else:
                    equipment.manufacturer_actual = str(maker)
                    equipment.model_actual = str(model)
                result.equipment.append(equipment)

        for buffer in package.buffers:
            object_name = names[buffer.id]
            check = BufferCheck(
                buffer_id=buffer.id,
                source_name=buffer.name,
                name_expected=object_name,
                capacity_expected=buffer.capacity,
            )
            try:
                check.name_actual = self.app.GetValue(f"{ids.path(object_name)}.Name")
                check.capacity_actual = int(float(self.app.GetValue(f"{ids.path(object_name)}.Capacity")))
            except Exception as exc:  # noqa: BLE001
                check.error = str(exc)[:200]
            result.buffers.append(check)

        for check in result.links:
            if check.error:
                continue
            ok, value = self._try(f"-> string; return {ids.path(check.from_name)}.succ.Name")
            if ok:
                check.actual_successor = value
            else:
                check.error = str(value)

    # run 

    def run(self, package: FactoryMindExchange, timeout_seconds: float = 120.0) -> None:
        """Run the built model over Fabrivium's own operating window.
        """
        import time  # noqa: PLC0415 

        ids = self.ids
        assert ids is not None and self.app is not None
        controller = ids.event_controller
        horizon = package.resources.production_seconds_per_day

        self._try(f'-> string; {ids.path("Source")}.Interval := 1; return "ok"')
        self._try(f"-> string; {controller}.End := {horizon}; return \"ok\"")

        self.app.ResetSimulation(controller)
        self.app.StartSimulation(controller, True)  # True = fast forward
        started = time.time()
        while self.app.IsSimulationRunning() and time.time() - started < timeout_seconds:
            time.sleep(0.5)

    def execute(
        self,
        package: FactoryMindExchange,
        *,
        release_interval_seconds: float,
        units_to_release: int,
        horizon_seconds: float | None = None,
        timeout_seconds: float = 600.0,
    ) -> ExecutionResult:
        """Run the model that is currently loaded, and read the result back.
        """
        import time  # noqa: PLC0415 

        ids = self.ids
        outcome = ExecutionResult(
            release_interval_seconds=release_interval_seconds,
            units_to_release=units_to_release,
        )
        if self.app is None or ids is None:
            outcome.errors.append("Not connected to Plant Simulation.")
            return outcome

        horizon = (
            horizon_seconds
            if horizon_seconds is not None
            else package.resources.production_seconds_per_day
        )
        outcome.horizon_seconds = horizon
        controller = ids.event_controller
        source = ids.path("Source")

        for label, expr in (
            ("horizon", f"{controller}.End := {horizon} + {HORIZON_EPSILON}"),
            ("release interval", f"{source}.Interval := {release_interval_seconds}"),
            ("release quantity", f"{source}.Number := {units_to_release}"),
        ):
            ok, detail = self._try(f'-> string; {expr}; return "ok"')
            if not ok:
                outcome.errors.append(f"Could not set the {label}: {detail}")
        if outcome.errors:
            return outcome

        try:
            self.app.ResetSimulation(controller)
            self.app.StartSimulation(controller, True)  # True = fast forward
        except Exception as exc:  # noqa: BLE001
            outcome.errors.append(f"The simulation could not be started: {str(exc)[:200]}")
            return outcome

        started = time.time()
        while self.app.IsSimulationRunning() and time.time() - started < timeout_seconds:
            time.sleep(0.2)
        if self.app.IsSimulationRunning():
            outcome.timed_out = True
            outcome.errors.append(
                f"The simulation was still running after {timeout_seconds:.0f}s. No result is "
                f"reported for a run that did not finish."
            )
            try:
                self.app.StopSimulation()
            except Exception:  # noqa: BLE001 
                pass
            return outcome

        try:
            outcome.had_error = bool(self.app.HasSimulationError())
        except Exception:  # noqa: BLE001 
            outcome.had_error = None

        ok, value = self._try(f"-> string; return to_str({controller}.SimTime)")
        outcome.sim_time = str(value) if ok else None
        ok, reached = self._try(
            f'-> string; if {controller}.SimTime >= {horizon} then return "yes" else return "no" end'
        )
        outcome.reached_horizon = (str(reached) == "yes") if ok else None

        self._read_execution_statistics(package, outcome)

        if outcome.had_error:
            outcome.errors.append("Plant Simulation reported a simulation error.")
        if outcome.reached_horizon is False:
            outcome.errors.append(
                f"The run stopped at {outcome.sim_time} without reaching the {horizon:.0f}s horizon."
            )
        outcome.executed = (
            not outcome.errors
            and outcome.finished_units is not None
            and outcome.reached_horizon is not False
            and not outcome.had_error
        )
        return outcome

    def _read_execution_statistics(
        self, package: FactoryMindExchange, outcome: ExecutionResult
    ) -> None:
        ids = self.ids
        assert ids is not None

        def number(expr: str) -> float | None:
            ok, value = self._try(f"-> string; return to_str({expr})")
            if not ok:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        finished = number(f'{ids.path("Drain")}.StatNumIn')
        if finished is None:
            outcome.errors.append("Plant Simulation's drain did not return a readable unit count.")
        else:
            outcome.finished_units = int(finished)
        admitted = number(f'{ids.path("Source")}.StatNumOut')
        if admitted is not None:
            outcome.units_admitted = int(admitted)

        names = assign_identifiers(package)
        for station in package.stations:
            name = names[station.id]
            for attr, target in (
                ("StatWorkingPortion", outcome.station_utilisation),
                ("StatBlockingPortion", outcome.station_blocking),
                ("StatWaitingPortion", outcome.station_waiting),
            ):
                value = number(f"{ids.path(name)}.{attr}")
                if value is not None:
                    target[station.name] = value

    def read_results(self, package: FactoryMindExchange, result: HandoffResult) -> None:
        ids = self.ids
        assert ids is not None
        ok, value = self._try(f'-> string; return to_str({ids.path("Drain")}.StatNumIn)')
        if ok:
            try:
                result.simulated_units = float(value)
            except (TypeError, ValueError):
                result.errors.append(f"Drain returned a value that is not a number: {value!r}")
        result.simulated_seconds = package.resources.production_seconds_per_day

        names = assign_identifiers(package)
        for station in package.stations:
            ok, value = self._try(
                f'-> string; return to_str({ids.path(names[station.id])}.StatWorkingPortion)'
            )
            if ok:
                try:
                    result.station_utilisation[station.name] = float(value)
                except (TypeError, ValueError):
                    pass
