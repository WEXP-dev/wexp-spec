# Draft toolchain

The publication pipeline builds its own toolchain. It must never use whatever
`xml2rfc` or `idnits` happens to be on a developer's `PATH`, and it must never
borrow another project's private toolchain directory.

This is not tidiness. `xml2rfc` embeds a generator block into rendered HTML
listing the interpreter version and every installed dependency version:

```html
<!-- Generator version information:
  xml2rfc 3.34.0
    Python 3.12.13
    ConfigArgParse 1.7.5
    ...
-->
```

So two environments that both report `xml2rfc 3.34.0` produce different HTML
bytes if their interpreter or any dependency differs. An ambient toolchain makes
every reproducibility statement in a publication bundle unfalsifiable. Rendered
plaintext, by contrast, was observed to be environment-independent for this
document — but that is an observation about one document, not a rule to rely on.

## Files

| File | Role |
|---|---|
| `toolchain.json` | authoritative declaration: interpreter, exact package versions, linter version and integrity, and where the pins came from |
| `python-toolchain.lock` | generated hash-pinned pip requirements; every SHA-256 published for each pinned version, so the lock is valid on any platform |
| `node/package.json`, `node/package-lock.json` | the pinned draft linter, installed with `npm ci` |
| `refresh_toolchain_lock.py` | regenerates `python-toolchain.lock` from `toolchain.json`; run only when a pin changes |

## Provisioning

```sh
python3 scripts/provision_toolchain.py
export PATH="$(python3 -c 'import json;print(json.load(open("build/toolchain/TOOLCHAIN.json"))["bin"])'):$PATH"
```

This builds `build/toolchain/` (git-ignored), installs Python packages with
`pip --require-hashes` and the linter with `npm ci`, verifies that what was
installed matches the declaration, and writes `build/toolchain/TOOLCHAIN.json`
recording the interpreter, package versions, lock digests, and the on-disk
SHA-256 of each tool's entry point.

The interpreter is pinned to the major.minor version the lock was resolved
against. Provisioning refuses an interpreter that lives in a temporary
directory or inside another project's `.tools` directory, because such an
interpreter can change or vanish with no record. Install one with
`uv python install 3.12` or `brew install python@3.12`, or point
`WEXP_TOOLCHAIN_PYTHON` at an existing interpreter.

## Updating a pin

1. Edit the version in `toolchain.json` (and `node/package.json` for the linter).
2. For Python, re-resolve and confirm the transitive set, then run
   `python3 tools/refresh_toolchain_lock.py`.
3. For the linter, run `npm install --package-lock-only` in `tools/node`.
4. Re-provision, re-run the Core-00 exercise, and record any change in rendered
   bytes. A toolchain change that alters rendered output is a reviewable event,
   not a silent upgrade.
