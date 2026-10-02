"""Execute docs/00..08 headless on COPIES, inside the Lab container.

Run by run.sh as:  python nbrun.py <phase> [<phase> ...]
Phases (each gets a fresh copy of /home/jovyan/docs under ROOT/<phase>/):

  reset   delete this topic's collections left by an earlier run (spike-notebooks-*,
          private-<owner>-spike-notebooks*), so every run starts from the same catalog
  docs    00-05 as committed + the 06/07/08 link cells (no writes), with
          WORKSHOP_USER=spike-notebooks so collection_id() is ours; 02 creates the
          collection 03/04 read. First checks that the fixes.py edits are still in docs/.
  writes  06 07 08, ids rewritten to spike-notebooks-* (HARNESS); run LAST, once
  audit   read-only: after `writes`, only 02's collection is left under our prefix

The fixes.py edits were proposed and tested on copies (phases asis/participant/zeropoint/
fixed, spike/evidence/notebooks.md), then applied to docs/ (spike/evidence/fix.md).

02's location is pinned (HARNESS) so runs load the same items: (148.09, -37.47), one of the
default points, 1,136 items (the median default point loads 1,144; points.py).

Never writes to /home/jovyan/docs (the bind-mounted repo).
"""

import json
import os
import shutil
import subprocess
import sys
import time

ROOT = "/tmp/nbrun-notebooks"
DOCS = "/home/jovyan/docs"
USER = "spike-notebooks"

PHASES = {
    "docs": [
        "00-introduction",
        "01-stac_metadata",
        "02-database",
        "03-stac_fastapi_pgstac",
        "04-titiler_pgstac",
        "05-tipg",
        "0608-links",
    ],
    "writes": [
        "06-stac_transactions_auth",
        "07-row_level_auth",
        "08-stac_browser_auth",
    ],
}

# Harness substitutions: (notebook, cell index, old, new). They stand in for what a
# participant types into a widget, and keep the ids this run creates under the
# spike-notebooks prefix so concurrent testers' data (and notebook 08's fixed ids
# public-demo / private-*-notebook) are never touched. Each `old` must match exactly.
HARNESS = [
    # participant types a location: pinned so every run loads the same items
    (
        "docs",
        "02-database",
        2,
        "default_lon, default_lat = get_random_point()",
        "default_lon, default_lat = 148.09, -37.47  # harness: a default point, 1,136 items",
    ),
    # 06: run-scoped ids under our prefix
    (
        "writes",
        "06-stac_transactions_auth",
        4,
        'f"tx-workshop-{run_id}"',
        f'f"{USER}-tx-{{run_id}}"',
    ),
    (
        "writes",
        "06-stac_transactions_auth",
        4,
        'f"tx-item-{run_id}"',
        f'f"{USER}-tx-item-{{run_id}}"',
    ),
    # 07: private ids must keep the private-<owner>- prefix the TenantFilter keys on
    (
        "writes",
        "07-row_level_auth",
        9,
        'f"public-demo-{run_id}"',
        f'f"{USER}-public-{{run_id}}"',
    ),
    (
        "writes",
        "07-row_level_auth",
        9,
        'f"private-alice-{run_id}"',
        f'f"private-alice-{USER}-{{run_id}}"',
    ),
    (
        "writes",
        "07-row_level_auth",
        9,
        'f"private-bob-{run_id}"',
        f'f"private-bob-{USER}-{{run_id}}"',
    ),
    # 08: never touch the fixed demo ids another tester may be logged in to
    ("writes", "08-stac_browser_auth", 6, '"public-demo"', f'"{USER}-public-demo"'),
    (
        "writes",
        "08-stac_browser_auth",
        6,
        '"private-alice-notebook"',
        f'"private-alice-{USER}"',
    ),
    (
        "writes",
        "08-stac_browser_auth",
        6,
        '"private-bob-notebook"',
        f'"private-bob-{USER}"',
    ),
]


def src(cell):
    return "".join(cell["source"])


def load(path):
    raw = open(path, encoding="utf-8").read()
    nb = json.loads(raw)
    nb["_ascii"] = (
        "\\u" in raw
    )  # 06/07 are stored with escaped non-ASCII; keep diffs minimal
    return nb


def save(nb, path):
    """Write like Jupyter does (line-list sources, indent 1, sorted keys)."""
    nb = dict(nb)
    ascii_ = nb.pop("_ascii", False)
    for c in nb["cells"]:
        if isinstance(c["source"], str):
            c["source"] = c["source"].splitlines(keepends=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(nb, indent=1, sort_keys=True, ensure_ascii=ascii_) + "\n")


def apply_harness(nbdir, phase):
    lines = []
    for phases, name, idx, old, new in HARNESS:
        path = f"{nbdir}/{name}.ipynb"
        if phase not in phases.split():  # asis runs unmodified
            continue
        nb = load(path)
        s = src(nb["cells"][idx])
        if old not in s:
            lines.append(
                f"FAIL harness.{phase}.{name}[{idx}] — expected text not found: {old}"
            )
            continue
        nb["cells"][idx]["source"] = s.replace(old, new)
        save(nb, path)
        lines.append(f"PASS harness.{phase}.{name}[{idx}] — {old} -> {new}")
    return lines


def check_fixes(nbdir):
    """The fixes.py edits are in docs/: each replaced cell's old text is gone (and the
    empty 00[23] now holds its new source), each markdown passage reads the new text."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import fixes

    lines, nbs = [], {}
    checks = [
        (name, e["cell"], e["expect"], e["source"], False)
        for name, es in fixes.FIXES.items()
        for e in es
    ]
    checks += [
        (name, i, old, new, True) for (name, i), (old, new) in fixes.MD_REPLACE.items()
    ]
    for name, idx, old, new, passage in checks:
        s = src(nbs.setdefault(name, load(f"{nbdir}/{name}.ipynb"))["cells"][idx])
        ok = new in s if passage else (s == new if not old else old not in s)
        lines.append(
            f"{'PASS' if ok else 'FAIL'} fixes.{name}[{idx}] — "
            f"{'edit in place' if ok else 'docs/ no longer holds the applied edit'}"
        )
    return lines


def links_notebook(nbdir):
    """The 06/07/08 link cells alone: those notebooks' writes run once, in `writes`."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import fixes

    nbs = {name: load(f"{nbdir}/{name}.ipynb") for name, _ in fixes.LINKS}
    prelude = {
        "cell_type": "code",
        "metadata": {},
        "outputs": [],
        "execution_count": None,
        "source": fixes.LINKS_PRELUDE,
    }
    save(
        dict(
            nbs["08-stac_browser_auth"],
            cells=[prelude] + [nbs[name]["cells"][i] for name, i in fixes.LINKS],
        ),
        f"{nbdir}/0608-links.ipynb",
    )
    return []


OURS = f"id LIKE '{USER}-%' OR id LIKE 'private-%-{USER}%'"


def drop_ours(phase, where=OURS):
    """Delete this topic's collections (and their items) straight in pgstac."""
    from pypgstac.db import PgstacDB

    with PgstacDB() as db:
        ids = [
            r[0]
            for r in db.query(f"SELECT id FROM collections WHERE {where} ORDER BY id;")
        ]
        for cid in ids:
            n = db.query_one(
                "SELECT count(*) FROM items WHERE collection = %s;", (cid,)
            )
            list(db.query("SELECT delete_collection(%s);", (cid,)))
            print(f"PASS {phase}.drop — {cid} ({n} items)", flush=True)
        left = db.query_one(f"SELECT count(*) FROM collections WHERE {where};")
    print(
        f"{'PASS' if not left else 'FAIL'} {phase}.clean — {len(ids)} dropped, {left} left",
        flush=True,
    )


def audit():
    """Read-only, after `writes`: 06-08 deleted what they created; only 02's collection stays."""
    from pypgstac.db import PgstacDB

    with PgstacDB() as db:
        ids = [
            r[0]
            for r in db.query(f"SELECT id FROM collections WHERE {OURS} ORDER BY id;")
        ]
        orphans = db.query_one(
            "SELECT count(*) FROM items WHERE collection NOT IN (SELECT id FROM collections);"
        )
    extra = [i for i in ids if i != f"{USER}-sentinel-2-c1-l2a"]
    print(
        f"{'PASS' if not extra and not orphans else 'FAIL'} audit.clean — ours left: {ids}; "
        f"unexpected: {extra}; items without a collection: {orphans}",
        flush=True,
    )


def main(phases):
    for phase in phases:
        if phase == "reset":
            drop_ours(phase)
            continue
        if phase == "audit":
            audit()
            continue
        nbdir = f"{ROOT}/{phase}"
        shutil.rmtree(nbdir, ignore_errors=True)
        shutil.copytree(DOCS, nbdir, ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(f"{nbdir}/out", exist_ok=True)
        lines = check_fixes(nbdir) + links_notebook(nbdir) if phase == "docs" else []
        for line in lines + apply_harness(nbdir, phase):
            print(line, flush=True)
        env = dict(os.environ)
        if phase == "docs":
            env["WORKSHOP_USER"] = (
                USER  # collection_id() -> spike-notebooks-sentinel-2-c1-l2a
            )
        for name in PHASES[phase]:
            t0 = time.monotonic()
            r = subprocess.run(
                [
                    "jupyter",
                    "nbconvert",
                    "--to",
                    "notebook",
                    "--execute",
                    "--allow-errors",
                    "--ExecutePreprocessor.timeout=600",
                    "--ExecutePreprocessor.kernel_name=python3",
                    "--output-dir",
                    "out",
                    f"{name}.ipynb",
                ],
                cwd=nbdir,
                env=env,
                capture_output=True,
                text=True,
            )
            dt = time.monotonic() - t0
            status = "PASS" if r.returncode == 0 else "FAIL"
            tail = r.stderr.strip().splitlines()[-1:] if r.returncode else []
            print(
                f"{status} exec.{phase}.{name} — nbconvert rc={r.returncode} in {dt:.0f}s {tail}",
                flush=True,
            )


if __name__ == "__main__":
    main(sys.argv[1:] or ["reset", "docs", "writes", "audit"])
