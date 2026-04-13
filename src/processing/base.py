from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.core.experiment_schemas import ExperimentRecord
from src.core.schemas import ExperimentDefinition


class BaseProcessor(ABC):
    """
    Abstract base class for experiment data processors.

    Each processor corresponds to a `processing_steps` entry in a
    definition.yaml. It takes an experiment directory and produces
    derived output files.
    """

    @abstractmethod
    def process(
        self,
        experiment_dir: Path,
        experiment: ExperimentRecord,
        definition: ExperimentDefinition,
        output_dir: Path,
    ) -> dict[str, Path]:
        """
        Process one experiment.

        Args:
            experiment_dir: Path to the experiment folder (contains experiment.yaml + data)
            experiment: The validated ExperimentRecord
            definition: The experiment type definition
            output_dir: Where to write derived outputs

        Returns:
            Mapping of output logical name -> output file path
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of this processor (must match definition.yaml step name)."""
        ...
