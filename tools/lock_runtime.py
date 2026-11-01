"""Record the resolved runtime dependency versions for review (not local environment paths)."""
from tools.package_native import dependency_closure
from tools.build_native import ROOT


def main():
    lines = ["# Resolved Windows CPython 3.11 runtime set. Regenerate deliberately with python -m tools.lock_runtime."]
    lines += [f"{name}=={distribution.version}" for name, distribution in sorted(dependency_closure().items())]
    (ROOT / "requirements-runtime-lock.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
