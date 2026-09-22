from __future__ import annotations

import argparse
import json
from pathlib import Path

from layervault.usd.discovery import inspect_package
from layervault.usd.metadata import inspect_asset_root


def path_text(
    path: Path | None,
    package_path: Path,
) -> str | None:
    if path is None:
        return None

    try:
        return path.relative_to(package_path).as_posix()
    except ValueError:
        return str(path)


def report_as_dict(package_path: Path) -> dict:
    inspection = inspect_package(package_path)

    root_metadata = {
        root_path.name: {
            "default_prim": metadata.default_prim,
            "root_prim_names": list(metadata.root_prim_names),
            "kind": metadata.kind,
            "up_axis": metadata.up_axis,
            "meters_per_unit": metadata.meters_per_unit,
            "meters_per_unit_authored": metadata.meters_per_unit_authored,
            "asset_identifier": metadata.asset_identifier,
            "asset_name": metadata.asset_name,
            "asset_version": metadata.asset_version,
            "has_payloads": metadata.has_payloads,
            "has_preview": metadata.has_preview,
            "preview_path": metadata.preview_path,
            "parse_status": metadata.parse_status,
            "parse_error": metadata.parse_error,
        }
        for root_path in inspection.root_candidates
        for metadata in [inspect_asset_root(root_path)]
    }

    return {
        "schema_version": 1,
        "package_path": str(inspection.package_path),
        "all_layers": [
            path_text(layer, inspection.package_path)
            for layer in inspection.all_layers
        ],
        "root_candidates": [
            path_text(layer, inspection.package_path)
            for layer in inspection.root_candidates
        ],
        "internal_layers": [
            path_text(layer, inspection.package_path)
            for layer in inspection.internal_layers
        ],
        "root_metadata": root_metadata,
        "dependencies": [
            {
                "type": dependency.dependency_type,
                "owning_layer": path_text(
                    dependency.owning_layer_path,
                    inspection.package_path,
                ),
                "authored_path": dependency.authored_path,
                "resolved_path": path_text(
                    dependency.resolved_path,
                    inspection.package_path,
                ),
                "exists": dependency.exists,
                "local_to_package": dependency.is_local_package_file,
                "external_uri": dependency.is_external_uri,
            }
            for dependency in inspection.dependencies
        ],
        "warnings": list(inspection.warnings),
    }


def print_human_report(report: dict) -> None:
    print()
    print("=" * 72)
    print(f"USD package: {report['package_path']}")
    print("=" * 72)

    print("\nAll local USD layers:")
    if report["all_layers"]:
        for layer in report["all_layers"]:
            print(f" - {layer}")
    else:
        print(" - None")

    print("\nInternal local composition layers:")
    if report["internal_layers"]:
        for layer in report["internal_layers"]:
            print(f" - {layer}")
    else:
        print(" - None")

    print("\nLayerVault root-layer candidates:")
    if report["root_candidates"]:
        for layer in report["root_candidates"]:
            print(f" + {layer}")
    else:
        print(" - None")

    print("\nDependencies:")
    if report["dependencies"]:
        for dependency in report["dependencies"]:
            state = "OK" if dependency["exists"] else "MISSING"
            location = dependency["resolved_path"] or "<URI/unresolved>"
            print(
                f" - [{state}] {dependency['type']}: "
                f"{dependency['owning_layer']} -> "
                f"{dependency['authored_path']} -> {location}"
            )
    else:
        print(" - No direct sublayer/reference/payload dependencies found.")

    if report["warnings"]:
        print("\nWarnings:")
        for warning in report["warnings"]:
            print(f" - {warning}")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect a flat USD package for LayerVault."
    )
    parser.add_argument(
        "package_path",
        type=Path,
        help="Folder containing USD layers directly inside it.",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        type=Path,
        help="Optional output path for a JSON report.",
    )

    arguments = parser.parse_args()

    package_path = arguments.package_path.expanduser().resolve()

    if not package_path.is_dir():
        parser.error(f"Folder does not exist: {package_path}")

    report = report_as_dict(package_path)
    print_human_report(report)

    if arguments.json_path is not None:
        output_path = arguments.json_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Wrote JSON report: {output_path}")


if __name__ == "__main__":
    main()
