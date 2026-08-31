"""
Connects the generic ``app.llm.LLMProvider`` to Fabrivium's THREE existing structured-
output agent stubs for Fabrivium Phase 7A:
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from app.llm.errors import LLMMalformedResponseError, LLMProviderError
from app.llm.models import LLMInvocationRecord, LLMInvocationResult, LLMRequest
from app.llm.provider import LLMProvider
from app.llm.schema import compact_schema
from app.models.agent import FactoryContext, PlanningRequirements
from app.models.conversation import RequirementUpdate
from app.models.explanation import ExplanationContext, ExplanationResult, PlanningExplanation
from app.models.factory import Factory
from app.models.layout import FactoryLayout
from app.models.orchestrator import PlanningSessionState
from app.models.planning_agent import PlanningAgentResult, PlanningContext, PlanningProposal
from app.services.explanation_agent import (
    DEFAULT_EXPLANATION_SYSTEM_PROMPT,
    DeterministicExplanationAgent,
    LLMExplanationAgent,
    generate_explanation,
)
from app.services.planning_agent import (
    DEFAULT_PLANNING_SYSTEM_PROMPT,
    DeterministicPlanningAgent,
    LLMPlanningAgent,
    PlanningAgent,
    run_planning_agent,
)
from app.services.planning_orchestrator import PlanningOrchestrator
from app.services.conversation_parser import DEFAULT_UPDATE_SYSTEM_PROMPT
from app.services.requirements_parser import (
    DEFAULT_SYSTEM_PROMPT,
    DeterministicFallbackRequirementsParser,
    LLMRequirementsParser,
    RequirementsParseResult,
)

_LOGGER = logging.getLogger("factorymind.llm")

OnInvocation = Callable[[LLMInvocationRecord], None]


# Authoritative response schemas passed to the provider via
# ``LLMRequest.response_schema``.
_REQUIREMENTS_SCHEMA: dict = compact_schema(PlanningRequirements)
_EXPLANATION_SCHEMA: dict = compact_schema(PlanningExplanation)
_PROPOSALS_SCHEMA: dict = {"type": "array", "items": compact_schema(PlanningProposal)}
_UPDATE_SCHEMA: dict = compact_schema(RequirementUpdate)


def _as_proposal_list(data: object) -> list[dict]:
    """
    Normalize a raw planning payload into the ``list[dict]`` the Phase 5B
    ``LLMPlanningAgent`` contract expects.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and len(data) == 1:
        only_value = next(iter(data.values()))
        if isinstance(only_value, list):
            return only_value
    return [data]  # type: ignore[list-item]


def _require_dict(data: object, *, provider: LLMProvider, agent_name: str) -> dict:
    """Return the value as a dict. Raise if a provider returned any other JSON type."""
    if not isinstance(data, dict):
        raise LLMMalformedResponseError(
            f"Expected a JSON object for {agent_name}, got {type(data).__name__}.",
            provider_name=provider.provider_name, model_name=provider.model_name,
        )
    return data


def _default_on_invocation(record: LLMInvocationRecord) -> None:
    """
    Structured log line only — never the prompt/response CONTENT, never a secret (there
    is none to log: an ``LLMInvocationRecord`` has no credential field at all, and no
    provider error message reaching here carries one either).
    """
    _LOGGER.info(
        "llm_invocation agent=%s provider=%s model=%s success=%s attempts=%d "
        "latency_ms=%.1f fallback_used=%s validation_passed=%s error_type=%s "
        "prompt_tokens=%s completion_tokens=%s total_tokens=%s request_id=%s",
        record.agent, record.provider_name, record.model_name, record.success,
        record.attempts, record.latency_ms, record.fallback_used,
        record.validation_passed, record.error_type,
        record.prompt_tokens, record.completion_tokens, record.total_tokens, record.request_id,
    )


def _success_record(agent_name: str, result: "LLMInvocationResult") -> LLMInvocationRecord:
    """
    Build the audit record for one successful provider call, carrying whatever usage
    metadata the provider actually reported (Phase 7B section 13).
    """
    usage = result.response.usage or {}
    return LLMInvocationRecord(
        agent=agent_name,
        provider_name=result.response.provider_name,
        model_name=result.response.model_name,
        success=True,
        attempts=result.attempts,
        latency_ms=result.response.latency_ms,
        fallback_used=False,
        validation_passed=None,
        error_type=None,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        request_id=result.response.request_id,
    )


# 1. completion_fn adapters


def build_requirements_completion_fn(
    provider: LLMProvider, *, agent_name: str = "requirements", on_invocation: OnInvocation | None = None,
) -> Callable[[str, "FactoryContext | None"], dict]:
    notify = on_invocation or _default_on_invocation

    def completion_fn(prompt: str, factory_context: FactoryContext | None) -> dict:
        request = LLMRequest(
            system_prompt=DEFAULT_SYSTEM_PROMPT, user_prompt=prompt,
            response_schema=_REQUIREMENTS_SCHEMA,
            metadata={"agent": agent_name},
        )
        start = time.monotonic()
        try:
            result = provider.generate_structured(request, response_model=None)
            data = _require_dict(result.parsed, provider=provider, agent_name=agent_name)
        except LLMProviderError as exc:
            notify(LLMInvocationRecord(
                agent=agent_name, provider_name=provider.provider_name, model_name=provider.model_name,
                success=False, attempts=1, latency_ms=(time.monotonic() - start) * 1000,
                fallback_used=False, validation_passed=None, error_type=type(exc).__name__,
            ))
            raise
        notify(_success_record(agent_name, result))
        return data

    return completion_fn


def build_planning_completion_fn(
    provider: LLMProvider, *, agent_name: str = "planning", on_invocation: OnInvocation | None = None,
) -> Callable[[str, PlanningContext], list[dict]]:
    notify = on_invocation or _default_on_invocation

    def completion_fn(prompt: str, context: PlanningContext) -> list[dict]:
        request = LLMRequest(
            system_prompt=DEFAULT_PLANNING_SYSTEM_PROMPT, user_prompt=prompt,
            response_schema=_PROPOSALS_SCHEMA,
            metadata={"agent": agent_name},
        )
        start = time.monotonic()
        try:
            result = provider.generate_structured(request, response_model=None)
        except LLMProviderError as exc:
            notify(LLMInvocationRecord(
                agent=agent_name, provider_name=provider.provider_name, model_name=provider.model_name,
                success=False, attempts=1, latency_ms=(time.monotonic() - start) * 1000,
                fallback_used=False, validation_passed=None, error_type=type(exc).__name__,
            ))
            raise
        notify(_success_record(agent_name, result))
        return _as_proposal_list(result.parsed)

    return completion_fn


def build_update_completion_fn(
    provider: LLMProvider, *, agent_name: str = "conversation_update", on_invocation: OnInvocation | None = None,
) -> Callable[[str, object], dict]:
    """Completion function for the Phase 7C conversational update parser."""
    notify = on_invocation or _default_on_invocation

    def completion_fn(prompt: str, context: object) -> dict:
        request = LLMRequest(
            system_prompt=DEFAULT_UPDATE_SYSTEM_PROMPT, user_prompt=prompt,
            response_schema=_UPDATE_SCHEMA,
            metadata={"agent": agent_name},
        )
        start = time.monotonic()
        try:
            result = provider.generate_structured(request, response_model=None)
            data = _require_dict(result.parsed, provider=provider, agent_name=agent_name)
        except LLMProviderError as exc:
            notify(LLMInvocationRecord(
                agent=agent_name, provider_name=provider.provider_name, model_name=provider.model_name,
                success=False, attempts=1, latency_ms=(time.monotonic() - start) * 1000,
                fallback_used=False, validation_passed=None, error_type=type(exc).__name__,
            ))
            raise
        notify(_success_record(agent_name, result))
        return data

    return completion_fn


def build_explanation_completion_fn(
    provider: LLMProvider, *, agent_name: str = "explanation", on_invocation: OnInvocation | None = None,
) -> Callable[[str, ExplanationContext], dict]:
    notify = on_invocation or _default_on_invocation

    def completion_fn(prompt: str, context: ExplanationContext) -> dict:
        request = LLMRequest(
            system_prompt=DEFAULT_EXPLANATION_SYSTEM_PROMPT, user_prompt=prompt,
            response_schema=_EXPLANATION_SCHEMA,
            metadata={"agent": agent_name},
        )
        start = time.monotonic()
        try:
            result = provider.generate_structured(request, response_model=None)
            data = _require_dict(result.parsed, provider=provider, agent_name=agent_name)
        except LLMProviderError as exc:
            notify(LLMInvocationRecord(
                agent=agent_name, provider_name=provider.provider_name, model_name=provider.model_name,
                success=False, attempts=1, latency_ms=(time.monotonic() - start) * 1000,
                fallback_used=False, validation_passed=None, error_type=type(exc).__name__,
            ))
            raise
        notify(_success_record(agent_name, result))
        return data

    return completion_fn


# 2. *_with_fallback — the integration surface app.main calls


def parse_requirements_with_fallback(
    user_request: str,
    factory_context: FactoryContext | None,
    provider: LLMProvider | None,
    *,
    on_invocation: OnInvocation | None = None,
) -> tuple[RequirementsParseResult, bool]:
    """Returns (result, fallback_used)."""
    if provider is None:
        return DeterministicFallbackRequirementsParser().parse(user_request, factory_context), False

    completion_fn = build_requirements_completion_fn(provider, on_invocation=on_invocation)
    agent = LLMRequirementsParser(completion_fn=completion_fn)
    try:
        result = agent.parse(user_request, factory_context)
    except LLMProviderError:
        fallback = DeterministicFallbackRequirementsParser().parse(user_request, factory_context)
        return fallback, True

    # agent.parse() already turns a malformed-but-transport-successful
    # response into a safe MEET_DEMAND default with structured_output_valid
    # =False (Phase 5A's own, unmodified behavior) — treat that the same as
    # a fallback for provenance-reporting purposes.
    return result, not result.structured_output_valid


def run_planning_agent_with_fallback(
    context: PlanningContext,
    requirements: PlanningRequirements,
    factory: Factory,
    provider: LLMProvider | None,
    *,
    optimizer_grounded: bool = True,
    on_invocation: OnInvocation | None = None,
) -> tuple[PlanningAgentResult, bool]:
    """Returns (result, fallback_used)."""
    if provider is None:
        return run_planning_agent(DeterministicPlanningAgent(), context, requirements, factory, optimizer_grounded), False

    completion_fn = build_planning_completion_fn(provider, on_invocation=on_invocation)
    agent = LLMPlanningAgent(completion_fn=completion_fn)
    try:
        result = run_planning_agent(agent, context, requirements, factory, optimizer_grounded)
    except LLMProviderError:
        fallback = run_planning_agent(DeterministicPlanningAgent(), context, requirements, factory, optimizer_grounded)
        return fallback, True

    return result, False


def explain_with_fallback(
    context: ExplanationContext,
    provider: LLMProvider | None,
    *,
    on_invocation: OnInvocation | None = None,
) -> tuple[ExplanationResult, bool]:
    """Returns (result, fallback_used)."""
    if provider is None:
        result = generate_explanation(DeterministicExplanationAgent(), context)
        return result, False

    completion_fn = build_explanation_completion_fn(provider, on_invocation=on_invocation)
    agent = LLMExplanationAgent(completion_fn=completion_fn)
    try:
        result = generate_explanation(agent, context)
    except LLMProviderError:
        fallback = generate_explanation(DeterministicExplanationAgent(), context)
        return fallback, True

    # generate_explanation() already falls back to DeterministicExplanationAgent
    # internally on a hallucination-guard violation or structured-output
    # ValidationError (Phase 5D's own, unmodified behavior) — its own
    # `used_fallback` field already reports that correctly.
    return result, result.used_fallback


def run_planning_session_with_fallback(
    factory: Factory,
    product_id: str,
    requirements: PlanningRequirements,
    provider: LLMProvider | None,
    *,
    layout: FactoryLayout | None = None,
    max_iterations: int = 5,
    on_invocation: OnInvocation | None = None,
) -> tuple[PlanningSessionState, bool]:
    """
    Run a FULL ``PlanningOrchestrator`` session with the LLM-backed planning agent,
    falling back to a full deterministic re-run on ANY provider failure, at ANY point in
    the (possibly multi-iteration) loop.
    """
    if provider is None:
        session = PlanningOrchestrator().run(factory, product_id, requirements, layout=layout, max_iterations=max_iterations)
        return session, False

    completion_fn = build_planning_completion_fn(provider, on_invocation=on_invocation)
    llm_agent: PlanningAgent = LLMPlanningAgent(completion_fn=completion_fn)
    try:
        session = PlanningOrchestrator().run(
            factory, product_id, requirements, layout=layout, max_iterations=max_iterations, planning_agent=llm_agent,
        )
    except LLMProviderError:
        session = PlanningOrchestrator().run(factory, product_id, requirements, layout=layout, max_iterations=max_iterations)
        return session, True

    return session, False
