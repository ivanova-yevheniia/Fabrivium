"""An operation is not a workstation."""

from __future__ import annotations

import pytest

from app.models.concept import (
    CellExecutionMode,
    ConceptBuffer,
    ConceptOperationGroup,
    ConceptStage,
    FactoryConceptDraft,
    SourcedFloat,
    SourcedInt,
    ValueSource,
)
from app.services.concept_validation import (
    ConceptNotReadyError,
    concept_to_factory,
    operation_group_errors,
    validate_concept,
)
from app.services.simulation import run_simulation


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def stage(sid: str, name: str, cycle: float, operators: int = 1, capacity: int = 1) -> ConceptStage:
    return ConceptStage(
        id=sid,
        name=name,
        process_type="assembly",
        cycle_time=SourcedFloat.of(cycle, ValueSource.ENGINEER),
        capacity=SourcedInt.of(capacity, ValueSource.ENGINEER),
        operators_required=SourcedInt.of(operators, ValueSource.ENGINEER),
    )


def draft_of(*stages: ConceptStage, groups: list[ConceptOperationGroup] | None = None,
             buffers: list[ConceptBuffer] | None = None) -> FactoryConceptDraft:
    return FactoryConceptDraft(
        name="Line",
        product_name="Widget",
        production_target=SourcedFloat.of(100.0, ValueSource.CUSTOMER),
        shifts_per_day=SourcedInt.of(1, ValueSource.CUSTOMER),
        hours_per_shift=SourcedFloat.of(8.0, ValueSource.CUSTOMER),
        operators_available=SourcedInt.of(4, ValueSource.CUSTOMER),
        stages=list(stages),
        buffers=buffers or [],
        operation_groups=groups or [],
    )


THREE = (stage("s1", "Place", 10.0), stage("s2", "Fasten", 20.0), stage("s3", "Pack", 30.0))


# 1. The default is unchanged


def test_a_concept_with_no_groups_compiles_exactly_as_before():
    factory, _ = concept_to_factory(draft_of(*THREE))
    assert [m.id for m in factory.machines] == ["s1", "s2", "s3"]
    assert [s.machine_id for s in factory.products[0].route] == ["s1", "s2", "s3"]
    assert [m.cycle_time for m in factory.machines] == [10.0, 20.0, 30.0]


def test_no_groups_means_no_grouping_content_at_all():
    """So a project that never groups hashes precisely as it did before."""
    from app.services.project_revisions import _grouping_content

    assert _grouping_content(draft_of(*THREE)) is None


# 2. One resource, several operations


def cell(*sids: str, gid: str = "cell-1", name: str = "Assembly cell") -> ConceptOperationGroup:
    return ConceptOperationGroup(id=gid, name=name, stage_ids=list(sids), basis="Engineer decision.")


def test_two_operations_can_share_one_resource():
    factory, _ = concept_to_factory(draft_of(*THREE, groups=[cell("s1", "s2")]))
    assert [m.id for m in factory.machines] == ["cell-1", "s3"]
    assert [s.machine_id for s in factory.products[0].route] == ["cell-1", "s3"]


def test_cell_work_content_is_the_sum_and_never_less():
    """Property 2. A cell that beat the sum would be claiming concurrency."""
    factory, _ = concept_to_factory(draft_of(*THREE, groups=[cell("s1", "s2")]))
    cell_machine = next(m for m in factory.machines if m.id == "cell-1")
    assert cell_machine.cycle_time == 30.0
    assert factory.products[0].route[0].cycle_time == 30.0


def test_the_whole_route_can_be_one_cell():
    factory, _ = concept_to_factory(draft_of(*THREE, groups=[cell("s1", "s2", "s3")]))
    assert len(factory.machines) == 1
    assert factory.machines[0].cycle_time == 60.0
    assert len(factory.products[0].route) == 1


def test_operators_are_the_maximum_not_the_sum():
    """Sequential means one operation at a time, so the cell is staffed for
    its most demanding operation — not for all of them at once."""
    stages = (stage("s1", "A", 10.0, operators=1), stage("s2", "B", 20.0, operators=2))
    factory, _ = concept_to_factory(draft_of(*stages, groups=[cell("s1", "s2")]))
    assert factory.machines[0].operators_required == 2


def test_capacity_is_the_tightest_member():
    stages = (stage("s1", "A", 10.0, capacity=3), stage("s2", "B", 20.0, capacity=1))
    factory, _ = concept_to_factory(draft_of(*stages, groups=[cell("s1", "s2")]))
    assert factory.machines[0].capacity == 1


def test_an_unpriced_member_makes_the_cell_unpriced_not_partly_priced():
    priced = stage("s1", "A", 10.0)
    priced = priced.model_copy(update={"purchase_cost": SourcedFloat.of(1000.0, ValueSource.ENGINEER)})
    unpriced = stage("s2", "B", 20.0)
    factory, _ = concept_to_factory(draft_of(priced, unpriced, groups=[cell("s1", "s2")]))
    assert factory.machines[0].purchase_cost is None


# 3. Buffers


def test_a_buffer_inside_a_cell_is_dropped():
    """One resource doing two operations back to back has no queue between
    them; keeping the buffer would add capacity the grouped line lacks."""
    buffers = [ConceptBuffer(id="b1", name="b", upstream_stage_id="s1", downstream_stage_id="s2",
                             capacity=SourcedInt.of(50, ValueSource.CATALOG_DEFAULT))]
    factory, _ = concept_to_factory(draft_of(*THREE, groups=[cell("s1", "s2")], buffers=buffers))
    assert factory.buffers == []


def test_a_buffer_at_a_cell_boundary_is_remapped_to_the_cell():
    buffers = [ConceptBuffer(id="b2", name="b", upstream_stage_id="s2", downstream_stage_id="s3",
                             capacity=SourcedInt.of(50, ValueSource.CATALOG_DEFAULT))]
    factory, _ = concept_to_factory(draft_of(*THREE, groups=[cell("s1", "s2")], buffers=buffers))
    assert len(factory.buffers) == 1
    assert factory.buffers[0].upstream_machine_id == "cell-1"
    assert factory.buffers[0].downstream_machine_id == "s3"


# 4. A grouped concept actually simulates


def test_a_grouped_concept_simulates():
    factory, product_id = concept_to_factory(draft_of(*THREE, groups=[cell("s1", "s2")]))
    result = run_simulation(factory, product_id)
    assert result.completed_units > 0


def test_grouping_reduces_throughput_here_and_the_result_is_explainable():
    """Three stations pipeline; one cell of two does not."""
    serial, pid_a = concept_to_factory(draft_of(*THREE))
    grouped, pid_b = concept_to_factory(draft_of(*THREE, groups=[cell("s1", "s2")]))
    serial_out = run_simulation(serial, pid_a).completed_units
    grouped_out = run_simulation(grouped, pid_b).completed_units
    assert grouped_out <= serial_out


# 5. Validation — a bad grouping is repaired, not answered


def test_a_non_contiguous_group_is_refused():
    errors = operation_group_errors(draft_of(*THREE, groups=[cell("s1", "s3")]))
    assert any("contiguous" in e for e in errors)


def test_a_stage_in_two_groups_is_refused():
    groups = [cell("s1", "s2"), cell("s2", "s3", gid="cell-2", name="Second")]
    errors = operation_group_errors(draft_of(*THREE, groups=groups))
    assert any("two operation groups" in e for e in errors)


def test_a_group_naming_an_unknown_stage_is_refused():
    errors = operation_group_errors(draft_of(*THREE, groups=[cell("s1", "nope")]))
    assert any("not in the route" in e for e in errors)


def test_a_group_id_may_not_collide_with_a_stage_id():
    errors = operation_group_errors(draft_of(*THREE, groups=[cell("s1", "s2", gid="s3")]))
    assert any("must be distinct" in e for e in errors)


def test_a_broken_grouping_blocks_simulation_rather_than_compiling():
    bad = draft_of(*THREE, groups=[cell("s1", "s3")])
    assert not validate_concept(bad).simulation_ready
    with pytest.raises(ConceptNotReadyError):
        concept_to_factory(bad)


def test_a_valid_grouping_leaves_the_concept_ready():
    assert validate_concept(draft_of(*THREE, groups=[cell("s1", "s2")])).simulation_ready


# 6. Grouping invalidates verification


def test_grouping_changes_the_simulation_inputs_channel():
    """Property 3: the grouped line is a different factory."""
    from app.services.project_revisions import _grouping_content

    before = _grouping_content(draft_of(*THREE))
    after = _grouping_content(draft_of(*THREE, groups=[cell("s1", "s2")]))
    assert before != after


def test_regrouping_differently_is_also_a_change():
    from app.services.project_revisions import _grouping_content

    one = _grouping_content(draft_of(*THREE, groups=[cell("s1", "s2")]))
    two = _grouping_content(draft_of(*THREE, groups=[cell("s2", "s3")]))
    assert one != two


def test_removing_a_group_returns_to_the_ungrouped_content():
    """Grouping is reversible, and undoing it is recognised as undoing it."""
    from app.services.project_revisions import _grouping_content

    assert _grouping_content(draft_of(*THREE, groups=[])) is _grouping_content(draft_of(*THREE))


# 7. The one execution mode is the only one, on purpose


def test_sequential_is_the_only_execution_mode():
    """Parallelism inside a cell must arrive as an explicit second mode, not
    as a factor quietly applied to this one."""
    assert [m.value for m in CellExecutionMode] == ["SEQUENTIAL"]


# 8. The HTTP surface — grouping is a real capability, not an internal type


class TestGroupingApi:
    """Grouping has to be reachable by a person, or it is not a capability."""

    @staticmethod
    def _draft() -> dict:
        return {
            "name": "L", "product_name": "W",
            "production_target": {"value": 100, "source": "CUSTOMER"},
            "shifts_per_day": {"value": 1, "source": "CUSTOMER"},
            "hours_per_shift": {"value": 8.0, "source": "CUSTOMER"},
            "operators_available": {"value": 4, "source": "CUSTOMER"},
            "stages": [
                {"id": f"s{i}", "name": n, "process_type": "assembly",
                 "cycle_time": {"value": t, "source": "ENGINEER"},
                 "capacity": {"value": 1, "source": "ENGINEER"},
                 "operators_required": {"value": 1, "source": "ENGINEER"}}
                for i, (n, t) in enumerate([("Place", 10.0), ("Fasten", 20.0), ("Pack", 30.0)], 1)
            ],
            "buffers": [],
        }

    def test_grouping_returns_a_ready_concept(self, client):
        r = client.post("/concept/group-operations", json={
            "draft": self._draft(), "stage_ids": ["s1", "s2"],
            "name": "Assembly cell", "basis": "One bench does both.",
        })
        assert r.status_code == 200
        body = r.json()
        assert [g["stage_ids"] for g in body["draft"]["operation_groups"]] == [["s1", "s2"]]
        assert body["validation"]["simulation_ready"] is True

    def test_the_engineers_reason_is_required(self, client):
        r = client.post("/concept/group-operations", json={
            "draft": self._draft(), "stage_ids": ["s1", "s2"], "name": "Cell", "basis": "",
        })
        assert r.status_code == 422

    def test_a_non_contiguous_grouping_is_refused_with_the_reason(self, client):
        r = client.post("/concept/group-operations", json={
            "draft": self._draft(), "stage_ids": ["s1", "s3"], "name": "Bad", "basis": "x",
        })
        assert r.status_code == 422
        assert "contiguous" in r.json()["detail"]

    def test_grouping_is_reversible(self, client):
        grouped = client.post("/concept/group-operations", json={
            "draft": self._draft(), "stage_ids": ["s1", "s2"],
            "name": "Assembly cell", "basis": "One bench does both.",
        }).json()["draft"]
        group_id = grouped["operation_groups"][0]["id"]

        r = client.post("/concept/ungroup-operations", json={"draft": grouped, "group_id": group_id})
        assert r.status_code == 200
        assert r.json()["draft"]["operation_groups"] == []

    def test_ungrouping_something_that_is_not_grouped_is_a_404(self, client):
        r = client.post("/concept/ungroup-operations",
                        json={"draft": self._draft(), "group_id": "cell-nope"})
        assert r.status_code == 404
