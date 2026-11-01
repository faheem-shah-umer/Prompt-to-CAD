"""Create a reviewed Windows x64 portable ZIP. No installer or user-data copying."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

from packaging.requirements import Requirement
from tools.build_native import ROOT, add_sdk_arguments, resolve_sdks, build_environment
from tools.source_policy import is_public_source


def dependency_closure():
    pending = [Requirement(line).name for line in (ROOT / "requirements.txt").read_text().splitlines()
               if line.strip() and not line.startswith("#")]
    result = {}
    while pending:
        distribution = metadata.distribution(pending.pop())
        name = distribution.metadata["Name"].lower().replace("_", "-")
        if name in result:
            continue
        result[name] = distribution
        for value in distribution.requires or []:
            requirement = Requirement(value)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    return result


def copy_python(destination):
    base = Path(sys.base_prefix)
    destination.mkdir(parents=True)
    for source in base.iterdir():
        if source.is_file() and (source.suffix.lower() == ".dll" or source.name in ("python.exe", "pythonw.exe", "LICENSE.txt")):
            shutil.copy2(source, destination / source.name)
    shutil.copytree(base / "DLLs", destination / "DLLs", ignore=shutil.ignore_patterns("*.pdb", "*_test*", "_tkinter.pyd"))
    with zipfile.ZipFile(destination / "python311.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for source in (base / "Lib").rglob("*"):
            relative = source.relative_to(base / "Lib")
            if any(part in {"site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "ensurepip", "venv"} for part in relative.parts):
                continue
            if source.is_file() and source.suffix != ".pyc":
                archive.write(source, relative.as_posix())
    site = destination / "Lib/site-packages"
    site.mkdir(parents=True)
    packages = []
    for name, distribution in sorted(dependency_closure().items()):
        package_root = Path(distribution.locate_file("")).resolve()
        notices = []
        for relative in distribution.files or []:
            source = Path(distribution.locate_file(relative)).resolve()
            if not source.is_file() or not source.is_relative_to(package_root) or "__pycache__" in source.parts or source.suffix in (".pyc", ".pdb") or source.name == "direct_url.json":
                continue
            target = site / source.relative_to(package_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if re.search(r"licen[cs]e|notice|copying|copyright", source.name, re.I):
                notices.append(target.relative_to(destination.parent).as_posix())
        if not notices:
            raise RuntimeError(f"No license/notice recorded for Python distribution {name}; package stopped.")
        packages.append({"name": name, "version": distribution.version,
            "license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License") or "See retained notices",
            "notices": notices,
            "source_metadata": distribution.metadata.get_all("Project-URL", [])})
    (destination / "python311._pth").write_text("python311.zip\nDLLs\nLib/site-packages\n.\n../app\nimport site\n", encoding="utf-8")
    return packages


def conda_records(prefix):
    folder = prefix.parent if prefix.name.lower() == "library" else prefix
    result = {}
    for path in (folder / "conda-meta").glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        for relative in record.get("files", []):
            result[(folder / relative).resolve()] = record
    return result


def copy_python_msvc(destination, prefix):
    """Give Python extensions their own CRT, without relying on a global redist."""
    owners = {}
    for source, record in conda_records(prefix).items():
        if (record['name'] in {'vc14_runtime', 'vcomp14'} and source.parent == prefix / 'bin'
                and source.suffix.lower() == '.dll'):
            shutil.copy2(source, destination / source.name)
            owners[source] = record
    if not owners:
        raise RuntimeError('The SDK is missing redistributable MSVC runtime files for bundled Python.')
    return owners


def copy_native(destination, args, env):
    destination.mkdir(parents=True)
    executable = args.build_dir / "bin/PromptToCAD.exe"
    if not executable.is_file():
        raise RuntimeError("Build the application first using the same --build-dir.")
    shutil.copy2(executable, destination)
    plugin_root = args.qt_prefix / "lib/qt6/plugins"
    pending = [destination / executable.name]
    records = {**conda_records(args.qt_prefix), **conda_records(args.occt_prefix)}
    owners = {}
    for relative in ("platforms/qwindows.dll", "imageformats/qjpeg.dll", "imageformats/qwebp.dll"):
        source = plugin_root / relative
        target = destination / "plugins" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        pending.append(target)
        owners[source.resolve()] = records.get(source.resolve())
    (destination / "qt.conf").write_text("[Paths]\nPrefix=.\nPlugins=plugins\n", encoding="utf-8")
    dumpbin = shutil.which("dumpbin", path=env["PATH"])
    if not dumpbin:
        raise RuntimeError("dumpbin is missing; use the x64 Visual Studio developer environment.")
    system = Path(os.environ["SystemRoot"]) / "System32"
    search = [args.occt_prefix / "bin", args.qt_prefix / "bin", Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs", system]
    copied = set()
    while pending:
        output = subprocess.check_output([dumpbin, "/DEPENDENTS", str(pending.pop())], env=env, text=True)
        for name in re.findall(r"^\s+([A-Za-z0-9_.+-]+\.dll)\s*$", output, re.M | re.I):
            if name.lower() in copied or name.lower().startswith(("api-ms-", "ext-ms-")):
                continue
            copied.add(name.lower())
            source = next((folder / name for folder in search if (folder / name).is_file()), None)
            if source is None:
                raise RuntimeError(f"Unresolved native DLL: {name}")
            if source.parent == system:
                if name.lower().startswith(("msvcp", "vcruntime", "concrt", "vcomp")):
                    raise RuntimeError(f"{name} is available only from the host OS; install a redistributable SDK runtime before packaging.")
                continue
            target = destination / name
            shutil.copy2(source, target)
            pending.append(target)
            owners[source.resolve()] = records.get(source.resolve())
    resources = args.occt_prefix / "share/opencascade/resources/Shaders"
    if not resources.is_dir():
        raise RuntimeError("OCCT shader resources are missing.")
    shutil.copytree(resources, destination / "resources/Shaders")
    return owners


def recipe_source_access(package):
    rendered = package / 'info/recipe/meta.yaml'
    text = rendered.read_text(encoding='utf-8') if rendered.is_file() else ''
    declaration = re.search(r'(?ms)^source:\n(.*?)(?=^[A-Za-z_][A-Za-z_]*:|\Z)', text)
    commit = re.search(r'(?m)^  sha: ([a-f0-9]{40})$', text)
    repository = re.search(r'(?m)^  remote_url: (https://[^\s]+)$', text)
    return {"rendered_source_declaration": declaration[1].strip() if declaration else None,
        "recipe_repository": repository[1] if repository else None,
        "recipe_commit": commit[1] if commit else None,
        "corresponding_source_verified": False}


def native_notices(bundle, owners, args):
    components = {}
    records = {**conda_records(args.qt_prefix), **conda_records(args.occt_prefix)}
    for source, record in owners.items():
        if not record:
            raise RuntimeError(f"No dependency provenance for {source.name}; use the fresh SDK created by tools.setup_windows.")
        identity = f'{record["name"]}-{record["version"]}-{record["build"]}'
        if identity in components:
            continue
        candidates = []
        if record.get("link", {}).get("source"):
            candidates.append(Path(record["link"]["source"]))
        if record.get("extracted_package_dir"):
            candidates.append(Path(record["extracted_package_dir"]))
        package = next((path for path in candidates if (path / "info/licenses").is_dir()), None)
        # The FreeType recipe puts notices in its matching development output,
        # while the split DLL output has no licence files of its own.
        notice_owner = record
        if package is None and record["name"] == "libfreetype6":
            notice_owner = next((item for item in records.values()
                if item["name"] == "freetype" and item["version"] == record["version"]), None)
            if notice_owner:
                candidate = Path(notice_owner.get("link", {}).get("source", ""))
                if (candidate / "info/licenses").is_dir():
                    package = candidate
        if package is None:
            raise RuntimeError(f"Missing retained license texts for native package {identity}.")
        target = bundle / "licences/native" / identity
        shutil.copytree(package / "info/licenses", target)
        # Only portable recipe files are copied; rendered build configuration contains host paths.
        recipe = package / "info/recipe"
        if recipe.is_dir():
            for path in recipe.rglob("*"):
                if path.is_file() and path.suffix in (".patch", ".diff"):
                    destination = target / "patches" / path.relative_to(recipe)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, destination)
        about = json.loads((package / "info/about.json").read_text()) if (package / "info/about.json").is_file() else {}
        components[identity] = {"name": record["name"], "version": record["version"], "build": record["build"],
            "license": record.get("license", "See retained notices"), "package_url": record.get("url"),
            "sha256": record.get("sha256"), "upstream": about.get("dev_url") or about.get("home"),
            "notices": target.relative_to(bundle).as_posix(),
            "notice_package": notice_owner["name"] if notice_owner else None,
            "selected_license": {"libfreetype6": "FTL", "freeimage": "FreeImage Public License (FIPL)"}.get(record['name'], record.get('license')),
            "source_access": recipe_source_access(package)}
    return list(components.values())


def public_sources(bundle):
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    source = bundle / "source"
    for name in sorted(set(names)):
        if not name or not is_public_source(name):
            continue
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("Source inclusion refused a missing file or filesystem link.")
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if name.startswith(("backend/native/", "backend/v2/")) or name == "backend/__init__.py":
            runtime = bundle / "app" / name
            runtime.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, runtime)
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, bundle / name)
    shutil.copytree(source / "docs", bundle / "docs", dirs_exist_ok=True)


def distribution_files(bundle):
    """The portable inventory excludes user folders even if added to staging."""
    bundle = Path(bundle).resolve()
    result = []
    for folder in ("bin", "python", "licences", "source", "app", "docs"):
        for path in (bundle / folder).rglob("*"):
            if not path.is_file():
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(bundle):
                raise RuntimeError("Distribution inventory contains a filesystem link.")
            relative = path.relative_to(bundle / folder).as_posix()
            if folder == "source" and not is_public_source(relative):
                continue
            if folder == "app" and not (relative.startswith("backend/") and is_public_source(relative)):
                continue
            if folder == "docs" and not is_public_source("docs/" + relative):
                continue
            if path.suffix.lower() in (".dpapi", ".pdb", ".pyc") or path.name in ("auth.json", "credentials.json", ".env"):
                raise RuntimeError("Credential or development file in distribution inventory.")
            result.append(path)
    result.extend(bundle / name for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "runtime-manifest.json", "Start-PromptToCAD.cmd") if (bundle / name).is_file())
    return sorted(result)


def finish_bundle(bundle, packages, native, smoke_test=False):
    from tools.prepare_legal_texts import prepare
    shutil.copytree(prepare(), bundle / "licences/supplemental", dirs_exist_ok=True)
    public_sources(bundle)
    version = (ROOT / "VERSION").read_text().strip()
    manifest = {"version": version, "target": "windows-x64", "python": platform.python_version(),
        "qt": "6.9.0", "occt": "7.8.1", "packages": packages, "native": native,
        "publication_ready": False, "pending_gates": ["clean Windows runner", "corresponding-source licensing review", "publication approval"]}
    (bundle / "runtime-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (bundle / "README.md").write_text(f"# Prompt to CAD {version} · Windows x64 preview\n\nExtract the entire folder to a writable location. Run Start-PromptToCAD.cmd or bin/PromptToCAD.exe. No administrator privileges or development SDK are required. This is an unsigned review candidate, not a production CAD certification.\n\nPython and native CAD runtimes are included. For AI features, install Codex separately and connect your own eligible ChatGPT account or separately billed API key in Settings. Offline import, viewing, measurement, supported direct edits and export do not need AI.\n\nProjects are local in Projects/; backend preferences are in .promptcad/. Native appearance preferences use Windows user settings; logs use local application data. Windows-protected account storage is separate. The archive contains no account, project or conversation data. See docs/privacy.md, runtime-manifest.json, THIRD_PARTY_NOTICES.md and licences/.\n\nBuildable application source is under source/. Dynamic libraries remain replaceable; see docs/dependency-licensing.md. Publishing is withheld until every release gate is verified.\n", encoding="utf-8")
    (bundle / "Start-PromptToCAD.cmd").write_text('@echo off\r\nset "PATH=%~dp0bin;%PATH%"\r\nstart "" "%~dp0bin\\PromptToCAD.exe"\r\n', encoding="utf-8")
    if smoke_test:
        from tools.smoke_package import check_package
        check_package(bundle)
    from tools.audit_package import audit
    audit(bundle)
    files = distribution_files(bundle)
    manifest["files"] = {path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in files if path.name != "runtime-manifest.json"}
    (bundle / "runtime-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    archive = bundle.parent / f"PromptToCAD-{version}-windows-x64.zip"
    if archive.exists():
        raise RuntimeError("Versioned ZIP already exists; choose another output parent. No archive was overwritten.")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in distribution_files(bundle):
            output.write(path, f"PromptToCAD-{version}/" + path.relative_to(bundle).as_posix())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Review candidate created: {archive.name}; publication gates remain pending.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_sdk_arguments(parser)
    parser.add_argument("--output", type=Path, required=True, help="A new empty staging directory; never refreshed or overwritten.")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11) or os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64"):
        parser.error("Package with CPython 3.11 on Windows x64.")
    resolve_sdks(args)
    bundle = args.output.resolve()
    if bundle.exists():
        parser.error("Output already exists. Choose a new staging directory; no files were changed.")
    bundle.mkdir(parents=True)
    env = build_environment(args.qt_prefix, args.occt_prefix, args.toolchain_env)
    print("Copying the reviewed Python runtime...", flush=True)
    packages = copy_python(bundle / "python")
    print("Resolving native DLL dependencies...", flush=True)
    owners = copy_native(bundle / "bin", args, env)
    owners.update(copy_python_msvc(bundle / 'python', args.qt_prefix))
    native = native_notices(bundle, owners, args)
    finish_bundle(bundle, packages, native, args.smoke_test)


if __name__ == "__main__":
    main()
