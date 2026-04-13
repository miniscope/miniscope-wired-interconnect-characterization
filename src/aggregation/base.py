from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.core.schemas import ExperimentDefinition


class BaseAggregator(ABC):
    """
    Abstract base class for cross-experiment aggregators.

    Aggregators operate on ALL experiments of a given type and produce
    summary tables, plots, or wiki payloads.
    """

    @abstractmethod
    def aggregate(
        self,
        experiment_dirs: list[Path],
        definition: ExperimentDefinition,
        output_dir: Path,
    ) -> dict[str, Path]:
        """
        Aggregate across experiments.

        Args:
            experiment_dirs: List of experiment folders (all same type)
            definition: The experiment type definition
            output_dir: Where to write aggregated outputs

        Returns:
            Mapping of output logical name -> output file path
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of this aggregator (must match definition.yaml aggregation name)."""
        ...
