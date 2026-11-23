"""Reusable deterministic agents that derive knowledge from canonical city state.

Agents depend on capabilities and canonical contracts only. They never call
provider APIs and never name a city.
"""

from urbanium.agents.relations import DerivedRelation, derive_relations
from urbanium.agents.temperature_spread import TemperatureSpreadAgent
from urbanium.agents.water_level_class import WaterLevelClassAgent
from urbanium.agents.water_level_trend import WaterLevelTrendAgent
from urbanium.core.execution import DeterministicComponent


def default_agents() -> tuple[DeterministicComponent, ...]:
    """Agents shipped with Urbanium, in a stable order."""

    return (TemperatureSpreadAgent(), WaterLevelTrendAgent(), WaterLevelClassAgent())


__all__ = [
    "DerivedRelation",
    "TemperatureSpreadAgent",
    "WaterLevelClassAgent",
    "WaterLevelTrendAgent",
    "default_agents",
    "derive_relations",
]
