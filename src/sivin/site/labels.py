"""Labels of the published variables and climate indices in Czech, German and English.

The web portal takes the names of variables and indices from ``manifest.json`` (MIGRATION_PLAN
§2.6, ``label: {cs, de, en}``), not from its own dictionaries.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from sivin.core.schema import Column

logger = logging.getLogger(__name__)

LANGUAGES: Final = ("cs", "de", "en")
"""Languages of every label, in the order written."""

INDEX_DOC_TEMPLATE: Final = "docs/indices/{index_id}.md"
"""Path of an index's documentation page, relative to the repository root."""


@dataclass(frozen=True, slots=True)
class Label:
    """A name in Czech, German and English.

    Attributes
    ----------
    cs, de, en : str
        The name in each language.
    """

    cs: str
    de: str
    en: str

    @classmethod
    def same(cls, text: str) -> Label:
        """Return a label with the same text in every language.

        Parameters
        ----------
        text : str
            The text.

        Returns
        -------
        Label
            ``Label(text, text, text)``.
        """
        return cls(text, text, text)

    def as_dict(self) -> dict[str, str]:
        """Return ``{"cs": ..., "de": ..., "en": ...}``.

        Returns
        -------
        dict of str to str
            Language code → text, in :data:`LANGUAGES` order.
        """
        return {"cs": self.cs, "de": self.de, "en": self.en}


@dataclass(frozen=True, slots=True)
class VariableSpec:
    """A measured variable listed in ``manifest.json``.

    Attributes
    ----------
    id : str
        Column name of the raw files, e.g. ``"temp_c"``.
    unit : str
        Unit symbol.
    label : Label
        Display name.
    """

    id: str
    unit: str
    label: Label

    def as_dict(self) -> dict[str, object]:
        """Return the manifest entry ``{"id", "unit", "label"}``.

        Returns
        -------
        dict
            The entry.
        """
        return {"id": self.id, "unit": self.unit, "label": self.label.as_dict()}


VARIABLES: Final = (
    VariableSpec(str(Column.TEMP), "°C", Label("Teplota", "Temperatur", "Temperature")),
    VariableSpec(str(Column.RH), "%", Label("Vlhkost", "Feuchtigkeit", "Humidity")),
    VariableSpec(str(Column.PRECIP), "mm", Label("Srážky", "Niederschlag", "Precipitation")),
    VariableSpec(
        str(Column.BATTERY), "V", Label("Napětí baterie", "Batteriespannung", "Battery voltage")
    ),
)
"""The variables of the raw files, in column order (temperature and humidity as in §2.6;
precipitation and battery voltage since WP-1.9)."""

INDEX_LABELS: Final[Mapping[str, Label]] = MappingProxyType(
    {
        "bedd": Label(
            "Biologicky efektivní stupňodny",
            "Biologisch effektive Gradtage",
            "Biologically effective degree-days",
        ),
        "botrytis_broome": Label(
            "Riziko plísně šedé (Broome)", "Botrytis-Risiko (Broome)", "Botrytis risk (Broome)"
        ),
        "budburst": Label("Odhad rašení", "Geschätzter Austrieb", "Budburst estimate"),
        "cool_night": Label("Index chladných nocí", "Kühle-Nächte-Index", "Cool night index"),
        "dew_point": Label("Rosný bod", "Taupunkt", "Dew point"),
        "dtr_ripening": Label(
            "Denní rozpětí teplot při zrání",
            "Tägliche Temperaturspanne in der Reife",
            "Diurnal temperature range during ripening",
        ),
        "frost": Label(
            "Mrazové hodiny a noci", "Froststunden und -nächte", "Frost hours and nights"
        ),
        "gdd_winkler": Label(
            "Sumy aktivních teplot (Winkler)", "Gradtage (Winkler)", "Growing degree-days (Winkler)"
        ),
        "gfv": Label(
            "Model kvetení a zaměkání (GFV)",
            "Blüte-Véraison-Modell (GFV)",
            "Grapevine Flowering Véraison model",
        ),
        "gsr": Label(
            "Model cukernatosti hroznů (GSR)",
            "Zuckerreife-Modell (GSR)",
            "Grapevine Sugar Ripeness model",
        ),
        "gst": Label(
            "Průměrná teplota vegetačního období",
            "Mitteltemperatur der Vegetationsperiode",
            "Growing season average temperature",
        ),
        "heat_hours": Label(
            "Hodiny v teplotních pásmech",
            "Stunden in Temperaturbereichen",
            "Hours in temperature bands",
        ),
        "huglin": Label("Huglinův index", "Huglin-Index", "Huglin index"),
        "powdery_mildew_gt": Label(
            "Riziko padlí (Gubler-Thomas)",
            "Mehltau-Risiko (Gubler-Thomas)",
            "Powdery mildew risk (Gubler-Thomas)",
        ),
        "tropical_days_nights": Label(
            "Tropické dny a noci", "Tropentage und Tropennächte", "Tropical days and nights"
        ),
        "vpd": Label("Deficit tlaku vodní páry", "Dampfdruckdefizit", "Vapour pressure deficit"),
        "winter_freeze": Label("Zimní mrazy", "Winterfrost", "Winter freeze"),
    }
)
"""Display names of the registered indices (titles of ``docs/indices/<id>.md`` in English)."""


@dataclass(frozen=True, slots=True)
class IndexSpec:
    """A climate index as listed in ``manifest.json``.

    Attributes
    ----------
    id : str
        Index id (registry key).
    unit : str
        Unit of its value.
    """

    id: str
    unit: str


class IndexCatalog:
    """Manifest entries of the indices: unit, documentation link and label.

    Parameters
    ----------
    labels : Mapping of str to Label, optional
        Label per index id; :data:`INDEX_LABELS` when omitted. An index without a label is
        listed under its id in every language (and a warning is logged).
    """

    __slots__ = ("_labels",)

    def __init__(self, labels: Mapping[str, Label] | None = None) -> None:
        self._labels = labels if labels is not None else INDEX_LABELS

    def label(self, index_id: str) -> Label:
        """Return the label of an index.

        Parameters
        ----------
        index_id : str
            The index id.

        Returns
        -------
        Label
            Its label, or the id itself in every language.
        """
        found = self._labels.get(index_id)
        if found is None:
            logger.warning("Index %s has no label for the site; its id is shown.", index_id)
            return Label.same(index_id)
        return found

    def entry(self, spec: IndexSpec) -> dict[str, object]:
        """Return the manifest entry of one index.

        Parameters
        ----------
        spec : IndexSpec
            Id and unit.

        Returns
        -------
        dict
            ``{"id", "unit", "doc", "label"}``.
        """
        return {
            "id": spec.id,
            "unit": spec.unit,
            "doc": INDEX_DOC_TEMPLATE.format(index_id=spec.id),
            "label": self.label(spec.id).as_dict(),
        }
