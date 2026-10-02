"""The chart runs the same stack as compose.participant.yml: per container,
same image, same command line, same env names, same non-secret env values.

values.yaml repeats compose by hand, so this is
what keeps the two from drifting. Reads `helm template` on stdin, renders
participant u01 back to compose's origin, and never prints a value that comes
from a secret. Prints: PASS|FAIL <name> — <detail>
"""

import pathlib
import shlex
import sys

import yaml

SPIKE = pathlib.Path(__file__).resolve().parents[2]
CHART_ORIGIN, COMPOSE_ORIGIN = (
    "http://lab-u01.spike.local:18080",
    "http://localhost:18888",
)

BUILT = {"eoapi-spike-lab": "eoapi-workshop-lab", "eoapi-spike-db": "eoapi-workshop-db"}
compose = yaml.safe_load((SPIKE / "compose.participant.yml").read_text())["services"]
pod = next(
    d
    for d in yaml.safe_load_all(sys.stdin)
    if d and d["kind"] == "Deployment" and d["metadata"]["name"].endswith("-u01")
)["spec"]["template"]["spec"]
chart = {c["name"]: c for c in pod["initContainers"] + pod["containers"]}


def argv(cmd):
    if cmd is None:
        return None
    return (
        shlex.split(cmd) if isinstance(cmd, str) else [" ".join(a.split()) for a in cmd]
    )


for name in sorted(set(compose) | set(chart)):
    s, c = compose.get(name), chart.get(name)
    if not (s and c):
        print(f"FAIL parity.{name} — only in {'compose' if s else 'chart'}")
        continue
    diffs = []
    img = s["image"]
    if img in BUILT:  # compose builds it locally; the chart pulls the same build
        same = c["image"].rsplit(":", 1)[0].endswith("/" + BUILT[img])
    else:
        same = img == c["image"]
    if not same:
        diffs.append(f"image {img} vs {c['image']}")
    ca = c.get("args") and [" ".join(a.split()) for a in c["args"]]
    if argv(s.get("command")) != ca:
        diffs.append("command differs")
    senv = s.get("environment") or {}
    cenv = {
        e["name"]: e.get("value") for e in c.get("env", [])
    }  # None = from the Secret
    if set(senv) != set(cenv):
        diffs.append(
            f"env names: compose-only {sorted(set(senv) - set(cenv))}, chart-only {sorted(set(cenv) - set(senv))}"
        )
    for k in sorted(set(senv) & set(cenv)):
        sv, cv = str(senv[k]), cenv[k]
        if (sv.startswith("${") or cv is None) and not (
            sv.startswith("${") and cv is None
        ):
            diffs.append(f"{k}: secret in one, literal in the other")
        elif cv is not None and cv.replace(CHART_ORIGIN, COMPOSE_ORIGIN) != sv:
            diffs.append(f"{k} differs")
    n = len(senv)
    print(
        f"{'FAIL' if diffs else 'PASS'} parity.{name} — "
        + (
            "; ".join(diffs)
            if diffs
            else f"image, command and {n} env vars match compose (origin swapped)"
        )
    )
