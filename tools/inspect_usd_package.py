from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

from pxr import Sdf


# USD layer formats LayerVault recognizes.
USD_EXTENSIONS = frozenset(
    {
        ".usd",
        ".usda",
        ".usdc",
        ".usdz",
    }
)


def is_usd_path(path: str) -> bool:
    """Return True only when an asset path has a supported USD extension."""
    return Path(path).suffix.lower() in USD_EXTENSIONS


def resolve_asset_path(
    authored_path: str,
    owning_layer_path: Path,
) -> Path | None:
    """
    Resolve an authored asset path relative to the USD layer that owns it.

    Example:
        owning layer:
            D:/Diorama/Models/Bollard/payload.usd

        authored path:
            ./mtl.usd

        resolved path:
            D:/Diorama/Models/Bollard/mtl.usd

    Do not use Path(authored_path).resolve() by itself: that incorrectly
    resolves relative paths from the current terminal working directory.
    """
    if not authored_path:
        return None

    # Custom resolver URIs are deliberately skipped in this first local-only
    # browser implementation. Example: asset://library/prop.usd
    if "://" in authored_path:
        return None

    try:
        asset_path = Path(authored_path)

        if asset_path.is_absolute():
            return asset_path.resolve()

        return (owning_layer_path.parent / asset_path).resolve()

    except OSError:
        return None


def find_usd_layers(package_path: Path) -> list[Path]:
    """
    Find USD files directly inside one asset package folder.

    The package itself is one folder such as:
        Models/KB3D_CBD_BldgSmDjBooth_A/

    We intentionally do not recurse into tex/, preview/, source/, etc.
    """
    return sorted(
        (
            path.resolve()
            for path in package_path.iterdir()
            if path.is_file() and path.suffix.lower() in USD_EXTENSIONS
        ),
        key=lambda path: path.name.lower(),
    )


def walk_prim_specs(
    prim_specs: list[Sdf.PrimSpec],
) -> Iterator[Sdf.PrimSpec]:
    """
    Yield every prim spec in a layer, including nested child prim specs.

    References and payloads can exist anywhere in a USD hierarchy, not only
    on the root prim.
    """
    for prim_spec in prim_specs:
        yield prim_spec
        yield from walk_prim_specs(list(prim_spec.nameChildren))


def get_list_op_items(list_op) -> list:
    """
    Return the currently applied items of an Sdf list operation.

    USD can author references/payloads with prepend, append, add, delete,
    explicit, and ordered list operations. GetAppliedItems gives the usable
    resolved item collection for the current layer specification.
    """
    try:
        return list(list_op.GetAppliedItems())

    except AttributeError:
        # Compatibility fallback for unusual older bindings.
        items = []

        for attribute_name in (
            "explicitItems",
            "prependedItems",
            "appendedItems",
            "addedItems",
        ):
            items.extend(getattr(list_op, attribute_name, []))

        return items


def get_direct_local_usd_dependencies(
    usd_layer_path: Path,
    package_layers: set[Path],
) -> set[Path]:
    """
    Find direct local USD dependencies authored by one USD layer.

    The function reads three composition mechanisms:

    1. Layer sublayers:
       layer.subLayerPaths

    2. Prim references:
       prim_spec.referenceList

    3. Prim payloads:
       prim_spec.payloadList

    Only dependencies resolving to another USD file in the same package folder
    are returned. External material-library USDs remain external dependencies
    and do not affect which local file is the asset root.
    """
    try:
        layer = Sdf.Layer.FindOrOpen(str(usd_layer_path))

    except Exception as error:
        print(
            f"WARNING: Could not open {usd_layer_path.name}: "
            f"{type(error).__name__}: {error}"
        )
        return set()

    if layer is None:
        print(f"WARNING: Could not open USD layer: {usd_layer_path.name}")
        return set()

    authored_asset_paths: set[str] = set()

    # -----------------------------------------------------------------------
    # 1. Layer-level sublayers
    # -----------------------------------------------------------------------

    for sublayer_path in layer.subLayerPaths:
        authored_asset_paths.add(str(sublayer_path))

    # -----------------------------------------------------------------------
    # 2. Prim-level references and payloads
    # -----------------------------------------------------------------------
    #
    # In your test:
    #
    # KB3D_CBD_BldgSmDjBooth_A.usd
    #   def "KB3D_CBD_BldgSmDjBooth_A" (
    #       prepend payload = @./payload.usd@
    #   )
    #
    # That authored payload lives on a PrimSpec's payloadList.

    for prim_spec in walk_prim_specs(list(layer.rootPrims)):

        # Extract all reference arcs authored on this prim.
        for reference in get_list_op_items(prim_spec.referenceList):
            asset_path = reference.assetPath

            if asset_path:
                authored_asset_paths.add(str(asset_path))

        # Extract all payload arcs authored on this prim.
        for payload in get_list_op_items(prim_spec.payloadList):
            asset_path = payload.assetPath

            if asset_path:
                authored_asset_paths.add(str(asset_path))

    # -----------------------------------------------------------------------
    # Resolve authored paths and retain only local package USD dependencies
    # -----------------------------------------------------------------------

    local_dependencies: set[Path] = set()

    for authored_path in authored_asset_paths:
        if not is_usd_path(authored_path):
            continue

        resolved_path = resolve_asset_path(
            authored_path=authored_path,
            owning_layer_path=usd_layer_path,
        )

        if resolved_path is None:
            continue

        if resolved_path in package_layers:
            local_dependencies.add(resolved_path)

    return local_dependencies


def find_asset_roots(
    package_path: Path,
) -> tuple[list[Path], set[Path], dict[Path, set[Path]]]:
    """
    Find artist-facing USD root layers for one package folder.

    Root detection policy:
    - A local USD layer referenced, payloaded, or sublayered by another local
      USD layer is an internal composition layer.
    - A local USD layer with no incoming local dependency is an asset-root
      candidate and should appear in LayerVault.
    """
    package_layers = find_usd_layers(package_path)
    package_layer_set = set(package_layers)

    if not package_layers:
        return [], set(), {}

    internal_layers: set[Path] = set()
    dependency_graph: dict[Path, set[Path]] = {}

    for usd_layer in package_layers:
        dependencies = get_direct_local_usd_dependencies(
            usd_layer_path=usd_layer,
            package_layers=package_layer_set,
        )

        dependency_graph[usd_layer] = dependencies
        internal_layers.update(dependencies)

    # Any layer nobody inside the package depends upon is a root candidate.
    root_candidates = sorted(
        package_layer_set - internal_layers,
        key=lambda path: path.name.lower(),
    )

    # A circular or broken package should remain browsable for debugging.
    if not root_candidates:
        root_candidates = package_layers

    return root_candidates, internal_layers, dependency_graph


def main() -> None:
    """
    Run:

        python tools\\inspect_usd_package.py "D:\\path\\to\\asset_package"
    """
    if len(sys.argv) != 2:
        print(
            "Usage:\n"
            '  python tools\\inspect_usd_package.py "D:\\path\\to\\asset_package"'
        )
        raise SystemExit(1)

    package_path = Path(sys.argv[1]).expanduser().resolve()

    if not package_path.is_dir():
        print(f"ERROR: Folder does not exist:\n{package_path}")
        raise SystemExit(1)

    package_layers = find_usd_layers(package_path)

    if not package_layers:
        print(f"No USD layers found directly inside:\n{package_path}")
        raise SystemExit(0)

    roots, internal_layers, graph = find_asset_roots(package_path)

    print("\n" + "=" * 72)
    print(f"USD package: {package_path}")
    print("=" * 72)

    print("\nComposition graph:")

    for layer in package_layers:
        dependencies = graph.get(layer, set())

        print(f"  {layer.name}")

        for dependency in sorted(
            dependencies,
            key=lambda path: path.name.lower(),
        ):
            print(f"    -> {dependency.name}")

    print("\nAll USD layers:")

    for layer in package_layers:
        print(f"  - {layer.name}")

    print("\nHidden internal composition layers:")

    if internal_layers:
        for layer in sorted(
            internal_layers,
            key=lambda path: path.name.lower(),
        ):
            print(f"  - {layer.name}")
    else:
        print("  - None detected")

    print("\nLayerVault asset-root candidates:")

    for layer in roots:
        print(f"  + {layer.name}")

    print("\nResult:")

    if len(roots) == 1:
        print(f"  LayerVault should display: {roots[0].name}")
    else:
        print(
            "  Multiple root candidates found. The package needs an explicit "
            "manifest or a publishing convention to select one official root."
        )


if __name__ == "__main__":
    main()