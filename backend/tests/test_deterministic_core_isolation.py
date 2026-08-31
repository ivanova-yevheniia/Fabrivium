"""No language model can reach the deterministic engineering core."""

from __future__ import annotations

import ast
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: The deterministic engineering core: every module that produces a number
#: presented as a computed engineering fact.
CORE_MODULES: tuple[str, ...] = (
    # Simulation and its trace.
    "app.services.simulation",
    "app.services.simulation_trace",
    "app.services.playback_reconstruction",
    "app.services.scenario",
    "app.services.scenario_runner",
    # Capacity, takt, bottleneck, sensitivity.
    "app.services.capacity",
    "app.services.sensitivity",
    "app.services.buffer_sensitivity",
    "app.services.robustness",
    "app.services.goal_checker",
    # Concept -> factory conversion and the gates on it.
    "app.services.concept_validation",
    "app.services.concept_builder",
    "app.services.route_validator",
    "app.services.readiness",
    # Candidate search, evaluation, ranking and comparison.
    "app.services.candidate_generator",
    "app.services.candidate_evaluator",
    "app.services.ranking",
    "app.services.pareto",
    "app.services.comparison",
    "app.services.branch_comparison",
    "app.services.strategy_comparison",
    "app.services.strategy_cost",
    # Money.
    "app.services.budget",
    # Layout and geometry.
    "app.services.layout",
    "app.services.geometry",
    "app.services.constraints",
    "app.services.placement_search",
    # Machine pooling, staleness, and the Siemens handoff.
    "app.services.machine_pool",
    "app.services.project_revisions",
    "app.integrations.plant_simulation.adapter",
    "app.integrations.plant_simulation.from_factory",
    "app.integrations.plant_simulation.exchange_schema",
)

# Modules that MAY reach a provider.
LANGUAGE_BOUNDARY_MODULES: frozenset[str] = frozenset({
    "app.services.llm_integration",
    "app.services.conversation_orchestrator",
    "app.services.estimation",
    "app.services.product_intelligence",
    "app.skills.contract",
})

_FORBIDDEN_PREFIX = "app.llm"


def _module_path(module: str) -> pathlib.Path:
    relative = module.removeprefix("app.").replace(".", "/")
    return APP / f"{relative}.py"


def _imports_of(module: str) -> set[str]:
    """Every ``app.*`` module *module* imports directly."""
    path = _module_path(module)
    if not path.exists():
        pytest.fail(f"{module} is listed in this test but the file does not exist: {path}")

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app."):
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_from_import(module, node)
            if resolved is not None and resolved.startswith("app."):
                found.add(resolved)
    return found


def _resolve_from_import(module: str, node: ast.ImportFrom) -> str | None:
    """Absolute dotted name for a ``from … import …``, relative or not."""
    if not node.level:
        return node.module

    # Both cases drop the last component: `app.models.__init__` anchors on
    # the package `app.models`, and `app.services.simulation` anchors on its
    # containing package `app.services`. Each level beyond 1 drops one more.
    package = module.split(".")[:-1]
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, node.module]) if node.module else ".".join(base)


def _transitive_imports(module: str) -> dict[str, list[str]]:
    """
    Every ``app.*`` module reachable from *module*, mapped to the import chain that
    reaches it.
    """
    reached: dict[str, list[str]] = {}
    frontier: list[tuple[str, list[str]]] = [(module, [module])]

    while frontier:
        current, chain = frontier.pop()
        for imported in sorted(_imports_of(current)):
            if imported in reached:
                continue
            path = [*chain, imported]
            reached[imported] = path
            # is its own business, and app.llm.* has no app.services.*
            # dependencies to follow anyway.
            if imported.startswith(_FORBIDDEN_PREFIX):
                continue
            if _module_path(imported).exists():
                frontier.append((imported, path))
    return reached


@pytest.mark.parametrize("module", CORE_MODULES)
def test_no_core_module_can_reach_a_language_provider(module: str):
    """The whole point. Transitive, so a helper cannot smuggle it in."""
    reached = _transitive_imports(module)
    violations = {name: chain for name, chain in reached.items() if name.startswith(_FORBIDDEN_PREFIX)}
    assert not violations, (
        f"{module} can reach the language-provider layer:\n"
        + "\n".join(" -> ".join(chain) for chain in violations.values())
        + "\n\nA module that computes an engineering figure must not be able to call a "
          "model. If this import is genuinely needed, the computation belongs on the "
          "other side of the boundary — as a proposal a person accepts, not as a number "
          "a KPI reads."
    )


@pytest.mark.parametrize("module", CORE_MODULES)
def test_no_core_module_reaches_a_language_boundary_module(module: str):
    """Stronger, and the one that actually holds the line."""
    reached = _transitive_imports(module)
    violations = {
        name: chain for name, chain in reached.items() if name in LANGUAGE_BOUNDARY_MODULES
    }
    assert not violations, (
        f"{module} can reach a language-boundary module:\n"
        + "\n".join(" -> ".join(chain) for chain in violations.values())
    )


def test_the_language_boundary_modules_named_here_are_the_only_ones():
    """Catch a NEW module that starts calling a provider."""
    importers: set[str] = set()
    for path in APP.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        module = "app." + path.relative_to(APP).with_suffix("").as_posix().replace("/", ".")
        if module.startswith(_FORBIDDEN_PREFIX) or module == "app.main":
            continue
        if any(imported.startswith(_FORBIDDEN_PREFIX) for imported in _imports_of(module)):
            importers.add(module)

    assert importers == LANGUAGE_BOUNDARY_MODULES, (
        f"The set of modules importing {_FORBIDDEN_PREFIX} has changed.\n"
        f"  added:   {sorted(importers - LANGUAGE_BOUNDARY_MODULES)}\n"
        f"  removed: {sorted(LANGUAGE_BOUNDARY_MODULES - importers)}\n"
        "Add a new one to LANGUAGE_BOUNDARY_MODULES only after checking that what it "
        "gets from a model is a proposal somebody accepts, and not a figure."
    )


def test_the_core_list_is_not_silently_empty():
    """A guard on the guard: a refactor that renames every core module
    would otherwise leave this file passing vacuously."""
    assert len(CORE_MODULES) >= 25
    for module in CORE_MODULES:
        assert _module_path(module).exists(), module
