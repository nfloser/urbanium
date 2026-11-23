"""Shared helpers for agents that consume canonical provider reads."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from urbanium.core.execution import CapabilityInput, ComponentRunProblem
from urbanium.core.provider import Availability, ProviderResult


def provider_read(item: CapabilityInput) -> ProviderResult:
    """Recover the validated provider outcome packed by `observation_input`."""

    payload = item.payload
    if not isinstance(payload, dict) or "read" not in payload:
        raise ValueError(f"input '{item.capability_id}' is not a provider read")
    return ProviderResult.model_validate(payload["read"])


def source_problems(result: ProviderResult) -> list[ComponentRunProblem]:
    """Carry a degraded source reason into the derived run instead of hiding it."""

    if result.availability is Availability.DEGRADED and result.error is not None:
        return [ComponentRunProblem(code="source_degraded", message=result.error.message)]
    return []


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def decimal_text(value: Decimal, places: str | None = None) -> str:
    if places is not None:
        value = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return str(value)
