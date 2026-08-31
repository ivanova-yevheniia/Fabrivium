"""Phase 15B — Plant Simulation adapter."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.integrations.plant_simulation.adapter import (
    PlantSimulationAdapter,
    PlantSimulationUnavailable,
    simtalk_identifier,
)
from app.integrations.plant_simulation.exchange_schema import (
    EXCHANGE_SCHEMA_VERSION,
    ExchangeValueSource,
    FactoryMindExchange,
)
from app.integrations.plant_simulation.from_factory import exchange_from_factory
from app.integrations.plant_simulation.layout import (
    MAX_COORDINATE,
    MIN_ANCHOR,
    MIN_SEPARATION_UNITS,
    collisions,
    plan_layout,
)
from app.integrations.plant_simulation.localization import GERMAN, LocalizationError, detect
from app.models.factory import Factory
from app.models.layout import FactoryLayout
from app.services.simulation import run_simulation

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


# A fake Plant Simulation

class FakePlantSim:
    """Minimal stand-in that behaves like the real product's German locale."""

    def __init__(self, *, fail_on: str | None = None, locale: str = "de"):
        self.fail_on = fail_on
        self.locale = locale
        self.objects: dict[str, dict] = {}
        self.links: dict[str, str] = {}
        self.saved_to: str | None = None
        self.executed: list[str] = []
        self.simulation_started = False

    # RemoteControl surface
    def SetNoMessageBox(self, *_): ...
    def SetTrustModels(self, *_): ...
    def SetVisible(self, *_): ...
    def SetSuppressStartOf3D(self, *_): ...
    def SetSuppressOpenGL(self, *_): ...
    def NewModel(self): self.objects.clear(); self.links.clear()
    def ResetSimulation(self, *_): ...
    def IsSimulationRunning(self): return False
    def Quit(self): ...

    def StartSimulation(self, *_):
        if self.fail_on == "simulation":
            raise RuntimeError("simulation failed")
        self.simulation_started = True

    def SaveModel(self, path):
        if self.fail_on == "save":
            raise RuntimeError("disk full")
        self.saved_to = path
        if self.fail_on == "save_produces_nothing":
            # The nastiest real failure mode: the call returns, and no file appears.
            return

        objects, links = dict(self.objects), dict(self.links)
        if self.fail_on == "save_drops_a_station":
            # A save that "succeeds" while losing content.
            for name in list(objects):
                if name not in ("Source", "Drain"):
                    objects.pop(name)
                    break

        # A real save produces a multi-megabyte OLE compound file.
        payload = json.dumps({"objects": objects, "links": links}).encode("utf-8")
        pathlib.Path(path).write_bytes(
            b"\xd0\xcf\x11\xe0" + payload + b"\n" + b"0" * 200_000
        )

    def CloseModel(self):
        # The real product requires this before loading over an open model.
        self.objects.clear()
        self.links.clear()

    def LoadModel(self, path):
        if self.fail_on == "reopen":
            raise RuntimeError("the file is corrupt")
        raw = pathlib.Path(path).read_bytes()
        payload = raw[4:].split(b"\n", 1)[0]
        state = json.loads(payload.decode("utf-8"))
        # Loading REPLACES the session, exactly as it does in the real
        # product: whatever is in the file is now what can be read back.
        self.objects = state["objects"]
        self.links = state["links"]

    def ExecuteSimTalk(self, expr: str):
        self.executed.append(expr)
        root = ".Modelle.Modell" if self.locale == "de" else ".Models.Model"
        lib = ".Materialfluss" if self.locale == "de" else ".MaterialFlow"
        station = "Einzelstation" if self.locale == "de" else "Station"

        # Localisation probes: answer ONLY for this fake's own locale, the
        # way the real product does. An unknown locale answers nothing, so
        # detection must fail rather than silently pick a language.
        if expr.startswith("-> string; return .") and expr.endswith(".Name") and ".succ" not in expr:
            target = expr[len("-> string; return "):-len(".Name")]
            if target in (root, f"{lib}.{station}"):
                if self.locale not in ("de", "en"):
                    raise self._com_error("Unbekannter Bezeichner")
                return target.split(".")[-1]
            leaf = target.split(".")[-1]
            if target == f"{root}.{leaf}" and leaf in self.objects:
                return self.objects[leaf]["Name"]
            raise self._com_error(f"Unbekannter Bezeichner '{leaf}'")

        if "createObject" in expr:
            if self.fail_on == "create":
                raise self._com_error("Ungültiger Bezeichner")
            name = expr.split('o.Name := "')[1].split('"')[0]
            entry = {"Name": name}
            # GEOMETRY, reproduced as the real product behaves — this is the behaviour
            # that hid the Phase 15D defect.
            args = expr.split("createObject(")[1].split(")")[0].split(",")
            raw_x, raw_y = float(args[1]), float(args[2])
            if raw_x > 30_000 or raw_y > 30_000:
                raise self._com_error("Das Objekt würde sich außerhalb des Netzwerks befinden.")
            entry["XPos"] = max(20, int(raw_x))
            entry["YPos"] = max(20, int(raw_y))
            if "ProcTime :=" in expr:
                entry["ProcTime"] = float(expr.split("o.ProcTime := ")[1].split(";")[0])
            if "Capacity :=" in expr:
                wanted = int(float(expr.split("o.Capacity := ")[1].split(";")[0]))
                # The real product REFUSES Capacity != 1 on a SingleProc —
                # "Die Kapazität kann nicht geändert werden." — while a
                # Buffer accepts it happily. The refusal is reproduced per
                # CLASS, because that distinction is exactly what forces the
                # adapter to pick ParallelProc for a multi-unit stage.
                single_proc = "Einzelstation" in expr or ".MaterialFlow.Station" in expr
                if single_proc and wanted != 1:
                    raise self._com_error("Die Kapazität kann nicht geändert werden.")
                entry["Capacity"] = wanted
            if "XDim :=" in expr:
                # A ParallelProc's parallelism comes from XDim x YDim, and
                # Capacity is DERIVED from them — exactly as measured against
                # 2404. The fake derives it too, so a test cannot pass by
                # writing a capacity the real product would never accept.
                x = int(float(expr.split("o.XDim := ")[1].split(";")[0]))
                y = int(float(expr.split("o.YDim := ")[1].split(";")[0])) if "YDim :=" in expr else 1
                entry["XDim"], entry["YDim"] = x, y
                entry["Capacity"] = x * y
            self.objects[name] = entry
            return name

        # Geometry read-back
        if ".XPos)" in expr and ".YPos)" in expr:
            name = expr.split(".XPos)")[0].rsplit(".", 1)[-1]
            if name not in self.objects:
                raise self._com_error(f"Unbekannter Bezeichner '{name}'")
            if self.fail_on == "verify_position":
                return "20,20"
            return f"{self.objects[name]['XPos']},{self.objects[name]['YPos']}"

        # User-defined equipment metadata
        if "createAttr(" in expr or (".FM_" in expr and ":=" in expr):
            if self.fail_on == "equipment":
                raise self._com_error("Das Attribut kann nicht erstellt werden.")
            for statement in expr.split(";"):
                if ".FM_" not in statement or ":=" not in statement:
                    continue
                target, value = statement.split(":=", 1)
                name = target.strip().split(".")[-2]
                attr = target.strip().split(".")[-1]
                if name in self.objects:
                    self.objects[name][attr] = value.strip().strip('"')
            return "ok"

        if expr.startswith("-> string; return ") and ".FM_" in expr:
            path = expr[len("-> string; return "):].strip()
            name, attr = path.split(".")[-2], path.split(".")[-1]
            if name not in self.objects or attr not in self.objects[name]:
                raise self._com_error(f"Unbekannter Bezeichner '{attr}'")
            if self.fail_on == "verify_equipment":
                return "Some Other Maker"
            return self.objects[name][attr]

        if ".connect(" in expr:
            if self.fail_on == "connect":
                raise self._com_error("Das Objekt kann nicht erstellt werden.")
            inner = expr.split(".connect(")[1].split(")")[0]
            a, b = (p.strip().split(".")[-1] for p in inner.split(","))
            self.links[a] = b
            return "ok"

        if ".succ.Name" in expr:
            name = expr.rsplit(".succ", 1)[0].rsplit(".", 1)[-1]
            if self.fail_on == "verify_link":
                return "WrongSuccessor"
            return self.links.get(name, "")

        if "StatNumIn" in expr:
            # A drain that counted nothing: the model is connected on paper
            # and no material ever crossed it.
            return "0" if self.fail_on == "drain_empty" else "1105"
        if "StatWorkingPortion" in expr:
            return "0.9994"
        return ""

    def GetValue(self, path: str):
        name = path.split(".")[-2]
        attr = path.split(".")[-1]
        if name not in self.objects:
            raise RuntimeError(f"unknown object {name}")
        if self.fail_on == "verify_cycle" and attr == "ProcTime":
            return 99.0
        if self.fail_on == "verify_capacity" and attr == "Capacity":
            return 99
        return self.objects[name].get(attr, 0)

    @staticmethod
    def _com_error(message: str) -> Exception:
        exc = RuntimeError("com error")
        exc.args = (-2147352567, "Exception", (0, "IRemoteControl::ExecuteSimTalk", message, None, 0, 0), None)
        return exc


def package() -> FactoryMindExchange:
    factory = Factory.model_validate(json.loads((EXAMPLES / "electronics_line.json").read_text(encoding="utf-8")))
    layout = FactoryLayout.model_validate(
        json.loads((EXAMPLES / "electronics_line_layout.json").read_text(encoding="utf-8"))
    )
    return exchange_from_factory(factory, factory.products[0].id, layout=layout)


def adapter_with(fake: FakePlantSim) -> PlantSimulationAdapter:
    adapter = PlantSimulationAdapter(dispatch=lambda _prog_id: fake)
    adapter.connect()
    return adapter


# Identifier sanitisation

class TestSimTalkIdentifier:
    def test_spaces_become_underscores(self):
        # The real product rejects "Assembly Station" outright, and every
        # machine in FactoryMind's own demo factory is named that way.
        assert simtalk_identifier("Assembly Station") == "Assembly_Station"

    def test_leading_digit_is_prefixed(self):
        assert simtalk_identifier("3-Axis Mill") == "S_3_Axis_Mill"

    def test_illegal_characters_are_dropped_not_transliterated(self):
        assert simtalk_identifier("Q/C Check (fast)") == "Q_C_Check_fast"

    def test_is_deterministic(self):
        assert simtalk_identifier("Assembly Station") == simtalk_identifier("Assembly Station")


# Exchange model

class TestExchangeModel:
    def test_carries_the_route_order_and_cycle_times_from_the_route(self):
        pkg = package()
        assert [s.name for s in pkg.stations] == [
            "Assembly Station", "Screwdriving Station", "Inspection Station", "Packaging Station",
        ]
        assert [s.cycle_time_seconds for s in pkg.stations] == [35.0, 52.0, 30.0, 25.0]

    def test_flow_links_follow_the_route(self):
        pkg = package()
        assert [(l.from_id, l.to_id) for l in pkg.flow] == [
            ("m-assembly", "m-screwdriving"),
            ("m-screwdriving", "m-inspection"),
            ("m-inspection", "m-packaging"),
        ]

    def test_operating_window_is_stated_so_two_simulators_are_comparable(self):
        # 2 shifts x 8 h. Without this a receiving tool runs 24 h and the
        # comparison is meaningless.
        assert package().resources.production_seconds_per_day == 57600.0

    def test_an_unknown_price_stays_unknown_and_never_becomes_zero(self):
        factory = Factory.model_validate(json.loads((EXAMPLES / "electronics_line.json").read_text(encoding="utf-8")))
        stripped = factory.model_copy(update={
            "machines": [m.model_copy(update={"purchase_cost": None}) for m in factory.machines]
        })
        pkg = exchange_from_factory(stripped, stripped.products[0].id)
        for station in pkg.stations:
            assert station.purchase_cost.value is None
            assert station.purchase_cost.source is ExchangeValueSource.UNKNOWN

    def test_a_genuine_zero_is_exported_as_a_price_not_as_unknown(self):
        """The other half, which the model could not express before."""
        factory = Factory.model_validate(json.loads((EXAMPLES / "electronics_line.json").read_text(encoding="utf-8")))
        owned = factory.model_copy(update={
            "machines": [m.model_copy(update={"purchase_cost": 0.0}) for m in factory.machines]
        })
        pkg = exchange_from_factory(owned, owned.products[0].id)
        for station in pkg.stations:
            assert station.purchase_cost.value == 0.0
            assert station.purchase_cost.source is ExchangeValueSource.CUSTOMER

    def test_only_wired_buffers_are_exported(self):
        # An unwired buffer has no effect in FactoryMind's simulation either;
        # exporting it would imply a constraint that does not exist.
        pkg = package()
        assert len(pkg.buffers) == 3

    def test_factorymind_results_travel_as_a_summary_for_comparison(self):
        factory = Factory.model_validate(json.loads((EXAMPLES / "electronics_line.json").read_text(encoding="utf-8")))
        factory = factory.model_copy(update={
            "products": [p.model_copy(update={"demand_per_day": 1900.0}) for p in factory.products]
        })
        result = run_simulation(factory, factory.products[0].id)
        pkg = exchange_from_factory(factory, factory.products[0].id, simulation=result)
        assert pkg.simulation_summary is not None
        assert pkg.simulation_summary.completed_units_per_day == 1105
        assert pkg.simulation_summary.bottleneck_station_id == "m-screwdriving"

    def test_schema_is_versioned(self):
        assert package().schema_version == EXCHANGE_SCHEMA_VERSION


# Localisation

class TestLocalization:
    def test_detects_german(self):
        known = {".Modelle.Modell", ".Materialfluss.Einzelstation"}
        ids = detect(lambda expr: (any(k in expr for k in known), "Modell"))
        assert ids.language == "de"
        assert ids.connector == "Kante"

    def test_detects_english(self):
        known = {".Models.Model", ".MaterialFlow.Station"}
        ids = detect(lambda expr: (any(k in expr for k in known), "Model"))
        assert ids.language == "en"
        assert ids.connector == "Connector"

    def test_stops_rather_than_guessing_when_nothing_resolves(self):
        with pytest.raises(LocalizationError):
            detect(lambda _expr: (False, "unknown identifier"))


# Handoff

class TestHandoff:
    def test_builds_and_verifies_the_full_line(self, tmp_path):
        fake = FakePlantSim()
        destination = tmp_path / "x.spp"
        result = adapter_with(fake).build(package(), save_path=str(destination))

        assert result.fully_verified is True
        assert result.stations_verified == 4
        # The demo line wires a buffer between each consecutive pair, and each
        # one is transferred: a Plant Simulation station has NO input queue,
        # so a model without them is a zero-buffer blocking line rather than
        # the unbounded-queue line FactoryMind simulates.
        assert result.buffers_verified == 3
        assert result.links_verified == 8  # Source + 4 stations + 3 buffers + Drain
        assert fake.saved_to == str(destination)
        # "Saved" is a claim about the filesystem, so it is checked there.
        assert destination.exists()
        assert result.model_path == str(destination)
        assert result.model_bytes and result.model_bytes > 100_000

    def test_a_save_that_produces_no_file_is_not_complete(self, tmp_path):
        # The failure this check exists for: SaveModel returns, nothing is
        # written, and the old code reported a green success with a path
        # pointing at nothing.
        fake = FakePlantSim(fail_on="save_produces_nothing")
        destination = tmp_path / "ghost.spp"
        result = adapter_with(fake).build(package(), save_path=str(destination))

        assert result.fully_verified is False
        assert result.model_path is None
        assert any("no file exists" in e for e in result.errors)

    def test_the_saved_file_is_reopened_and_read_back(self, tmp_path):
        # The handoff artefact is the file, so the file is what gets
        # verified — not the session that produced it.
        fake = FakePlantSim()
        destination = tmp_path / "roundtrip.spp"
        result = adapter_with(fake).build(package(), save_path=str(destination))

        assert result.saved_model_verified is True
        assert result.reopened_stations_verified == 4
        assert result.reopened_buffers_verified == 3
        assert result.reopened_links_verified == 8
        assert result.fully_verified is True

    def test_a_save_that_silently_loses_a_station_is_not_complete(self, tmp_path):
        # In-session verification passes; the file disagrees.
        fake = FakePlantSim(fail_on="save_drops_a_station")
        destination = tmp_path / "lossy.spp"
        result = adapter_with(fake).build(package(), save_path=str(destination))

        assert result.stations_verified == 4          # the session was fine
        assert result.saved_model_verified is False   # the file was not
        assert result.fully_verified is False
        assert any("does not match" in e for e in result.errors)

    def test_a_file_that_cannot_be_reopened_is_not_complete(self, tmp_path):
        fake = FakePlantSim(fail_on="reopen")
        destination = tmp_path / "corrupt.spp"
        result = adapter_with(fake).build(package(), save_path=str(destination))

        assert result.saved_model_verified is False
        assert result.fully_verified is False
        assert any("could not be re-opened" in e for e in result.errors)

    def test_a_truncated_save_is_not_complete(self, tmp_path):
        fake = FakePlantSim()
        destination = tmp_path / "tiny.spp"
        destination.write_bytes(b"not a model")

        class Truncating(type(fake)):
            def SaveModel(self, path):
                self.saved_to = path
                pathlib.Path(path).write_bytes(b"too small")

        result = adapter_with(Truncating()).build(package(), save_path=str(destination))

        assert result.fully_verified is False
        assert any("too small" in e for e in result.errors)

    def test_transfers_factorymind_cycle_times_exactly(self):
        fake = FakePlantSim()
        adapter_with(fake).build(package())
        assert fake.objects["Screwdriving_Station"]["ProcTime"] == 52.0
        assert fake.objects["Assembly_Station"]["ProcTime"] == 35.0

    def test_builds_source_and_drain_around_the_stations(self):
        fake = FakePlantSim()
        adapter_with(fake).build(package())
        assert "Source" in fake.objects and "Drain" in fake.objects
        assert fake.links["Source"] == "Assembly_Station"
        assert fake.links["Packaging_Station"] == "Drain"


# Failure must be safe

class TestFailuresAreSafe:
    def test_missing_plant_simulation_is_reported_as_unavailable(self):
        def refuse(_prog_id):
            raise OSError("Class not registered")

        adapter = PlantSimulationAdapter(dispatch=refuse)
        with pytest.raises(PlantSimulationUnavailable) as exc:
            adapter.connect()
        assert "not installed" in str(exc.value)

    def test_object_creation_failure_is_never_reported_as_complete(self):
        result = adapter_with(FakePlantSim(fail_on="create")).build(package())
        assert result.fully_verified is False
        assert result.errors

    def test_connection_failure_is_never_reported_as_complete(self):
        result = adapter_with(FakePlantSim(fail_on="connect")).build(package())
        assert result.fully_verified is False
        assert result.links_verified == 0

    def test_a_wrong_cycle_time_read_back_fails_verification(self):
        # The decisive test: the writes "succeed", but the model does not
        # contain what FactoryMind sent, so the handoff is not complete.
        result = adapter_with(FakePlantSim(fail_on="verify_cycle")).build(package())
        assert result.fully_verified is False
        assert result.stations_verified == 0

    def test_a_wrong_successor_read_back_fails_verification(self):
        result = adapter_with(FakePlantSim(fail_on="verify_link")).build(package())
        assert result.fully_verified is False
        assert result.links_verified == 0

    def test_save_failure_is_reported(self):
        result = adapter_with(FakePlantSim(fail_on="save")).build(package(), save_path="C:/tmp/x.spp")
        assert result.fully_verified is False
        assert any("save" in e.lower() for e in result.errors)

    def test_unknown_localisation_stops_the_handoff(self):
        fake = FakePlantSim(locale="klingon")
        result = adapter_with(fake).build(package())
        assert result.fully_verified is False
        assert any("does not answer to any identifier set" in e for e in result.errors)


# Isolation

def test_the_integration_never_imports_the_simulator():
    """The dependency runs one way."""
    for module in ["adapter", "exchange_schema", "localization"]:
        source = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app" / "integrations" / "plant_simulation" / f"{module}.py"
        ).read_text(encoding="utf-8")
        assert "app.services.simulation" not in source
        assert "from app.services" not in source


class TestTheWritingReleaseIsRecorded:
    """Audit §11 — an .spp is version-bound, so who wrote it matters."""

    def test_an_unreportable_version_stays_unknown_rather_than_guessed(self, tmp_path):
        # The test double is a plain Python class with no Siemens type
        # library behind it, which is exactly the "cannot tell" case.
        fake = FakePlantSim()
        result = adapter_with(fake).build(package(), save_path=str(tmp_path / "x.spp"))

        assert result.product_version is None
        # UNKNOWN must not block a handoff that is otherwise verified — it
        # is a fact about our knowledge, not a defect in the model.
        assert result.fully_verified is True

    def test_a_reported_version_is_carried_through(self, tmp_path):
        from app.integrations.plant_simulation.adapter import _product_version

        class TypeLibraryBacked:
            """Stands in for a win32com-generated proxy, which documents the
            product in the class and module docstrings."""

            __doc__ = "Plant Simulation 2404 IRemoteControl Interface"

        assert _product_version(TypeLibraryBacked()) == "Plant Simulation 2404"

    def test_an_unrelated_docstring_is_not_mistaken_for_a_version(self):
        from app.integrations.plant_simulation.adapter import _product_version

        class Unrelated:
            __doc__ = "Some other COM component"

        assert _product_version(Unrelated()) is None


# Phase 15D — geometry The defect these pin: the exporter passed FactoryMind's floor
# coordinates (metres) straight into `createObject(frame, x, y)`.

class TestLayoutTransform:
    @staticmethod
    def _neighbours(chain: list[str]) -> dict[str, tuple[str | None, str | None]]:
        return {
            name: (
                chain[i - 1] if i else None,
                chain[i + 1] if i + 1 < len(chain) else None,
            )
            for i, name in enumerate(chain)
        }

    def test_metre_coordinates_are_not_frame_coordinates(self):
        """The exact failing case: a 6-stage line laid out by concept_builder."""
        chain = ["Source"] + [f"S{i}" for i in range(6)] + ["Drain"]
        # concept_builder's own numbers for a six-stage screwdriving line.
        concept = {f"S{i}": (4.25 + i * 5.5, 2.667) for i in range(6)}
        plan = plan_layout(chain, concept_points=concept, neighbours=self._neighbours(chain))

        assert plan.min_separation >= MIN_SEPARATION_UNITS
        assert collisions(plan.positions) == []
        # Nothing may land on or under the clamp boundary, or the product
        # would move it without saying so.
        assert all(x > MIN_ANCHOR and y > MIN_ANCHOR for x, y in plan.positions.values())
        assert len(set(plan.positions.values())) == len(chain)

    def test_the_conceptual_arrangement_is_preserved_when_it_can_be(self):
        chain = ["Source", "A", "B", "C", "Drain"]
        concept = {"A": (0.0, 0.0), "B": (7.0, 0.0), "C": (14.0, 0.0)}
        plan = plan_layout(chain, concept_points=concept, neighbours=self._neighbours(chain))

        assert plan.mode == "normalised-concept"
        # Evenly spaced in the concept, evenly spaced in the frame.
        xs = [plan.positions[n][0] for n in ("A", "B", "C")]
        assert xs[1] - xs[0] == xs[2] - xs[1]

    def test_y_is_mirrored_so_the_hall_does_not_arrive_back_to_front(self):
        # FactoryMind's Y grows away across the floor; a frame's Y grows downwards.
        chain = ["Source", "Front", "Back", "Drain"]
        concept = {"Front": (0.0, 0.0), "Back": (0.0, 10.0)}
        plan = plan_layout(chain, concept_points=concept, neighbours=self._neighbours(chain))
        assert plan.positions["Back"][1] < plan.positions["Front"][1]

    def test_coincident_concept_points_fall_back_to_a_generated_line(self):
        chain = ["Source", "A", "B", "Drain"]
        concept = {"A": (5.0, 5.0), "B": (5.0, 5.0)}
        plan = plan_layout(chain, concept_points=concept, neighbours=self._neighbours(chain))

        assert plan.mode == "generated-line"
        assert plan.reason and "same conceptual coordinate" in plan.reason
        assert collisions(plan.positions) == []

    def test_a_missing_coordinate_is_not_invented(self):
        chain = ["Source", "A", "B", "Drain"]
        plan = plan_layout(chain, concept_points=None)
        assert plan.mode == "generated-line"
        assert collisions(plan.positions) == []

    def test_a_long_line_wraps_instead_of_running_off_the_frame(self):
        chain = ["Source"] + [f"S{i}" for i in range(60)] + ["Drain"]
        plan = plan_layout(chain)
        assert collisions(plan.positions) == []
        assert all(x <= MAX_COORDINATE and y <= MAX_COORDINATE for x, y in plan.positions.values())
        # It actually wrapped rather than running out sideways.
        assert len({y for _x, y in plan.positions.values()}) > 1

    def test_the_generated_line_is_deterministic(self):
        chain = ["Source", "A", "B", "Drain"]
        assert plan_layout(chain).positions == plan_layout(chain).positions


class TestGeometryVerification:
    def test_the_built_model_has_distinct_non_overlapping_positions(self, tmp_path):
        fake = FakePlantSim()
        result = adapter_with(fake).build(package(), save_path=str(tmp_path / "x.spp"))

        assert result.geometry_verified is True
        assert result.overlaps == []
        assert result.positions_verified == len(result.positions)
        placed = {(p.x_actual, p.y_actual) for p in result.positions}
        assert len(placed) == len(result.positions)
        assert result.layout_min_separation >= MIN_SEPARATION_UNITS

    def test_a_clamped_position_is_never_reported_as_complete(self, tmp_path):
        """The defect itself: Plant Simulation moves an object and says nothing."""
        fake = FakePlantSim(fail_on="verify_position")
        result = adapter_with(fake).build(package(), save_path=str(tmp_path / "x.spp"))

        assert result.fully_verified is False
        assert result.geometry_verified is False
        # Every station is present and every connection is there — which is
        # exactly why the old handoff called this a success.
        assert result.stations_verified == 4
        assert result.links_verified == 8
        assert any("geometrically wrong" in e or "overlap" in e for e in result.errors)

    def test_positions_are_verified_in_the_saved_file_too(self, tmp_path):
        fake = FakePlantSim()
        result = adapter_with(fake).build(package(), save_path=str(tmp_path / "x.spp"))
        assert result.reopened_positions
        assert all(p.verified for p in result.reopened_positions)


class TestRouteVerification:
    def test_the_route_is_walked_from_source_to_drain(self, tmp_path):
        fake = FakePlantSim()
        result = adapter_with(fake).build(package(), save_path=str(tmp_path / "x.spp"))

        assert result.route_complete is True
        assert result.route_walked[0] == "Source"
        assert result.route_walked[-1] == "Drain"
        assert result.disconnected == []
        # Source + 4 stations + 3 buffers + Drain.
        assert len(result.route_walked) == 9

    def test_a_broken_route_is_not_reported_as_complete(self, tmp_path):
        fake = FakePlantSim(fail_on="connect")
        result = adapter_with(fake).build(package(), save_path=str(tmp_path / "x.spp"))

        assert result.fully_verified is False
        assert result.route_complete is not True


class TestTraversalVerification:
    def test_a_unit_reaching_the_drain_is_recorded_as_evidence(self, tmp_path):
        fake = FakePlantSim()
        result = adapter_with(fake).build(package(), save_path=str(tmp_path / "x.spp"))

        assert result.traversal_verified is True
        assert result.traversal_units and result.traversal_units >= 1

    def test_a_route_no_unit_can_travel_is_not_a_successful_handoff(self, tmp_path):
        fake = FakePlantSim(fail_on="drain_empty")
        result = adapter_with(fake).build(package(), save_path=str(tmp_path / "x.spp"))

        assert result.traversal_verified is False
        assert result.fully_verified is False
        assert any("No unit reached the drain" in e for e in result.errors)

    def test_the_run_can_be_skipped_without_weakening_the_other_checks(self, tmp_path):
        fake = FakePlantSim()
        result = adapter_with(fake).build(
            package(), save_path=str(tmp_path / "x.spp"), verify_traversal=False
        )
        assert result.traversal_verified is None
        assert result.fully_verified is True


class TestEquipmentMetadata:
    @staticmethod
    def _package_with_equipment() -> FactoryMindExchange:
        factory = Factory.model_validate(
            json.loads((EXAMPLES / "electronics_line.json").read_text(encoding="utf-8"))
        )
        layout = FactoryLayout.model_validate(
            json.loads((EXAMPLES / "electronics_line_layout.json").read_text(encoding="utf-8"))
        )
        product = factory.products[0]
        station_id = product.route[1].machine_id
        return exchange_from_factory(
            factory,
            product.id,
            layout=layout,
            equipment_selections={
                station_id: {
                    "manufacturer": "WEBER Schraubautomaten GmbH",
                    "model": "SER Series 30",
                    "source_url": "https://example.invalid/ser-30",
                }
            },
        )

    def test_the_equipment_under_consideration_reaches_the_model(self, tmp_path):
        fake = FakePlantSim()
        pkg = self._package_with_equipment()
        result = adapter_with(fake).build(pkg, save_path=str(tmp_path / "x.spp"))

        assert result.fully_verified is True
        assert result.equipment_verified == 1
        carried = result.equipment[0]
        assert carried.manufacturer_actual == "WEBER Schraubautomaten GmbH"
        assert carried.model_actual == "SER Series 30"

    def test_manufacturer_values_never_overwrite_the_verified_parameters(self, tmp_path):
        """Metadata is metadata."""
        fake = FakePlantSim()
        pkg = self._package_with_equipment()
        station = next(s for s in pkg.stations if s.selected_model)
        adapter_with(fake).build(pkg, save_path=str(tmp_path / "x.spp"))

        stored = fake.objects[simtalk_identifier(station.name)]
        assert stored["ProcTime"] == station.cycle_time_seconds
        assert stored["Capacity"] == station.capacity
        # The model says so in its own words, so the receiving engineer
        # cannot mistake one for the other.
        assert "NOT applied" in stored["FM_ParameterSource"]

    def test_metadata_that_did_not_survive_the_transfer_fails_the_handoff(self, tmp_path):
        fake = FakePlantSim(fail_on="verify_equipment")
        result = adapter_with(fake).build(
            self._package_with_equipment(), save_path=str(tmp_path / "x.spp")
        )
        assert result.equipment_verified == 0
        assert result.fully_verified is False


class TestMultiCapacityStations:
    """A capacity-N stage must be N INDEPENDENT servers, not a batch of N."""

    @staticmethod
    def _package_with_a_six_place_stage() -> FactoryMindExchange:
        base = package()
        stations = [
            s.model_copy(update={"capacity": 6}) if i == 1 else s
            for i, s in enumerate(base.stations)
        ]
        return base.model_copy(update={"stations": stations})

    def test_a_capacity_six_stage_is_not_built_as_a_batch_station(self, tmp_path):
        fake = FakePlantSim()
        pkg = self._package_with_a_six_place_stage()
        multi = next(s for s in pkg.stations if s.capacity > 1)
        name = simtalk_identifier(multi.name)

        adapter_with(fake).build(pkg, save_path=str(tmp_path / "x.spp"))

        create = next(
            expr for expr in fake.executed
            if "createObject" in expr and f'o.Name := "{name}"' in expr
        )
        assert "Parallelstation" not in create
        assert "Puffer" in create
        # The two values that make it N servers rather than one, both of
        # them read back afterwards.
        assert f"o.ProcTime := {multi.cycle_time_seconds}" in create
        assert "o.Capacity := 6" in create

    def test_the_capacity_and_cycle_time_still_verify(self, tmp_path):
        fake = FakePlantSim()
        pkg = self._package_with_a_six_place_stage()
        result = adapter_with(fake).build(pkg, save_path=str(tmp_path / "x.spp"))

        assert result.fully_verified is True
        multi = next(s for s in pkg.stations if s.capacity > 1)
        check = next(s for s in result.stations if s.station_id == multi.id)
        assert check.capacity_actual == 6
        assert check.cycle_time_actual == multi.cycle_time_seconds
