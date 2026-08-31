"""In-memory Equipment Asset Registry for Fabrivium Phase 3A."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.equipment import EquipmentAsset


@dataclass(frozen=True)
class _RegistryEntry:
    """One registered asset plus the lookup keys it is indexed under."""

    asset: EquipmentAsset
    manufacturer: str | None
    model_number: str | None
    process_type: str | None


class EquipmentAssetRegistry:
    """In-memory registry of reusable ``EquipmentAsset`` entries."""

    def __init__(self) -> None:
        self._entries: list[_RegistryEntry] = []

    def register(
        self,
        asset: EquipmentAsset,
        *,
        manufacturer: str | None = None,
        model_number: str | None = None,
        process_type: str | None = None,
    ) -> None:
        """Register *asset* under the given lookup keys."""
        self._entries.append(
            _RegistryEntry(
                asset=asset,
                manufacturer=manufacturer if manufacturer is not None else asset.manufacturer,
                model_number=model_number if model_number is not None else asset.model_number,
                process_type=process_type,
            )
        )

    def find_by_manufacturer_model(
        self, manufacturer: str, model_number: str
    ) -> EquipmentAsset | None:
        """Return the first registered asset matching both keys exactly,
        or None if no matching asset exists."""
        for entry in self._entries:
            if entry.manufacturer == manufacturer and entry.model_number == model_number:
                return entry.asset
        return None

    def find_by_process_type(self, process_type: str) -> list[EquipmentAsset]:
        """Return every asset registered under *process_type* (e.g."""
        return [entry.asset for entry in self._entries if entry.process_type == process_type]

    def all_assets(self) -> list[EquipmentAsset]:
        """Return every registered asset, in registration order."""
        return [entry.asset for entry in self._entries]
