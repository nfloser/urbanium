"""City-independent Urbanium core contracts."""

from urbanium.core.city import (
    CapabilityDefinition,
    CapabilitySupport,
    CityDefinition,
    LicenseMetadata,
    RedistributionStatus,
    SourceAuthority,
    SourceDefinition,
    SourceStatus,
)
from urbanium.core.component import (
    CapabilityRequirement,
    ComponentDescriptor,
    ComponentKind,
    ComponentOutput,
    ComponentRegistry,
    ComponentResolution,
    DerivedStateCategory,
    ResolutionReasonCode,
    UnavailableCapability,
    resolve_component,
)

__all__ = [
    "CapabilityDefinition",
    "CapabilityRequirement",
    "CapabilitySupport",
    "CityDefinition",
    "ComponentDescriptor",
    "ComponentKind",
    "ComponentOutput",
    "ComponentRegistry",
    "ComponentResolution",
    "DerivedStateCategory",
    "LicenseMetadata",
    "RedistributionStatus",
    "ResolutionReasonCode",
    "SourceAuthority",
    "SourceDefinition",
    "SourceStatus",
    "UnavailableCapability",
    "resolve_component",
]
