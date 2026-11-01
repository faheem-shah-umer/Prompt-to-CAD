# Third-party notices

The MIT license applies to Prompt to CAD's own code, documentation, purple pyramid and current original interface icons. It does not relicense dependencies or hosted services. Current glyphs are reproduced by `tools/generate_icons.py`; the previously extracted Flaticon artwork has been replaced in the present tree. Git history is preserved and has separate unresolved historical-artifact review.

The Windows portable candidate dynamically links Qt 6.9.0 and OpenCascade 7.8.1, and carries CPython 3.11 plus the resolved Python CAD/runtime dependencies. Exact package versions, native package builds, hashes and retained notice paths appear in `runtime-manifest.json` inside each candidate. Do not infer the final inventory from this summary.

| Component | Terms / retained material |
| --- | --- |
| Python | PSF and incorporated-software licenses in the actual runtime's LICENSE.txt |
| Qt Core / Gui / Widgets / Svg | LGPLv3 route; retain LGPLv3, GPLv3, copyright and third-party notices; DLLs remain replaceable |
| OpenCascade | LGPL2.1 with the OCCT LGPL exception; retain both texts |
| CadQuery and OCP bindings | Apache-2.0; wrapped OCCT has its own LGPL/exception obligations |
| CasADi and bundled solver/runtime components | LGPLv3+ and component-specific terms; retain the wheel's entire notice/license tree, including `include/licenses` |
| VTK | BSD-style and bundled third-party notices retained by its wheel |
| Certifi | MPL2; its public CA certificate bundle is not private credential material |
| FreeImage | Choose the FreeImage Public License route for the native package; preserve its complete terms and source-access obligations |
| LibRaw | Record the actual package's license selection; do not silently substitute a different upstream dual-license option |
| FreeType | Use the FreeType License route, with required acknowledgment/notices |
| Microsoft VC runtime | Actual Microsoft redistributable-runtime terms, not a conda metapackage's BSD label |

Other packages, compression/image libraries, cryptography, numerical libraries and solver dependencies retain their own notices. Packaging follows binary dependency edges; it must not copy a donor environment wholesale. In particular, an unrelated GPL-enabled FFmpeg package must not enter the runtime accidentally.

The package includes source and build instructions for the application. Dynamic library replacement/rebuild directions and exact corresponding-library-source review are described in [dependency licensing](docs/dependency-licensing.md). A missing notice, unidentified native DLL or unresolved source obligation blocks publication. This preparation is not legal clearance for an unchecked artifact.

Codex is installed separately and is not bundled. OpenAI service/account terms, model access and plan/API billing are independent of the repository's license. No credentials, inference key, model weights or private CAD translator are included.
