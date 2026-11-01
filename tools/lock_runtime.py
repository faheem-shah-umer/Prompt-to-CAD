"""Record the resolved runtime dependency versions for review (not local environment paths)."""
import importlib.metadata as metadata
from packaging.requirements import Requirement
from tools.build_native import ROOT


def dependency_closure():
    pending = [Requirement(line).name for line in (ROOT / 'requirements.txt').read_text().splitlines()
               if line.strip() and not line.startswith('#')]
    result = {}
    while pending:
        distribution = metadata.distribution(pending.pop())
        name = distribution.metadata['Name'].lower().replace('_', '-')
        if name in result:
            continue
        result[name] = distribution
        for value in distribution.requires or []:
            requirement = Requirement(value)
            if requirement.marker is None or requirement.marker.evaluate({'extra': ''}):
                pending.append(requirement.name)
    return result


def main():
    lines = ["# Resolved Windows CPython 3.11 runtime set. Regenerate deliberately with python -m tools.lock_runtime."]
    lines += [f"{name}=={distribution.version}" for name, distribution in sorted(dependency_closure().items())]
    (ROOT / "requirements-runtime-lock.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
