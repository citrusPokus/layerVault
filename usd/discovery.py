'''
Becomes the single source of truth for:
- Recognized USD extensions.
- Resolving authored local paths.
- Walking prim specs.
- Reading sublayers, references, and payloads.
- Detecting local package dependencies.
- Identifying candidate root layers.
- Reporting missing/external/URI dependencies.
- Scanning a library recursively without any PySide6 dependency.
'''
from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pxr import Sdf

from .metadata import UsdAssetMetadata, inspect_asset_root


USD_EXTENSIONS = frozenset(
    {
        ".usd",
        ".usda",
        ".usdc",
        ".usdz",
    }
)


@dataclass(frozen=True, slots=True)
class UsdDependency:
  
    owning_layer_path: Path
    authored_path: str
    dependency_type: str
    resolved_path: Path | None
    exists: bool
    is_local_package_file: bool
    is_external_uri: bool


@dataclass(frozen=True, slots=True)
class UsdPackageInspection:
    # Inspection result for one flat USD package folder.
    package_path: Path
    all_layers: tuple[Path, ...]
    root_candidates: tuple[Path, ...]
    internal_layers: tuple[Path, ...]
    dependencies: tuple[UsdDependency, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiscoveredUsdRoot:

    library_root: Path
    package_path: Path
    root_layer_path: Path
    relative_path: str
    category: str
    size_bytes: int
    metadata: UsdAssetMetadata
    root_detection_mode: str
    root_candidate_count: int
    package_warnings: tuple[str, ...]


def is_usd_path(path: str | Path) -> bool:
    # Return True when a path has an extension supported by LayerVault.
    return Path(path).suffix.lower() in USD_EXTENSIONS

def is_external_uri(authored_path: str) -> bool:
    """
    URI handling is deliberately deferred. A future OpenAssetIO
    integration, but the local inspector records them
    without pretending they resolve to a filesystem path.
    """
    return "://" in authored_path

def resolve_asset_path(
    authored_path: str,
    owning_layer_path: Path,
) -> Path | None:
    """
    Resolve a filesystem asset path relative to the layer that authored it.
    This intentionally does not resolve URI-like identifiers. A relative USD
    path is anchored to its owning layer, not to the Python process CWD.
    """
    if not authored_path or is_external_uri(authored_path):
        return None

    try:
        asset_path = Path(authored_path)

        if asset_path.is_absolute():
            return asset_path.resolve()

        return (owning_layer_path.parent / asset_path).resolve()

    except OSError:
        return None


def find_usd_layers(package_path: Path) -> list[Path]:
    
    try:
        return sorted(
            (
                path.resolve()
                for path in package_path.iterdir()
                if path.is_file() and is_usd_path(path)
            ),
            key=lambda path: path.name.casefold(),
        )
    except OSError:
        return []

def walk_prim_specs(prim_specs: list[Sdf.PrimSpec],) -> Iterator[Sdf.PrimSpec]:
    #Yield every prim spec in a layer, including nested child specs.
    for prim_spec in prim_specs:
        yield prim_spec
        yield from walk_prim_specs(list(prim_spec.nameChildren))

def get_list_op_items(list_op) -> list:
    # Return usable items from an Sdf list operation.

    try:
        return list(list_op.GetAppliedItems())

    except AttributeError:
        items: list = []

        for attribute_name in (
            "explicitItems",
            "prependedItems",
            "appendedItems",
            "addedItems",
        ):
            items.extend(getattr(list_op, attribute_name, []))

        return items

def iter_direct_authored_usd_dependencies(usd_layer_path: Path,) -> Iterator[UsdDependency]:
    """
    This function deliberately reports authored paths even when they are
    missing, external, or URI-based. Root discovery can filter local package
    dependencies while validation/reporting retains the complete information.
    """
    try:
        layer = Sdf.Layer.FindOrOpen(str(usd_layer_path))
    except Exception:
        return

    if layer is None:
        return

    authored_dependencies: list[tuple[str, str]] = []

    for sublayer_path in layer.subLayerPaths:
        authored_dependencies.append(("sublayer", str(sublayer_path)))

    for prim_spec in walk_prim_specs(list(layer.rootPrims)):
        for reference in get_list_op_items(prim_spec.referenceList):
            if reference.assetPath:
                authored_dependencies.append(
                    ("reference", str(reference.assetPath))
                )

        for payload in get_list_op_items(prim_spec.payloadList):
            if payload.assetPath:
                authored_dependencies.append(
                    ("payload", str(payload.assetPath))
                )

    seen: set[tuple[str, str]] = set()

    for dependency_type, authored_path in authored_dependencies:
        key = (dependency_type, authored_path)

        if key in seen:
            continue

        seen.add(key)

        external_uri = is_external_uri(authored_path)
        resolved_path = resolve_asset_path(
            authored_path=authored_path,
            owning_layer_path=usd_layer_path,
        )

        exists = bool(resolved_path and resolved_path.exists())

        yield UsdDependency(
            owning_layer_path=usd_layer_path,
            authored_path=authored_path,
            dependency_type=dependency_type,
            resolved_path=resolved_path,
            exists=exists,
            is_local_package_file=False,
            is_external_uri=external_uri,
        )


def inspect_package(package_path: Path) -> UsdPackageInspection:
    """
    Root detection :
    - A USD layer referenced, payloaded, or sublayered by another local USD
      file in the same folder is considered an internal composition layer.
    - A USD layer with no incoming local composition relation is a root-layer
      candidate.
    - Cyclic/broken packages remain visible by treating all layers as
      candidates when no root can be inferred.
    """
    resolved_package_path = package_path.resolve()
    all_layers = tuple(find_usd_layers(resolved_package_path))
    package_layer_set = set(all_layers)

    if not all_layers:
        return UsdPackageInspection(
            package_path=resolved_package_path,
            all_layers=(),
            root_candidates=(),
            internal_layers=(),
            dependencies=(),
            warnings=("No USD layers found directly inside this folder.",),
        )

    dependencies: list[UsdDependency] = []
    internal_layers: set[Path] = set()
    warnings: list[str] = []

    for layer_path in all_layers:
        try:
            layer_dependencies = list(
                iter_direct_authored_usd_dependencies(layer_path)
            )
        except Exception as error:
            warnings.append(
                f"Could not inspect {layer_path.name}: "
                f"{type(error).__name__}: {error}"
            )
            continue

        for dependency in layer_dependencies:
            resolved_path = dependency.resolved_path
            is_local_package_file = bool(
                resolved_path and resolved_path in package_layer_set
            )

            normalized_dependency = UsdDependency(
                owning_layer_path=dependency.owning_layer_path,
                authored_path=dependency.authored_path,
                dependency_type=dependency.dependency_type,
                resolved_path=resolved_path,
                exists=dependency.exists,
                is_local_package_file=is_local_package_file,
                is_external_uri=dependency.is_external_uri,
            )

            dependencies.append(normalized_dependency)

            if is_local_package_file and resolved_path is not None:
                internal_layers.add(resolved_path)

    root_candidates = tuple(
        sorted(
            package_layer_set - internal_layers,
            key=lambda path: path.name.casefold(),
        )
    )

    if not root_candidates:
        warnings.append(
            "No root layer could be inferred from composition arcs. "
            "The package may contain an ambiguous structure; all "
            "local USD layers are shown as candidates."
        )
        root_candidates = all_layers

    if len(root_candidates) > 1:
        warnings.append(
            f"Ambiguous package: {len(root_candidates)} root-layer candidates "
            "were detected. Add a manifest or project convention to declare "
            "one official entry layer."
        )

    return UsdPackageInspection(
        package_path=resolved_package_path,
        all_layers=all_layers,
        root_candidates=root_candidates,
        internal_layers=tuple(
            sorted(
                internal_layers,
                key=lambda path: path.name.casefold(),
            )
        ),
        dependencies=tuple(dependencies),
        warnings=tuple(warnings),
    )


def iter_package_directories(library_root: Path,) -> Iterator[Path]:
    #The filesystem traversal does not follow symlinked directories. This reduces accidental scans of mounted libraries and cycles.
    
    root = library_root.resolve()
    directories: list[Path] = [root]

    while directories:
        directory = directories.pop()

        try:
            with os.scandir(directory) as entries:
                entries = list(entries)
        except (OSError, PermissionError):
            continue

        contains_direct_usd = False

        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    directories.append(Path(entry.path))
                    continue

                if entry.is_file(follow_symlinks=False) and is_usd_path(
                    entry.name
                ):
                    contains_direct_usd = True

            except (OSError, PermissionError):
                continue

        if contains_direct_usd:
            yield directory


def iter_discovered_roots(library_root: Path,) -> Iterator[DiscoveredUsdRoot]:
    """
    Recursively discover artist-facing root candidates below a library root.
    This is deliberately headless and reusable from:
    - the CLI,
    - the PySide6 scan worker,
    - tests,
    - future batch/CI workers.
    """
    resolved_library_root = library_root.resolve()

    for package_path in sorted(
        iter_package_directories(resolved_library_root),
        key=lambda path: str(path).casefold(),
    ):
        inspection = inspect_package(package_path)

        if not inspection.root_candidates:
            continue

        root_candidate_count = len(inspection.root_candidates)
        root_detection_mode = (
            "heuristic"
            if root_candidate_count == 1
            else "heuristic_ambiguous"
        )

        for root_layer_path in inspection.root_candidates:
            try:
                size_bytes = root_layer_path.stat().st_size
            except OSError:
                size_bytes = 0

            try:
                relative_path = root_layer_path.relative_to(
                    resolved_library_root
                ).as_posix()
            except ValueError:
                relative_path = root_layer_path.name

            path_parts = relative_path.split("/")
            category = (
                path_parts[0]
                if len(path_parts) > 1
                else "Uncategorised"
            )

            yield DiscoveredUsdRoot(
                library_root=resolved_library_root,
                package_path=package_path,
                root_layer_path=root_layer_path,
                relative_path=relative_path,
                category=category,
                size_bytes=size_bytes,
                metadata=inspect_asset_root(root_layer_path),
                root_detection_mode=root_detection_mode,
                root_candidate_count=root_candidate_count,
                package_warnings=inspection.warnings,
            )
