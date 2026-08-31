"""P0 — the manufacturing process stays editable after it has been reviewed."""

from __future__ import annotations

import pytest

from app.models.process_draft import (
    ManufacturingProcessDraft,
    OperationStatus,
    ProposedOperation,
)
from app.models.product import FactStatus
from app.services.process_editing import (
    OperationNotFound,
    add_operation,
    edit_operation,
    link_to_requirements,
    remove_operation,
    reorder_operations,
    restore_operation,
    unlink_requirements,
)


def _operation(op_id: str, name: str, **overrides) -> ProposedOperation:
    fields = {
        "id": op_id,
        "process_type": "assembly",
        "name": name,
        "description": f"{name} the unit.",
        "basis": "Derived from a product fact.",
        "source_fact_keys": [],
        "fact_status": FactStatus.RULE_DERIVED,
        "status": OperationStatus.PROPOSED,
    }
    fields.update(overrides)
    return ProposedOperation(**fields)


@pytest.fixture
def draft() -> ManufacturingProcessDraft:
    return ManufacturingProcessDraft(
        product_name="Compact electronics controller",
        operations=[
            _operation("op-1", "Assembly"),
            _operation("op-2", "Screwdriving", process_type="screwdriving"),
            _operation("op-3", "Packaging", process_type="packaging"),
        ],
    )


class TestRestore:
    def test_a_rejected_operation_can_be_brought_back(self, draft):
        rejected = remove_operation(draft, "op-2")
        assert rejected.operations[1].status is OperationStatus.REJECTED

        restored = restore_operation(rejected, "op-2")
        assert restored.operations[1].status is OperationStatus.MODIFIED
        assert restored.operations[1].fact_status is FactStatus.ENGINEER_VERIFIED

    def test_restoring_says_who_put_it_back(self, draft):
        restored = restore_operation(remove_operation(draft, "op-2"), "op-2")
        assert "Restored by the engineer" in restored.operations[1].basis
        # The planner's own reasoning is still there underneath it.
        assert "Derived from a product fact." in restored.operations[1].basis

    def test_restoring_something_that_was_never_rejected_changes_nothing(self, draft):
        assert restore_operation(draft, "op-1") is draft

    def test_an_unknown_operation_is_reported(self, draft):
        with pytest.raises(OperationNotFound):
            restore_operation(draft, "op-nope")


class TestUnlink:
    def test_a_link_made_in_error_can_be_taken_back(self, draft):
        linked = link_to_requirements(draft, "op-3", ["identification_label"])
        assert linked.operations[2].source_fact_keys == ["identification_label"]

        unlinked = unlink_requirements(linked, "op-3", ["identification_label"])
        assert unlinked.operations[2].source_fact_keys == []

    def test_unlinking_is_recorded_rather_than_silent(self, draft):
        linked = link_to_requirements(draft, "op-3", ["identification_label", "torque_spec"])
        unlinked = unlink_requirements(linked, "op-3", ["identification_label"])

        assert unlinked.operations[2].source_fact_keys == ["torque_spec"]
        assert "unlinked this operation from: identification_label" in unlinked.operations[2].basis

    def test_unlinking_something_that_was_not_linked_changes_nothing(self, draft):
        assert unlink_requirements(draft, "op-1", ["identification_label"]) is draft


class TestReorder:
    def test_the_route_takes_the_order_the_engineer_chose(self, draft):
        reordered = reorder_operations(draft, ["op-2", "op-1", "op-3"])
        assert [op.id for op in reordered.operations] == ["op-2", "op-1", "op-3"]

    def test_a_reorder_that_drops_an_operation_is_refused(self, draft):
        """A deletion wearing a reorder's clothes."""
        with pytest.raises(ValueError, match="every operation exactly once"):
            reorder_operations(draft, ["op-2", "op-1"])

    def test_a_reorder_that_invents_an_operation_is_refused(self, draft):
        with pytest.raises(ValueError):
            reorder_operations(draft, ["op-1", "op-2", "op-3", "op-4"])

    def test_reordering_preserves_every_operation_intact(self, draft):
        reordered = reorder_operations(draft, ["op-3", "op-2", "op-1"])
        assert {op.id: op for op in reordered.operations} == {op.id: op for op in draft.operations}


class TestEditFields:
    def test_the_description_can_be_corrected_without_rewriting_the_basis(self, draft):
        """C1 — 'what it does' and 'why it exists' are different fields, and
        correcting the first must not overwrite the chain back to the product
        fact held in the second."""
        edited = edit_operation(draft, "op-2", description="Drive six M3 screws to 0.6 Nm.")

        assert edited.operations[1].description == "Drive six M3 screws to 0.6 Nm."
        assert edited.operations[1].basis == "Derived from a product fact."
        assert edited.operations[1].status is OperationStatus.MODIFIED
        assert edited.operations[1].fact_status is FactStatus.ENGINEER_VERIFIED

    def test_repeated_operations_per_unit_can_be_changed(self, draft):
        edited = edit_operation(draft, "op-2", repeated_operations=6)
        assert edited.operations[1].repeated_operations == 6

    def test_zero_repetitions_is_refused(self, draft):
        with pytest.raises(ValueError):
            edit_operation(draft, "op-2", repeated_operations=0)


class TestProvenanceSurvivesEditing:
    def test_an_engineer_added_operation_is_never_marked_rule_derived(self, draft):
        """C2 — a human decision must not be filed under a machine's name."""
        added = add_operation(
            draft,
            name="Label application",
            process_type="labeling",
            basis="The specification requires a unique identification label.",
            source_fact_keys=["identification_label"],
        )
        new = added.operations[-1]
        assert new.fact_status is FactStatus.STATED
        assert new.fact_status is not FactStatus.RULE_DERIVED
        assert new.status is OperationStatus.ACCEPTED

    def test_a_rule_derived_operation_stays_rule_derived_until_someone_acts(self, draft):
        """C3 — and only an engineer's own act changes it."""
        assert draft.operations[0].fact_status is FactStatus.RULE_DERIVED
        untouched = reorder_operations(draft, ["op-2", "op-1", "op-3"])
        assert untouched.operations[1].fact_status is FactStatus.RULE_DERIVED

    def test_editing_keeps_the_original_proposal_readable(self, draft):
        edited = edit_operation(draft, "op-1", basis="The enclosure is snap-fit, not screwed.")
        assert "originally: Derived from a product fact." in edited.operations[0].basis


class TestApi:
    """The same edits over HTTP, with coverage recomputed in the response."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from app.main import app

        return TestClient(app)

    @pytest.fixture
    def understanding(self) -> dict:
        from app.models.product import ProductUnderstanding

        return ProductUnderstanding(
            product_name="Compact electronics controller",
            description="A controller in a plastic enclosure.",
        ).model_dump(mode="json")

    def test_restore_endpoint(self, client, understanding, draft):
        payload = {
            "understanding": understanding,
            "draft": remove_operation(draft, "op-2").model_dump(mode="json"),
            "operation_id": "op-2",
        }
        response = client.post("/product/process/restore-operation", json=payload)
        assert response.status_code == 200
        assert response.json()["draft"]["operations"][1]["status"] == "MODIFIED"

    def test_unlink_endpoint(self, client, understanding, draft):
        linked = link_to_requirements(draft, "op-3", ["identification_label"])
        payload = {
            "understanding": understanding,
            "draft": linked.model_dump(mode="json"),
            "operation_id": "op-3",
            "fact_keys": ["identification_label"],
        }
        response = client.post("/product/process/unlink-requirement", json=payload)
        assert response.status_code == 200
        assert response.json()["draft"]["operations"][2]["source_fact_keys"] == []

    def test_reorder_endpoint(self, client, understanding, draft):
        payload = {
            "understanding": understanding,
            "draft": draft.model_dump(mode="json"),
            "ordered_ids": ["op-3", "op-1", "op-2"],
        }
        response = client.post("/product/process/reorder", json=payload)
        assert response.status_code == 200
        assert [op["id"] for op in response.json()["draft"]["operations"]] == ["op-3", "op-1", "op-2"]

    def test_reorder_endpoint_refuses_a_lossy_order(self, client, understanding, draft):
        payload = {
            "understanding": understanding,
            "draft": draft.model_dump(mode="json"),
            "ordered_ids": ["op-3", "op-1"],
        }
        assert client.post("/product/process/reorder", json=payload).status_code == 422

    def test_edit_endpoint_accepts_a_description(self, client, understanding, draft):
        payload = {
            "understanding": understanding,
            "draft": draft.model_dump(mode="json"),
            "operation_id": "op-2",
            "description": "Drive six M3 screws to 0.6 Nm.",
        }
        response = client.post("/product/process/edit-operation", json=payload)
        assert response.status_code == 200
        operation = response.json()["draft"]["operations"][1]
        assert operation["description"] == "Drive six M3 screws to 0.6 Nm."
        assert operation["basis"] == "Derived from a product fact."
