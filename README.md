# LayerVault

> A local-first, OpenUSD-first project, asset, resource, and dependency manager for personal and small-team CG pipelines.
> LayerVault aims to provide a reliable foundation for personal productions, short films, look-development projects, game assets, and mostly small USD-based pipelines.

LayerVault is a desktop application (and command-line toolkit for managing OpenUSD projects, assets, shots, publishes, textures, materials, caches, and DCC workfiles.

It is designed for artists and technical artists who want the practical workflow benefits of tools such as Prism Pipeline or Tik Manager while keeping their data local, transparent, portable, and structured around OpenUSD composition.

LayerVault treats **USD layers, immutable publishes, manifests, dependency locks, and portable packages** as first-class production objects.

---

## Status

> **Early development**

The first milestone is called **USD Lab**.
It focuses on:

- Opening and inspecting `.usd`, `.usda`, and `.usdc` files.
- Displaying layer stacks, references, payloads, and sublayers.
- Discovering external dependencies.
- Detecting missing files, absolute paths, and broken UDIM texture sets.
- Validating USD and LayerVault project policies.
- Producing machine-readable JSON reports.
- Integrate with Houdini/Solaris.

### Primary goals

- Use **OpenUSD** as the main interchange format between DCC applications.
- Store project metadata in human-readable manifests.
- Use SQLite only as a fast, local index.
- Support immutable, versioned publishes.
- Make asset and shot dependencies visible and inspectable.
- Build portable USD packages with all required resources.
- Support assets, shots, materials, texture sets, HDRIs, scans, caches, and render outputs.
- Work on Linux and Windows.
- Develop natively on RHEL base system.
- Avoid dependency conflicts with Houdini, Maya, Nuke, Mari, Blender, RenderMan, or other DCC applications.
- Provide controlled DCC launch contexts and application profiles.
- Remain useful without a cloud service, central database server, or internet connection.

### Long-term goals

- Cross-platform project and resource browsing.
- DCC launcher and environment-profile management.
- Houdini, Maya, Nuke, Mari, and Blender integrations.
- USD asset validation and publishing workflows.
- Texture/UDIM publishing and resource management.
- Thumbnail and preview generation.
- Reverse dependency search.
- Package archives for handoff, backup, and portability.
-  OpenAssetIO/USD resolver integration.
- Optional batch workers for validation, thumbnail generation, texture conversion, and packaging.
- Optional Hydra, or external renderer preview integrations.

---

## Core principles

### USD first

OpenUSD is the primary communication format between applications.

LayerVault uses USD for:

- Asset interfaces.
- Layered composition.
- References.
- Payloads.
- Material bindings.
- Variants.
- Render settings.
- Render products.
- Asset assembly.
- Shot assembly.
- Look development.
- Lighting.
- FX handoff.
- Render input definition.

Published data is preferably represented through USD and explicit package artifacts.

### Immutable publishes

Published versions must never be modified in place.

```text
publish/lookdev/v001/
publish/lookdev/v002/
publish/lookdev/v003/
```

A correction creates a new version.

```text
v003 is wrong
    ↓
Create v004
```

This allows:

- Reproducible renders.
- Reliable shot assembly.
- Historical inspection.
- Safer package generation.
- Easier debugging.
- Repeatable comp inputs.
- Version pinning.

### Stable root layers

Every asset should have a stable root layer that acts as its public interface.
Shots and other assets should reference this stable interface rather than internal publish paths.

```text
assets/char/robot_01/
├── usd/
│   ├── robot_01.usda
│   ├── robot_01_model.usda
│   ├── robot_01_lookdev.usda
│   └── robot_01_payload.usda
└── publish/
    ├── model/
    └── lookdev/
```

The root layer is intentionally stable.
The actual selected publish version is recorded through manifests, policy files, or generated composition layers.

### Relative paths inside packages

Dependencies within a portable package should use relative asset paths.

```usda
prepend payload = @./geometry/robot_01_render.usdc@
```

```usda
asset inputs:file = @./textures/robot_01_basecolor.<UDIM>.tx@
```

This makes packages movable and archiveable.
Avoid authoring machine-specific paths such as:

```text
C:/Users/artist/Documents/textures/robot_basecolor.1001.exr
/mnt/nas/projects/simplecity/assets/robot/textures/basecolor.1001.tx
```

### Isolated application runtimes

LayerVault ships with and uses its own tested runtime.
It must not import OpenUSD, Python packages, Qt libraries, or plugins from other application

Each application should run in its own controlled environment.

```text
LayerVault runtime
    ├── Python
    ├── PySide6 / Qt
    ├── OpenUSD
    ├── USD plugins
    └── LayerVault code

Houdini runtime
    ├── Houdini Python
    ├── Houdini USD
    ├── Solaris
    └── Houdini plugins

Maya runtime
    ├── Maya Python
    ├── Maya USD
    └── Maya plugins
```

## Repository structure

```text
layervault/
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── uv.lock
├── flake.nix
├── flake.lock
├── justfile
│
├── config/
│   ├── runtime.toml
│   ├── naming.toml
│   ├── departments.toml
│   ├── usd_policy.toml
│   ├── default_project.toml
│   └── dcc_profiles/
│       ├── houdini_20_5.toml
│       ├── maya.toml
│       ├── nuke.toml
│       ├── mari.toml
│       └── blender.toml
│
├── src/
│   └── layervault/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli/
│       ├── domain/
│       ├── filesystem/
│       ├── usd/
│       ├── validation/
│       ├── packaging/
│       ├── indexing/
│       ├── publishing/
│       ├── dcc/
│       ├── thumbnails/
│       ├── ui/
│       └── infrastructure/
│
├── resources/
│   ├── icons/
│   ├── schemas/
│   ├── templates/
│   ├── styles/
│   └── demo_project/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── smoke/
│   ├── fixtures/
│   └── golden/
│
├── docs/
│   ├── architecture/
│   ├── decisions/
│   ├── usd/
│   ├── release/
│   └── user-guides/
│
├── tools/
│   ├── build_usd_linux.sh
│   ├── build_usd_windows.ps1
│   ├── build_app_linux.sh
│   ├── build_app_windows.ps1
│   ├── package_project.py
│   └── ci/
│
├── docker/
│   ├── validator/
│   ├── packager/
│   └── thumbnail/
│
└── vendor/
    └── OpenUSD/
```

---

## Project structure

A LayerVault project is a filesystem tree with readable configuration and versioned data.

```text
MountainEnv/
├── project.toml
├── config/
│   ├── departments.toml
│   ├── naming.toml
│   ├── usd_policy.toml
│   └── applications.toml
│
├── assets/
│   ├── char/
│   │   └── plane_01/
│   │       ├── entity.toml
│   │       ├── usd/
│   │       ├── work/
│   │       ├── publish/
│   │       ├── sourceimages/
│   │       ├── caches/
│   │       └── renders/
│   │
│   ├── prop/
│   └── env/
│
├── shots/
│   └── sq010/
│       └── sh020/
│           ├── entity.toml
│           ├── usd/
│           ├── work/
│           ├── publish/
│           ├── caches/
│           └── renders/
│
├── library/
│   ├── materials/
│   ├── texture_sets/
│   ├── scans/
│   ├── hdri/
│   ├── ocio/
│   ├── luts/
│   ├── render_presets/
│   └── usd_components/
│
├── tools/
│   ├── houdini/
│   ├── maya/
│   ├── nuke/
│   ├── mari/
│   └── blender/
│
└── .layervault/
    ├── index.sqlite
    ├── cache/
    ├── thumbnails/
    ├── logs/
    └── reports/
```
