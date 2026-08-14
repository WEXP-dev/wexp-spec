#!/usr/bin/env python3
"""Provision the IETF draft toolchain this repository owns.

The publication pipeline must never depend on whatever renderer or linter
happens to be installed on the machine running it. A different ``xml2rfc``
silently produces different rendered bytes, and a different ``idnits`` silently
produces a different verdict, so an ambient toolchain would make every
reproducibility claim in a publication bundle unfalsifiable.

This script builds a self-contained toolchain under ``build/toolchain`` from the
pins in ``tools/toolchain.json``:

* Python packages from ``tools/python-toolchain.lock`` installed with
  ``pip --require-hashes``, so any unpinned or tampered distribution aborts the
  install;
* ``@ietf-tools/idnits`` from ``tools/node/package-lock.json`` installed with
  ``npm ci``, which refuses to run if the lockfile and manifest disagree.

It then records what it actually got in ``build/toolchain/TOOLCHAIN.json``,
including the on-disk SHA-256 of each executable's entry point, and prints the
directory to prepend to ``PATH``.

Usage:

    python3 scripts/provision_toolchain.py
    export PATH="$(python3 scripts/provision_toolchain.py --print-path):$PATH"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = ROOT / "tools" / "toolchain.json"
PYTHON_LOCK = ROOT / "tools" / "python-toolchain.lock"
NODE_DIR = ROOT / "tools" / "node"
DEFAULT_PREFIX = ROOT / "build" / "toolchain"


class ProvisioningError(RuntimeError):
    """Raised when the toolchain cannot be built exactly as declared."""


def run(command: Sequence[str], *, cwd: Path | None = None, quiet: bool = True) -> str:
    result = subprocess.run(
        list(command),
        cwd=str(cwd) if cwd else None,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise ProvisioningError(
            f"{' '.join(command)} failed with exit {result.returncode}:\n{result.stdout.strip()}"
        )
    if not quiet and result.stdout.strip():
        print(result.stdout.strip())
    return result.stdout


def rejection_reason(path: Path) -> str:
    """Reject interpreters that would reintroduce an ambient dependency.

    A toolchain borrowed from another project, or one living in a temporary
    directory, cannot be the authoritative environment for a publication: it can
    change or disappear without any record, which is exactly the failure mode
    hash-pinning the packages is meant to remove.
    """

    resolved = path.resolve()
    parts = resolved.parts
    if ".tools" in parts:
        return f"{resolved} belongs to another project's private toolchain"
    for temporary in ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/"):
        if str(resolved).startswith(temporary):
            return f"{resolved} lives in a temporary directory and is not durable"
    return ""


def candidate_interpreters(required: str) -> list[Path]:
    """Standard, neutral places to look for the pinned interpreter."""

    candidates: list[Path] = []
    explicit = os.environ.get("WEXP_TOOLCHAIN_PYTHON")
    if explicit:
        candidates.append(Path(explicit))
    for name in (f"python{required}", "python3"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    home = Path.home()
    candidates.extend(
        [
            home / ".local/share/uv/python" / f"cpython-{required}-macos-aarch64-none/bin/python3",
            home / ".local/share/uv/python" / f"cpython-{required}-linux-x86_64-gnu/bin/python3",
            Path(f"/opt/homebrew/opt/python@{required}/bin/python{required}"),
            Path(f"/usr/local/opt/python@{required}/bin/python{required}"),
            Path(f"/usr/bin/python{required}"),
            Path(sys.executable),
        ]
    )
    return candidates


def find_interpreter(required: str, *, explicit: str | None = None) -> Path:
    """Locate a durable CPython matching the declared major.minor version."""

    rejected: list[str] = []
    candidates = [Path(explicit)] if explicit else candidate_interpreters(required)
    seen: set[Path] = set()
    for candidate in candidates:
        if not candidate.exists() or candidate in seen:
            continue
        seen.add(candidate)
        try:
            version = run([str(candidate), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"]).strip()
        except ProvisioningError:
            continue
        if version != required:
            continue
        reason = rejection_reason(candidate)
        if reason:
            rejected.append(reason)
            continue
        return candidate

    detail = "; rejected: " + "; ".join(rejected) if rejected else ""
    raise ProvisioningError(
        f"no durable CPython {required} interpreter found{detail}. The toolchain pins that "
        f"version because the lock records the distributions resolved for it. Install one with "
        f"'uv python install {required}' or 'brew install python@{required}', or point "
        f"WEXP_TOOLCHAIN_PYTHON at an existing interpreter"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def provision_python(
    prefix: Path, declaration: dict[str, Any], *, explicit: str | None = None
) -> dict[str, Any]:
    required = str(declaration["interpreter"]["version"])
    interpreter = find_interpreter(required, explicit=explicit)
    venv = prefix / "python"
    if venv.exists():
        shutil.rmtree(venv)
    run([str(interpreter), "-m", "venv", str(venv)])
    python = venv / "bin" / "python"
    run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--quiet",
         "--require-hashes", "--requirement", str(PYTHON_LOCK)])

    installed = {}
    for line in run([str(python), "-m", "pip", "list", "--format=freeze"]).splitlines():
        if "==" in line:
            name, _, version = line.partition("==")
            installed[name.strip().lower().replace("_", "-")] = version.strip()

    declared = {name.lower().replace("_", "-"): version for name, version in declaration["python_packages"].items()}
    mismatched = [
        f"{name}: declared {version}, installed {installed.get(name, 'absent')}"
        for name, version in declared.items()
        if installed.get(name) != version
    ]
    if mismatched:
        raise ProvisioningError("provisioned Python packages differ from the declaration: " + "; ".join(mismatched))

    return {
        "interpreter": run([str(python), "-V"]).strip(),
        "source_interpreter": str(interpreter.resolve()),
        "interpreter_path": str(python),
        "packages": {name: declared[name] for name in sorted(declared)},
        "lock": PYTHON_LOCK.relative_to(ROOT).as_posix(),
        "lock_sha256": sha256_file(PYTHON_LOCK),
    }


def provision_node(prefix: Path, declaration: dict[str, Any]) -> dict[str, Any]:
    if shutil.which("npm") is None:
        raise ProvisioningError("npm is required to provision the pinned draft linter")
    node_root = prefix / "node"
    if node_root.exists():
        shutil.rmtree(node_root)
    node_root.mkdir(parents=True)
    for name in ("package.json", "package-lock.json"):
        shutil.copyfile(NODE_DIR / name, node_root / name)
    run(["npm", "ci", "--no-fund", "--no-audit", "--ignore-scripts"], cwd=node_root)

    lock = json.loads((node_root / "package-lock.json").read_text(encoding="utf-8"))
    entry = lock["packages"][f"node_modules/{declaration['node']['package']}"]
    if entry["version"] != declaration["node"]["version"]:
        raise ProvisioningError(
            f"provisioned {declaration['node']['package']} {entry['version']} "
            f"but {declaration['node']['version']} is declared"
        )
    if entry["integrity"] != declaration["node"]["integrity"]:
        raise ProvisioningError("provisioned linter integrity does not match the declaration")
    return {
        "package": declaration["node"]["package"],
        "version": entry["version"],
        "integrity": entry["integrity"],
        "resolved": entry.get("resolved"),
        "lock": (NODE_DIR / "package-lock.json").relative_to(ROOT).as_posix(),
        "lock_sha256": sha256_file(NODE_DIR / "package-lock.json"),
    }


def link_executables(prefix: Path) -> dict[str, dict[str, str]]:
    """Expose exactly the declared tools on one directory, and nothing else."""

    bin_dir = prefix / "bin"
    if bin_dir.exists():
        shutil.rmtree(bin_dir)
    bin_dir.mkdir(parents=True)
    sources = {
        "xml2rfc": prefix / "python" / "bin" / "xml2rfc",
        "idnits": prefix / "node" / "node_modules" / ".bin" / "idnits",
    }
    recorded: dict[str, dict[str, str]] = {}
    for name, source in sources.items():
        if not source.exists():
            raise ProvisioningError(f"{name} was not provisioned at {source}")
        target = bin_dir / name
        target.write_text(f'#!/usr/bin/env sh\nexec "{source}" "$@"\n', encoding="utf-8")
        target.chmod(0o755)
        recorded[name] = {
            "path": str(target),
            "target": str(source),
            "entry_point_sha256": sha256_file(source.resolve()),
        }
    return recorded


def observed_versions(bin_dir: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment["PATH"] = f"{bin_dir}:{environment.get('PATH', '')}"
    versions: dict[str, str] = {}
    for name, arguments in (("xml2rfc", ["--version"]), ("idnits", ["--version"])):
        result = subprocess.run(
            [str(bin_dir / name), *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        versions[name] = result.stdout.strip().splitlines()[0].strip() if result.stdout.strip() else ""
    return versions


def provision(prefix: Path, *, interpreter: str | None = None) -> dict[str, Any]:
    declaration = json.loads(DECLARATION.read_text(encoding="utf-8"))
    prefix.mkdir(parents=True, exist_ok=True)
    python = provision_python(prefix, declaration, explicit=interpreter)
    node = provision_node(prefix, declaration)
    executables = link_executables(prefix)
    record = {
        "schema_version": 1,
        "record_kind": "wexp-provisioned-toolchain",
        "prefix": str(prefix),
        "bin": str(prefix / "bin"),
        "declaration": {
            "path": DECLARATION.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(DECLARATION),
        },
        "python": python,
        "node": node,
        "executables": executables,
        "observed_versions": observed_versions(prefix / "bin"),
        "provenance": declaration.get("provenance"),
        "non_claims": [
            "A provisioned toolchain is not evidence of draft correctness.",
            "Hash pinning binds the distributions installed, not the behaviour of the tools.",
        ],
    }
    (prefix / "TOOLCHAIN.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=DEFAULT_PREFIX)
    parser.add_argument(
        "--interpreter",
        default=None,
        help="explicit CPython to build the venv from; overrides discovery",
    )
    parser.add_argument(
        "--print-path",
        action="store_true",
        help="print only the bin directory, for use in PATH",
    )
    args = parser.parse_args(argv)

    try:
        record = provision(args.prefix.resolve(), interpreter=args.interpreter)
    except ProvisioningError as exc:
        print(f"TOOLCHAIN NOT PROVISIONED — {exc}", file=sys.stderr)
        return 1

    if args.print_path:
        print(record["bin"])
        return 0
    for name, version in record["observed_versions"].items():
        print(f"{name}: {version}")
    print(f"record: {Path(record['prefix']) / 'TOOLCHAIN.json'}")
    print(f"bin: {record['bin']}")
    print("TOOLCHAIN PROVISIONED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
