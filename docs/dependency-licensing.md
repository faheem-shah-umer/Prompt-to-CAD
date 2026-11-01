# Dependency redistribution and source-access gates

The portable ZIP is a review candidate until its exact inventory has passed these checks. Application MIT licensing alone does not authorize redistribution of every dependency.

## Required material

- Preserve Python's actual distribution license and all Python-wheel license/notice files. CasADi's bundled solver notices, including `include/licenses`, must not be removed as developer-only files.
- For each non-system native DLL, record its owning package, version, build, binary hash, selected license and notice location. Missing ownership or license material is a packaging error.
- Keep the application dynamically linked to replaceable Qt/OCCT DLLs. Include application source/build instructions; do not prevent users from replacing compatible libraries or debugging modifications.
- Retain Qt's LGPLv3 **and GPLv3** texts, Qt third-party notices, and OCCT's LGPL2.1 text and exception. Handle LibRaw, FreeImage, CasADi/solvers and other copyleft/source-availability terms individually.
- Retain exact corresponding source and immutable build recipes/patches for the actual binaries, or provide verified equivalent source access compliant with the selected terms. An upstream version link alone can omit conda patches. Do not promise “source on request” without an actual supported offer.
- Mirror required corresponding-source archives/recipes with hashes beside a published release where needed. They are release compliance artifacts, not SDKs to commit into application Git.
- Use Microsoft's actual redistributable-runtime terms for CRT DLLs. Do not copy arbitrary system DLLs or call them BSD because a package wrapper uses that label.

## Verified primary references

| Component | Source/obligation reference |
| --- | --- |
| Qt | [LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations), [Qt 6.9 licensing](https://doc.qt.io/archives/qt-6.9/licensing.html), [6.9.0 source](https://download.qt.io/archive/qt/6.9/6.9.0/single/qt-everywhere-src-6.9.0.tar.xz), [exact main-package recipe/patches](https://github.com/conda-forge/qt-main-feedstock/tree/ae60e296d89295a053245c3c4a4ccf5bb8ea1c30/recipe) |
| OCCT | [7.8.1 LGPL exception](https://raw.githubusercontent.com/Open-Cascade-SAS/OCCT/V7_8_1/OCCT_LGPL_EXCEPTION.txt), [exact main-package recipe with patches](https://github.com/conda-forge/occt-feedstock/tree/4237a64ca19105111b57b8d18535e9de717d8870/recipe) |
| OCP | [bindings license](https://raw.githubusercontent.com/CadQuery/OCP/7.8.1.1/LICENSE); wrapped OCCT retains separate obligations |
| CasADi | [3.8.2 release/source/build information](https://github.com/casadi/casadi/releases/tag/3.8.2) and each retained solver notice |
| Python | [Python 3.11 license](https://docs.python.org/3.11/license.html) plus the actual packaged runtime's LICENSE.txt |
| Source access | [GPLv3 §6](https://www.gnu.org/licenses/gpl-3.0.html#section6), [LGPLv3 §4](https://www.gnu.org/licenses/lgpl-3.0.html) |

The original icon blocker is resolved for the current tree by replacing extracted Flaticon glyphs with original geometric drawings. Historical Git content is unchanged and is not newly cleared by this replacement.

## Replace or rebuild dynamic libraries

Keep the extracted application stopped. Back up its `bin/` directory, then replace compatible Qt 6.9.0 / OCCT 7.8.1 libraries and their matching dependencies/plugins. Maintain x64 architecture and ABI compatibility. Use a separate copy for experimentation. Rebuild application source using `source/docs/setup.md` (or the repository setup guide) with your chosen compatible SDK prefixes. The application has no technical library-replacement lock or anti-modification check. Runtime geometry asset checks protect project data; they do not prohibit replacing library DLLs.

The current candidate manifest explicitly records that final corresponding-source verification and clean Windows testing are pending. Do not publish it as redistribution-cleared until those gates are resolved.

Native manifest entries preserve the cached package's rendered upstream source declaration and immutable recipe repository/commit where available. These are review inputs, with `corresponding_source_verified: false`; they are not a claim that all source archives were mirrored or all Qt/solver third-party notices were independently cleared. The candidate retains FreeType's FTL text (the selected alternative), FreeImage's FIPL route, supplemental Qt GPLv3 text and the OCCT exception. Required upstream authorship remains intact.
