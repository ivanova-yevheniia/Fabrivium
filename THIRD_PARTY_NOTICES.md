# Third-party notices

This file lists third-party material distributed with Fabrivium and the basis on which it is included.

## 3D assets — Kenney Factory Kit 3.0 · CC0 1.0

**14 `.glb` models and their accompanying Kenney texture assets** under `frontend/public/assets/factory/`:

| Directory | Files |
|---|---|
| `stations/` | `assembly.glb`, `screwdriving.glb`, `inspection.glb`, `packaging.glb` |
| `flow/` | `conveyor.glb`, `conveyor-long.glb`, `conveyor-corner.glb`, `conveyor-junction.glb`, `arrow.glb`, `arrow-rounded.glb` |
| `workpieces/` | `unit.glb`, `unit-wide.glb` |
| `fallback/` | `machine.glb`, `machine-bed.glb` |

| | |
|---|---|
| Asset pack | **Kenney Factory Kit 3.0** |
| Author | **Kenney** |
| Source | **https://kenney.nl** |
| Licence | **CC0 1.0 Universal** |
| Redistribution | **Permitted**, including commercially |
| Attribution | **Not required** — credited here anyway |

The licence was verified from the Factory Kit archive's `License.txt` before the assets were included in the public release.

The runtime asset manifest in `frontend/src/utils/assetResolution.ts` also carries licence and source metadata for the Kenney assets used by the application.

## Fonts — IBM Plex · SIL Open Font License 1.1

Fabrivium uses IBM Plex through the npm packages:

- `@fontsource/ibm-plex-sans`
- `@fontsource/ibm-plex-mono`

Font binaries are installed through npm and are not committed as source files in this repository.

## Sample product specification — original project material

`examples/customer_docs/Compact_Electronics_Controller_Product_Specification.pdf`

Created specifically for Fabrivium. The CEC-120 is fictional and contains no real customer data.

The specification deliberately omits manufacturing-system design values such as production cycle times, station capacities, station counts, shift patterns, buffers, layouts, and costs. Those values must therefore be established downstream rather than read directly from the sample document.

No real customer document is included in this repository.

## Manufacturer equipment data — cited, not redistributed

Files under `backend/app/data/`, including candidate and supplier data, contain engineering notes derived from public manufacturer information together with the relevant source references where recorded.

They may include model names, capabilities, published dimensions, and notes about the scope or meaning of a published figure.

**No vendor PDF, image, drawing, or CAD file is redistributed by Fabrivium.**

## Python and JavaScript dependencies

Python dependencies are declared in:

`backend/requirements.txt`

Frontend dependencies are declared in:

`frontend/package.json`

They are resolved from PyPI and npm at install time. No third-party dependency is vendored in this repository, and the public project does not rely on local-path or private-registry dependencies.

## Project licence

This repository does not currently include a project licence. Unless and until one is added, the project source remains under the default copyright terms.

Third-party material listed above remains governed by its respective licence.
