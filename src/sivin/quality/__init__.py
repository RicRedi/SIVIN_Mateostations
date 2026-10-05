"""Quality control checks and deployment detection (WP-1.5, MIGRATION_PLAN §2.7).

Entry point: :class:`QualityPipeline` built from :class:`QualityPipelineSettings`. The checks
live in :mod:`sivin.quality.checks`, deployment detection in :mod:`sivin.quality.deployment`;
the method is documented in ``docs/quality-control.md``.
"""

from sivin.quality.deployment import (
    DeploymentDetector,
    DeploymentResult,
    DeploymentSettings,
    DetectorMode,
)
from sivin.quality.events import DeploymentEvent, EventKind, EventSource, QualityEvent, Severity
from sivin.quality.pipeline import QualityPipeline, QualityPipelineSettings, QualityResult

__all__ = [
    "DeploymentDetector",
    "DeploymentEvent",
    "DeploymentResult",
    "DeploymentSettings",
    "DetectorMode",
    "EventKind",
    "EventSource",
    "QualityEvent",
    "QualityPipeline",
    "QualityPipelineSettings",
    "QualityResult",
    "Severity",
]
