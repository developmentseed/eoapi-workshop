#!/usr/bin/env python3
"""Print the STAC collection ids that a database reset must preserve.

The "fixtures" are whatever the Load Workshop Data step of `.github/workflows/deploy.yml`
puts in the database. Everything else in the catalog is a workshop participant's leftover
and is what `reset-data.yml` removes.

Most fixtures come from files in `data/`, so they are discovered rather than listed --
adding a fixture file is enough, with nothing to keep in sync here. Fixtures fetched from
a remote STAC API have no local file, so those ids are listed in REMOTE_FIXTURES below.

Usage:
    python scripts/fixture_collections.py            # one id per line
    python scripts/fixture_collections.py --check    # also report where each came from
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

# Fixtures loaded from a remote STAC API, so there is no file in data/ to discover them
# from. Keep in step with the `pypgstac load` calls in .github/workflows/deploy.yml.
REMOTE_FIXTURES = {
    "glad-global-forest-change-1.11",  # fetched from https://stac.maap-project.org
}


def _records(path: Path):
    """Yield the JSON objects in a .json or newline-delimited .ndjson file."""
    text = path.read_text().strip()
    if not text:
        return
    if path.suffix == ".ndjson":
        for line in text.splitlines():
            line = line.strip()
            if line:
                yield json.loads(line)
        return
    parsed = json.loads(text)
    if isinstance(parsed, list):
        yield from parsed
    else:
        yield parsed


def discover(data_dir: Path = DATA_DIR) -> dict[str, str]:
    """Map collection id -> where it was found."""
    found: dict[str, str] = {cid: "deploy.yml (remote)" for cid in REMOTE_FIXTURES}

    for path in sorted(data_dir.glob("*.json")) + sorted(data_dir.glob("*.ndjson")):
        for record in _records(path):
            if not isinstance(record, dict):
                continue
            # A Collection names itself; an Item names the collection it belongs to.
            if record.get("type") == "Collection" and record.get("id"):
                found.setdefault(record["id"], path.name)
            elif record.get("collection"):
                found.setdefault(record["collection"], path.name)

    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="show where each id was found"
    )
    args = parser.parse_args()

    found = discover()
    if not found:
        print("no fixture collections discovered", file=sys.stderr)
        return 1

    for cid in sorted(found):
        print(f"{cid}\t{found[cid]}" if args.check else cid)
    return 0


def demo() -> None:
    """Self-check: `python scripts/fixture_collections.py --selftest`."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "c.json").write_text(json.dumps({"type": "Collection", "id": "fix-a"}))
        (d / "i.ndjson").write_text(
            json.dumps({"type": "Feature", "id": "x", "collection": "fix-b"})
            + "\n"
            + json.dumps({"type": "Feature", "id": "y", "collection": "fix-b"})
            + "\n"
        )
        (d / "empty.ndjson").write_text("\n")

        found = discover(d)

    assert "fix-a" in found, found
    assert "fix-b" in found, found
    assert REMOTE_FIXTURES <= set(found), found
    # Nothing invented: only what the files and REMOTE_FIXTURES name.
    assert set(found) == {"fix-a", "fix-b"} | REMOTE_FIXTURES, found
    print("fixture_collections: all checks passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        demo()
    else:
        raise SystemExit(main())
