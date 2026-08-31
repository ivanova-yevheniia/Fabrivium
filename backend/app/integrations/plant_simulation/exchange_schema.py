"""
Fabrivium Exchange Model 

    Fabrivium domain (Factory / FactoryConceptDraft / FactoryLayout)
            ↓
    Fabrivium Exchange Model      ← this module
            ↓
    ┌────────────────┬──────────────────┬──────────────┐
    Plant Simulation   future adapter     file archive
        adapter

The Siemens adapter must never read Fabrivium's domain objects directly.
If it did, every future tool would need its own translation of the same
concepts, and Siemens-shaped assumptions would leak back into the domain.
The exchange model is the one place where "what Fabrivium knows" is
expressed in terms an engineering tool can consume.

* An UNKNOWN value stays `None` and keeps `source = UNKNOWN`. It is never
  serialised as 0 — the Phase 13 rule, unchanged.
* Provenance travels with each value that has one, so a downstream consumer
  can still distinguish a customer statement from a planning default.
* Fabrivium's own simulation results are carried as a SUMMARY for
  comparison.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field

PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]

EXCHANGE_SCHEMA_VERSION = "factorymind.exchange.v1"


class ExchangeValueSource(str, Enum):
    """Mirrors app.models.concept.ValueSource.
    """

    CUSTOMER = "CUSTOMER"
    EXAMPLE_DATA = "EXAMPLE_DATA"
    CATALOG_DEFAULT = "CATALOG_DEFAULT"
    CALCULATED = "CALCULATED"
    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"


class ExchangeValue(BaseModel):
    """A number that may be absent, and knows where it came from."""

    model_config = {"frozen": True}

    value: float | None = None
    source: ExchangeValueSource = ExchangeValueSource.UNKNOWN
    detail: str | None = None

    @staticmethod
    def unknown() -> "ExchangeValue":
        return ExchangeValue(value=None, source=ExchangeValueSource.UNKNOWN)

    @staticmethod
    def of(value: float, source: ExchangeValueSource, detail: str | None = None) -> "ExchangeValue":
        return ExchangeValue(value=value, source=source, detail=detail)


class ExchangeStation(BaseModel):
    """One processing station.

    `cycle_time_seconds` and `capacity` are process semantics a receiving
    simulator reads them. `x`/`y`/`width`/`length` are layout, which
    Fabrivium's simulator does not read; they are transferred because a
    receiving tool may place objects with them, never because they affect
    throughput.
    """

    model_config = {"frozen": True}

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    process_type: str = Field(..., min_length=1)

    cycle_time_seconds: PositiveFloat
    capacity: PositiveInt = 1
    operators_required: int = 0

    x: float | None = None
    y: float | None = None
    width: float | None = None
    length: float | None = None
    rotation_deg: float = 0.0

    purchase_cost: ExchangeValue = Field(default_factory=ExchangeValue.unknown)

    # selected equipment 
    # METADATA ONLY
    selected_manufacturer: str | None = None
    selected_model: str | None = None
    selected_source_url: str | None = None


class ExchangeBuffer(BaseModel):
    """Intermediate storage between two consecutive stations."""

    model_config = {"frozen": True}

    id: str
    name: str
    upstream_station_id: str
    downstream_station_id: str
    capacity: PositiveInt


class ExchangeFlowLink(BaseModel):
    """One directed material-flow link. The chain of links IS the route."""

    model_config = {"frozen": True}

    from_id: str
    to_id: str


class ExchangeResources(BaseModel):
    """The operating model. All three are simulation inputs in Fabrivium."""

    model_config = {"frozen": True}

    operators_available: int
    shifts_per_day: PositiveInt
    hours_per_shift: PositiveFloat

    @property
    def production_seconds_per_day(self) -> float:
        """Available production time per day.
        """
        return self.shifts_per_day * self.hours_per_shift * 3600.0


class ExchangeSimulationSummary(BaseModel):
    """Fabrivium's own verified result, carried for COMPARISON only.
    """

    model_config = {"frozen": True}

    target_units_per_day: float
    completed_units_per_day: float
    demand_gap_units: float
    bottleneck_station_id: str | None = None
    simulator: str = "Fabrivium deterministic discrete-event engine"


class FactoryMindExchange(BaseModel):
    """The full package handed to an engineering tool."""

    schema_version: str = EXCHANGE_SCHEMA_VERSION

    project_name: str
    product_name: str

    stations: list[ExchangeStation] = Field(default_factory=list)
    flow: list[ExchangeFlowLink] = Field(default_factory=list)
    buffers: list[ExchangeBuffer] = Field(default_factory=list)

    resources: ExchangeResources

    floor_width: float | None = None
    floor_length: float | None = None

    simulation_summary: ExchangeSimulationSummary | None = None
    open_assumptions: list[str] = Field(default_factory=list)

    def station_by_id(self, station_id: str) -> ExchangeStation | None:
        for station in self.stations:
            if station.id == station_id:
                return station
        return None
