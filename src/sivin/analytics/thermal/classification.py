"""Classes of an index value given by increasing upper bounds (Winkler regions, Huglin classes).

A classification is a frozen pydantic model, so its bounds are index parameters that can be
overridden in the configuration. All classifications of this package use the same rule: a
value belongs to the first class whose upper bound it does not exceed (``value <= bound``);
values above the last bound belong to :attr:`IntervalClassification.top_label`.
"""

from __future__ import annotations

import logging
from itertools import pairwise
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)


class ClassBound(BaseModel):
    """One class with its inclusive upper bound.

    Attributes
    ----------
    label : str
        Machine-readable class label, e.g. ``"region_i"``.
    upper : float
        Inclusive upper bound in the unit of the classified index.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(min_length=1, description="Class label (machine-readable, no unit).")
    upper: float = Field(description="Inclusive upper bound, in the unit of the index.")


class IntervalClassification(BaseModel):
    """Ordered classes with increasing inclusive upper bounds and an open top class.

    Attributes
    ----------
    bounds : tuple of ClassBound
        Classes in increasing order of their upper bound.
    top_label : str
        Label of values above the last bound.

    Raises
    ------
    pydantic.ValidationError
        If the bounds are empty, not strictly increasing or labels repeat.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bounds: tuple[ClassBound, ...] = Field(
        min_length=1, description="Classes with strictly increasing inclusive upper bounds."
    )
    top_label: str = Field(min_length=1, description="Label of values above the last bound.")

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        uppers = [bound.upper for bound in self.bounds]
        if any(later <= earlier for earlier, later in pairwise(uppers)):
            raise ValueError(f"Class bounds must be strictly increasing, got {uppers}.")
        labels = [*(bound.label for bound in self.bounds), self.top_label]
        if len(set(labels)) != len(labels):
            raise ValueError(f"Class labels must be unique, got {labels}.")
        return self

    def classify(self, value: float) -> str:
        """Return the label of the class ``value`` falls into.

        Parameters
        ----------
        value : float
            Index value in the unit of the bounds.

        Returns
        -------
        str
            Label of the first class with ``value <= upper``, else :attr:`top_label`.
        """
        return next((bound.label for bound in self.bounds if value <= bound.upper), self.top_label)
