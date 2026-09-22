from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom


@dataclass(frozen=True, slots=True)
class UsdAssetMetadata:
    """Metadata extracted from one visible USD asset root."""

    default_prim: str
    root_prim_names: tuple[str, ...]
    kind: str
    up_axis: str
    meters_per_unit: float | None
    meters_per_unit_authored: bool
    asset_identifier: str
    asset_name: str
    asset_version: str
    has_payloads: bool
    has_preview: bool
    preview_path: str
    parse_status: str
    parse_error: str

    def root_prim_names_json(self) -> str:
        return json.dumps(self.root_prim_names, ensure_ascii=False)

    @staticmethod
    def pending() -> "UsdAssetMetadata":
        return UsdAssetMetadata(
            default_prim="",
            root_prim_names=(),
            kind="",
            up_axis="",
            meters_per_unit=None,
            meters_per_unit_authored=False,
            asset_identifier="",
            asset_name="",
            asset_version="",
            has_payloads=False,
            has_preview=False,
            preview_path="",
            parse_status="pending",
            parse_error="",
        )

    @staticmethod
    def error(message: str) -> "UsdAssetMetadata":
        return UsdAssetMetadata(
            default_prim="",
            root_prim_names=(),
            kind="",
            up_axis="",
            meters_per_unit=None,
            meters_per_unit_authored=False,
            asset_identifier="",
            asset_name="",
            asset_version="",
            has_payloads=False,
            has_preview=False,
            preview_path="",
            parse_status="error",
            parse_error=message,
        )


def _text(value: object | None) -> str:
    return "" if value is None else str(value)


def _list_op_items(list_op) -> list:
    try:
        return list(list_op.GetAppliedItems())
    except AttributeError:
        items: list = []

        for name in (
            "explicitItems",
            "prependedItems",
            "appendedItems",
            "addedItems",
        ):
            items.extend(getattr(list_op, name, []))

        return items


def _has_authored_payloads(layer: Sdf.Layer) -> bool:
    def walk(prim_specs: list[Sdf.PrimSpec]) -> bool:
        for prim_spec in prim_specs:
            if _list_op_items(prim_spec.payloadList):
                return True

            if walk(list(prim_spec.nameChildren)):
                return True

        return False

    return walk(list(layer.rootPrims))


def _find_default_preview(default_prim: Usd.Prim) -> tuple[bool, str]:
    """
    Discover—not generate—an authored AssetPreviewsAPI image.

    A missing preview API is normal and must never make metadata extraction
    fail.
    """
    if not default_prim or not default_prim.IsValid():
        return False, ""

    try:
        from pxr import UsdMedia

        previews_api = UsdMedia.AssetPreviewsAPI(default_prim)
        if not previews_api:
            return False, ""

        thumbnails = previews_api.GetDefaultThumbnails()
        if thumbnails is None:
            return False, ""

        default_image = thumbnails.defaultImage
        if not default_image:
            return False, ""

        return True, str(default_image)

    except Exception:
        return False, ""


def inspect_asset_root(root_path: Path) -> UsdAssetMetadata:
    """
    Read metadata from one visible USD root asset.

    The first pass uses Sdf.Layer for direct authored values. The second uses a
    LoadNone stage so payloads are not loaded merely to read stage-level
    metrics, kind, or an authored preview reference.
    """
    try:
        layer = Sdf.Layer.FindOrOpen(str(root_path))
    except Exception as error:
        return UsdAssetMetadata.error(
            f"{type(error).__name__}: {error}"
        )

    if layer is None:
        return UsdAssetMetadata.error("USD layer could not be opened")

    try:
        root_prim_names = tuple(
            prim_spec.name
            for prim_spec in layer.rootPrims
        )

        asset_info = dict(layer.assetInfo or {})

        default_prim_name = _text(layer.defaultPrim)
        asset_identifier = _text(asset_info.get("identifier"))
        asset_name = _text(asset_info.get("name"))
        asset_version = _text(asset_info.get("version"))
        has_payloads = _has_authored_payloads(layer)

    except Exception as error:
        return UsdAssetMetadata.error(
            f"Layer metadata read failed: {type(error).__name__}: {error}"
        )

    try:
        stage = Usd.Stage.Open(
            str(root_path),
            load=Usd.Stage.LoadNone,
        )
    except Exception as error:
        return UsdAssetMetadata(
            default_prim=default_prim_name,
            root_prim_names=root_prim_names,
            kind="",
            up_axis="",
            meters_per_unit=None,
            meters_per_unit_authored=False,
            asset_identifier=asset_identifier,
            asset_name=asset_name,
            asset_version=asset_version,
            has_payloads=has_payloads,
            has_preview=False,
            preview_path="",
            parse_status="warning",
            parse_error=(
                "Layer opened, but stage metadata could not be read: "
                f"{type(error).__name__}: {error}"
            ),
        )

    if stage is None:
        return UsdAssetMetadata(
            default_prim=default_prim_name,
            root_prim_names=root_prim_names,
            kind="",
            up_axis="",
            meters_per_unit=None,
            meters_per_unit_authored=False,
            asset_identifier=asset_identifier,
            asset_name=asset_name,
            asset_version=asset_version,
            has_payloads=has_payloads,
            has_preview=False,
            preview_path="",
            parse_status="warning",
            parse_error="Layer opened, but composed stage could not be created",
        )

    try:
        default_prim = stage.GetDefaultPrim()

        if default_prim and default_prim.IsValid():
            composed_default_prim_name = default_prim.GetName()
            kind = _text(default_prim.GetMetadata("kind"))
        else:
            composed_default_prim_name = default_prim_name
            kind = ""

        up_axis = _text(UsdGeom.GetStageUpAxis(stage))
        meters_per_unit_authored = bool(
            UsdGeom.StageHasAuthoredMetersPerUnit(stage)
        )
        meters_per_unit = float(
            UsdGeom.GetStageMetersPerUnit(stage)
        )

        has_preview, preview_path = _find_default_preview(default_prim)

        return UsdAssetMetadata(
            default_prim=composed_default_prim_name,
            root_prim_names=root_prim_names,
            kind=kind,
            up_axis=up_axis,
            meters_per_unit=meters_per_unit,
            meters_per_unit_authored=meters_per_unit_authored,
            asset_identifier=asset_identifier,
            asset_name=asset_name,
            asset_version=asset_version,
            has_payloads=has_payloads,
            has_preview=has_preview,
            preview_path=preview_path,
            parse_status="valid",
            parse_error="",
        )

    except Exception as error:
        return UsdAssetMetadata(
            default_prim=default_prim_name,
            root_prim_names=root_prim_names,
            kind="",
            up_axis="",
            meters_per_unit=None,
            meters_per_unit_authored=False,
            asset_identifier=asset_identifier,
            asset_name=asset_name,
            asset_version=asset_version,
            has_payloads=has_payloads,
            has_preview=False,
            preview_path="",
            parse_status="warning",
            parse_error=(
                "Stage opened, but extraction was incomplete: "
                f"{type(error).__name__}: {error}"
            ),
        )
