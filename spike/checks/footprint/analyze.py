"""Turn results/ (samples.csv, phases.tsv, snaps.jsonl, load.jsonl, images.json,
gdal.tsv) into PASS/FAIL lines, tables (results/analysis.txt) and per-container
requests/limits + pods-per-node.  usage: analyze.py <results dir>"""

import csv
import json
import math
import re
import statistics
import sys
from pathlib import Path

R = Path(sys.argv[1])
SERVICES = [
    "lab",
    "database",
    "stac-fastapi",
    "titiler-pgstac",
    "tipg",
    "stac-auth-proxy",
    "mock-oidc",
    "stac-browser",
    "stac-manager",
]
LOADS = ["titiler", "tipg", "stac", "kernel", "all"]
GI = 1024  # MiB per GiB

# ---------------------------------------------------------------- inputs
phases = {}
for row in csv.reader(open(R / "phases.tsv"), delimiter="\t"):
    phases[row[0]] = (float(row[1]), float(row[2]))
samples = []  # (t, svc, cpu_pct, mem_mib); docker stats measures over ~1 s ending ~1.8 s after t
for row in csv.DictReader(open(R / "samples.csv")):
    samples.append(
        (
            float(row["t"]) + 1.0,
            row["service"],
            float(row["cpu_pct"]),
            float(row["mem_mib"]),
        )
    )
snaps = {s["label"]: s for s in map(json.loads, open(R / "snaps.jsonl"))}
loads = [json.loads(line) for line in open(R / "load.jsonl") if line.startswith("{")]
images = json.load(open(R / "images.json"))
gdal = dict(
    row for row in csv.reader(open(R / "gdal.tsv"), delimiter="\t") if len(row) == 2
)

out_lines = []


def emit(status, name, detail):
    print(f"{status} {name} — {detail}")


def table(title, header, rows):
    out_lines.append(f"\n## {title}\n")
    out_lines.append("| " + " | ".join(header) + " |")
    out_lines.append("|" + "---|" * len(header))
    for r in rows:
        out_lines.append("| " + " | ".join(str(x) for x in r) + " |")


def within(name):
    a, b = phases[name]
    return [s for s in samples if a <= s[0] <= b]


def ceil_to(x, step):
    return int(math.ceil(x / step) * step)


def mi(q):  # "560Mi" / "1Gi" -> MiB
    return int(q[:-2]) * (1024 if q.endswith("Gi") else 1)


# ---------------------------------------------------------------- sampler
ts = sorted({s[0] for s in samples})
gaps = [b - a for a, b in zip(ts, ts[1:])]
med_gap = statistics.median(gaps) if gaps else float("nan")
# A gap > 5 s means the sampler (or the Docker VM, e.g. host sleep) stalled: the run is not valid.
emit(
    "PASS" if gaps and med_gap <= 2.5 and max(gaps) <= 5 else "FAIL",
    "sampler.cadence",
    f"{len(ts)} docker-stats rounds x {len(SERVICES)} containers, median interval {med_gap:.2f} s, "
    f"max {max(gaps or [0]):.2f} s (FAIL if median > 2.5 s or any gap > 5 s)",
)
n_idle = len({s[0] for s in within("idle")})
emit(
    "PASS" if n_idle >= 3 else "FAIL",
    "sampler.idle-samples",
    f"{n_idle} rounds in the idle window",
)

# ---------------------------------------------------------------- loads
for ld in loads:
    if ld["load"] == "kernel":
        continue
    ok = ld["ok"] == ld["n"]
    emit(
        "PASS" if ok else "FAIL",
        f"load.{ld['load']}",
        f"{ld['ok']}/{ld['n']} 2xx codes={ld['codes']} wall={ld['wall_s']}s p50={ld['p50_s']}s p95={ld['p95_s']}s "
        f"max={ld['max_s']}s c=4 seed={ld['seed']} lon_shift={ld['lon_shift']}",
    )
kernels = [ld for ld in loads if ld["load"] == "kernel"]
for i, k in enumerate(kernels):
    st = {s["step"]: s for s in k["steps"]}
    good = k["error"] is None and "loaded" in st
    name = "kernel.rioxarray-500MB" + ("" if i == 0 else "-concurrent")
    if good:
        emit(
            "PASS",
            name,
            f"{st['loaded']['nbytes_MiB']} MiB {st['loaded']['dtype']} {st['loaded']['shape']} in {st['loaded']['seconds']} s; "
            f"kernel RSS start={st['start']['VmRSS_MiB']} imported={st['imported']['VmRSS_MiB']} loaded={st['loaded']['VmRSS_MiB']} "
            f"computed={st['computed']['VmRSS_MiB']} freed={st['freed']['VmRSS_MiB']} MiB; PEAK (VmHWM)={k['peak_rss_MiB']} MiB; "
            f"GDAL_CACHEMAX={st['imported']['gdal_cachemax_MiB']} MiB; other kernels at start: {k['other_kernels_at_start']}",
        )
    else:
        emit(
            "FAIL", name, f"error={k['error']} steps={[s['step'] for s in k['steps']]}"
        )

# kernel RSS (MiB): after imports, holding the array, peak (VmHWM)
kimp = max(
    (s["VmRSS_MiB"] for k in kernels for s in k["steps"] if s["step"] == "imported"),
    default=0,
)
kheld = max(
    (s["VmRSS_MiB"] for k in kernels for s in k["steps"] if s["step"] == "held"),
    default=0,
)
kpk = max((k["peak_rss_MiB"] or 0) for k in kernels) if kernels else 0

# Same job under a 3 GiB cgroup limit, outside the stack (GDAL cache then 5 % of the limit)
k3 = (
    {s["step"]: s for s in map(json.loads, open(R / "kernel-3g.jsonl")) if "step" in s}
    if (R / "kernel-3g.jsonl").exists()
    else {}
)
if "freed" in k3:
    emit(
        "PASS",
        "kernel.rioxarray-500MB-under-3GiB-limit",
        f"same job, --memory 3g: GDAL_CACHEMAX={k3['imported']['gdal_cachemax_MiB']} MiB; RSS imported={k3['imported']['VmRSS_MiB']} "
        f"loaded={k3['loaded']['VmRSS_MiB']} held={k3['held']['VmRSS_MiB']} freed={k3['freed']['VmRSS_MiB']} MiB; "
        f"PEAK (VmHWM)={k3['freed']['VmHWM_MiB']} MiB; not OOM-killed",
    )
else:
    emit(
        "FAIL",
        "kernel.rioxarray-500MB-under-3GiB-limit",
        f"steps seen: {list(k3)} (OOM-killed or error, see results/load.err)",
    )

# ---------------------------------------------------------------- per container
LOAD_WINDOW = [p for p in phases if p in LOADS or p.startswith("settle-")]
stats = {}
for svc in SERVICES:
    idle = [s for s in within("idle") if s[1] == svc]
    load = [s for p in LOAD_WINDOW for s in within(p) if s[1] == svc]
    post = [s for s in within("post") if s[1] == svc]
    d = {
        "idle_mem": statistics.mean(s[3] for s in idle),
        "idle_cpu": statistics.mean(s[2] for s in idle),
        "load_med_mem": statistics.median(s[3] for s in load),
        "peak_mem": max(s[3] for s in load + idle + post),
        "post_mem": statistics.mean(s[3] for s in post),
        "peak_cpu": max(s[2] for s in load),
        "cg_peak": snaps["post-all"]["cgroup"][svc].get("peak", 0) / 2**20,
        "per_phase": {},
    }
    for p in LOADS:
        a, b = snaps[f"pre-{p}"], snaps[f"post-{p}"]
        cpu_s = (b["cgroup"][svc]["usage_usec"] - a["cgroup"][svc]["usage_usec"]) / 1e6
        ps = [s for s in within(p) if s[1] == svc]
        d["per_phase"][p] = {
            "cores": cpu_s / (b["t"] - a["t"]),
            "cpu_s": cpu_s,
            "max_mem": max(s[3] for s in ps) if ps else float("nan"),
            "max_cpu": max(s[2] for s in ps) if ps else float("nan"),
        }
    a, b = snaps["pre-titiler"], snaps["post-all"]
    d["avg_cores_load"] = (
        (b["cgroup"][svc]["usage_usec"] - a["cgroup"][svc]["usage_usec"])
        / 1e6
        / (b["t"] - a["t"])
    )
    d["busiest_cores"] = max(v["cores"] for v in d["per_phase"].values())
    if svc == "lab" and kernels:
        # A 2 s sampler misses the kernel's ~0.5 s temporary; add it back from VmHWM.
        d["peak_mem"] = max(d["peak_mem"], d["peak_mem"] - kheld + kpk)
    stats[svc] = d
    emit(
        "PASS",
        f"mem.{svc}",
        f"idle {d['idle_mem']:.0f} MiB, load median {d['load_med_mem']:.0f}, peak {d['peak_mem']:.0f}, after load {d['post_mem']:.0f} "
        f"(cgroup memory.peak incl. page cache {d['cg_peak']:.0f}); "
        f"CPU idle {d['idle_cpu']:.1f}%, avg under load {d['avg_cores_load'] * 1000:.0f}m, busiest phase {d['busiest_cores'] * 1000:.0f}m, "
        f"peak 1-s sample {d['peak_cpu']:.0f}%",
    )

table(
    "Memory per container (MiB, docker stats working set, 2 s samples; Lab peak adds back the kernel's VmHWM spike)",
    [
        "container",
        "idle (mean)",
        "under load (median)",
        "peak",
        "after load (mean)",
        "cgroup memory.peak*",
    ],
    [
        [
            s,
            f"{d['idle_mem']:.0f}",
            f"{d['load_med_mem']:.0f}",
            f"{d['peak_mem']:.0f}",
            f"{d['post_mem']:.0f}",
            f"{d['cg_peak']:.0f}",
        ]
        for s, d in stats.items()
    ]
    + [
        [
            "**pod total**",
            f"{sum(d['idle_mem'] for d in stats.values()):.0f}",
            f"{sum(d['load_med_mem'] for d in stats.values()):.0f}",
            f"{sum(d['peak_mem'] for d in stats.values()):.0f} (sum of peaks)",
            f"{sum(d['post_mem'] for d in stats.values()):.0f}",
            "",
        ]
    ],
)
out_lines.append(
    "\n*cgroup `memory.peak` is since container start and includes page cache; an upper bound, not a working set."
)

# The pod's busiest moment (all containers in the same 2 s round), plus the
# kernel's sub-sample spike; and the same with the kernel peak measured under a
# 3 GiB limit (what the Lab sees on k8s, where GDAL's cache is 5 % of the limit).
rounds = {}
for t, _, _, mem in samples:
    rounds[t] = rounds.get(t, 0) + mem
pod_now = max(rounds.values()) + max(0, kpk - kheld)
pod_k8s = pod_now - (kpk - k3["freed"]["VmHWM_MiB"] if "freed" in k3 else 0)
out_lines.append(
    f"\nPod total at its busiest moment: {pod_now:.0f} MiB as measured (kernel GDAL cache uncapped), "
    f"{pod_k8s:.0f} MiB with the kernel peak from the 3 GiB-limited run."
)

table(
    "CPU per container (millicores; average over each phase from cgroup cpu.stat, peak = highest ~1 s docker-stats sample)",
    ["container", "idle", *LOADS, "avg whole load window", "peak 1-s"],
    [
        [
            s,
            f"{d['idle_cpu'] * 10:.0f}",
            *[f"{d['per_phase'][p]['cores'] * 1000:.0f}" for p in LOADS],
            f"{d['avg_cores_load'] * 1000:.0f}",
            f"{d['peak_cpu'] * 10:.0f}",
        ]
        for s, d in stats.items()
    ]
    + [
        [
            "**pod total**",
            f"{sum(d['idle_cpu'] for d in stats.values()) * 10:.0f}",
            *[
                f"{sum(d['per_phase'][p]['cores'] for d in stats.values()) * 1000:.0f}"
                for p in LOADS
            ],
            f"{sum(d['avg_cores_load'] for d in stats.values()) * 1000:.0f}",
            "",
        ]
    ],
)

wall = {p: snaps[f"post-{p}"]["t"] - snaps[f"pre-{p}"]["t"] for p in LOADS}
table(
    "CPU-seconds consumed per phase (cgroup cpu.stat; robust for bursts shorter than a 2 s sample)",
    ["container", *[f"{p} ({wall[p]:.0f} s)" for p in LOADS]],
    [
        [s, *[f"{d['per_phase'][p]['cpu_s']:.1f}" for p in LOADS]]
        for s, d in stats.items()
    ]
    + [
        [
            "**pod total**",
            *[
                f"{sum(d['per_phase'][p]['cpu_s'] for d in stats.values()):.1f}"
                for p in LOADS
            ],
        ]
    ],
)

table(
    "Peak memory per phase (MiB, docker stats; '-' = phase shorter than one 2 s sample)",
    ["container", *LOADS],
    [
        [
            s,
            *[
                f"{d['per_phase'][p]['max_mem']:.0f}"
                if d["per_phase"][p]["max_mem"] == d["per_phase"][p]["max_mem"]
                else "-"
                for p in LOADS
            ],
        ]
        for s, d in stats.items()
    ],
)

# Lab processes at each snapshot (server vs kernels, ours and other testers')
rows = []
for label, s in snaps.items():
    procs = s["lab_procs"]
    if isinstance(procs, list):
        srv = sum(p["rss_mib"] for p in procs if p["kind"] == "server")
        ks = [
            f"{p['kernel']}={p['rss_mib']:.0f}" for p in procs if p["kind"] == "kernel"
        ]
        rows.append([label, f"{srv:.0f}", ", ".join(ks) or "-"])
table(
    "Lab container processes at each snapshot (RSS MiB; our kernel lives between snapshots, see kernel.* lines)",
    [
        "snapshot",
        "jupyter processes (server + any jupyter CLI)",
        "kernels (id=RSS; external = not started by the Lab)",
    ],
    rows,
)

# ---------------------------------------------------------------- recommendations
# Memory request: what the container keeps after a burst of use (Python and
# Postgres do not hand memory back), +25 %. Memory limit: 2x the observed peak
# (one participant, heavier than our synthetic burst), floor 128 Mi.
# CPU request: average over the whole load window (a busy participant), floor 10m.
# No CPU limits (requests already set the CFS share under contention; limits
# only throttle bursty tile rendering).
rec = {}
for svc, d in stats.items():
    base = max(d["post_mem"], d["load_med_mem"], d["idle_mem"])
    req = max(32, ceil_to(base * 1.25, 16))
    lim = max(128, ceil_to(d["peak_mem"] * 2, 64))
    cpu = max(10, ceil_to(d["avg_cores_load"] * 1000, 10))
    rec[svc] = {"mem_req": req, "mem_lim": lim, "cpu_req": cpu}

# The Lab is special: its limit must hold a kernel doing real work, and its
# request is a policy choice. Two request profiles, both from measured numbers:
#  - notebooks: Lab at idle + 2 kernels with the scientific stack imported
#    (notebooks 02-08 call APIs; they do not hold big arrays), +25 %
#  - raster: Lab at idle + one kernel HOLDING the ~500 MB array, +10 %; the
#    kernel figure comes from the 3 GiB-limited run (what k8s sees) if present
# Limit: 1.5x the Lab's peak measured WITHOUT a limit (GDAL cache 1.2 GiB, so
# conservative), so the 500 MB exercise fits with headroom; above it the OOM
# killer takes the Lab container only (whole container on cgroup v2), and the
# pod's DB and services survive.
idle_lab = stats["lab"]["idle_mem"]
held_k8s = k3["held"]["VmRSS_MiB"] if "held" in k3 else kheld
lab_req = {
    "notebooks": ceil_to((idle_lab + 2 * kimp) * 1.25, 256),
    "raster": ceil_to((idle_lab + held_k8s) * 1.1, 256),
}
rec["lab"]["mem_req"] = lab_req["notebooks"]
# Limit: 1.5x the Lab's peak as it would be under a k8s limit. GDAL sizes its
# default block cache from the cgroup limit (gdal.cachemax-cgroup-aware), so the
# kernel's peak is the one measured under --memory 3g, not the uncapped local one.
k3_peak = k3["freed"]["VmHWM_MiB"] if "freed" in k3 else kpk
lab_peak_k8s = stats["lab"]["peak_mem"] - (kpk - k3_peak)
rec["lab"]["mem_lim"] = ceil_to(lab_peak_k8s * 1.5, 512)
out_lines.append(
    f"\nLab peak: {stats['lab']['peak_mem']:.0f} MiB as measured (kernel GDAL cache uncapped), "
    f"{lab_peak_k8s:.0f} MiB with the kernel peak from the 3 GiB-limited run (limit rule uses this)."
)

table(
    "Recommended requests/limits per container (derived by the rules in analyze.py)",
    ["container", "cpu request", "cpu limit", "memory request", "memory limit"],
    [
        [s, f"{r['cpu_req']}m", "none", f"{r['mem_req']}Mi", f"{r['mem_lim']}Mi"]
        for s, r in rec.items()
    ]
    + [
        [
            "**pod**",
            f"{sum(r['cpu_req'] for r in rec.values())}m",
            "",
            f"{sum(r['mem_req'] for r in rec.values())}Mi",
            f"{sum(r['mem_lim'] for r in rec.values())}Mi",
        ]
    ],
)

out_lines.append(
    f"\nLab memory request profiles: notebooks = {lab_req['notebooks']}Mi (used above); "
    f"500 MB raster held in the kernel = {lab_req['raster']}Mi (kernel held RSS {held_k8s} MiB)."
)

# ---------------------------------------------------------------- packing
# spike/chart/values.yaml writes each container's resources on one flow-style line.
chart, cur = {}, None
for line in open(
    Path(__file__).resolve().parent.parent.parent / "chart" / "values.yaml"
):
    m = re.match(r"  - name: (\S+)", line)
    cur = m.group(1) if m else cur
    m = re.search(
        r"requests: \{cpu: (\w+), memory: (\w+)\}, limits: \{memory: (\w+)\}", line
    )
    if m and cur:
        chart[cur] = {
            "cpu_req": m.group(1),
            "mem_req": mi(m.group(2)),
            "mem_lim": mi(m.group(3)),
        }
# The chart's current values as a third request profile (cpu "60m" -> 60).
chart_rec = {
    k: {**v, "cpu_req": int(v["cpu_req"].rstrip("m"))} for k, v in chart.items()
}

# b3-8 allocatable measured on "labs"; b3-16/b3-32 EXTRAPOLATED two ways:
#  - proportional: same allocatable/nominal ratio as b3-8 (conservative)
#  - fixed reserve: same absolute reserve as b3-8 (optimistic)
NOMINAL = {
    "b3-8": (2, 8e9 / 2**30),
    "b3-16": (4, 16e9 / 2**30),
    "b3-32": (8, 32e9 / 2**30),
}
A8 = (1.84, 5.77)
res_cpu, res_mem = NOMINAL["b3-8"][0] - A8[0], NOMINAL["b3-8"][1] - A8[1]
ALLOC = {"b3-8 (measured)": A8}
for n in ("b3-16", "b3-32"):
    c, m = NOMINAL[n]
    ALLOC[f"{n} (extrap., proportional)"] = (
        c * A8[0] / 2,
        m * A8[1] / NOMINAL["b3-8"][1],
    )
    ALLOC[f"{n} (extrap., fixed reserve)"] = (c - res_cpu, m - res_mem)
DS = (
    0.25,
    0.25,
)  # ASSUMED per-node DaemonSet requests (calico-node, csi node plugin, ...): verify on a pool node

variants = {
    "Lab: notebooks": rec,
    "Lab: 500 MB raster held": {
        **rec,
        "lab": {**rec["lab"], "mem_req": lab_req["raster"]},
    },
    "chart values.yaml as committed": chart_rec,
}
rows, fits = [], {}
for vname, rr in variants.items():
    pc = sum(r["cpu_req"] for r in rr.values()) / 1000
    pm = sum(r["mem_req"] for r in rr.values()) / GI
    for node, (ac, am) in ALLOC.items():
        n0 = int(min(ac / pc, am / pm))
        n1 = int(min((ac - DS[0]) / pc, (am - DS[1]) / pm))
        bind = "CPU" if ac / pc < am / pm else "memory"
        fits[(vname, node)] = n1
        need = {
            u: math.ceil(u / max(n1, 1e-9)) + 1 if n1 else "n/a" for u in (10, 20, 40)
        }
        lim = n1 * sum(r["mem_lim"] for r in rr.values()) / GI / am
        rows.append(
            [
                vname,
                node,
                f"{ac:.2f} / {am:.2f}",
                f"{pc:.2f} / {pm:.2f}",
                n0,
                n1,
                bind,
                f"{lim:.1f}x",
                f"{need[10]} / {need[20]} / {need[40]}",
            ]
        )
table(
    "Participant pods per node (requests-based)",
    [
        "Lab request profile",
        "node",
        "allocatable CPU / GiB",
        "pod requests CPU / GiB",
        "pods (no DaemonSets)",
        f"pods (minus assumed DS {DS[0]} CPU / {DS[1]} GiB)",
        "binding",
        "memory limits / allocatable at that density",
        "nodes for 10 / 20 / 40 users (+1 spare)",
    ],
    rows,
)

# ---------------------------------------------------------------- plan claims
backend_idle = sum(d["idle_mem"] for s, d in stats.items() if s != "lab")
emit(
    "PASS" if backend_idle < 1.5 * GI else "FAIL",
    "plan.backend-idle-under-1.5GiB",
    f"backend (all but Lab) idle = {backend_idle:.0f} MiB with one uvicorn worker each (skeptic review claim)",
)
pod_peak = sum(d["peak_mem"] for d in stats.values())
# Two lines on purpose: the k8s estimate (kernel peak under a 3 GiB limit) and
# the figure as measured here (no limit, GDAL cache uncapped). Neither hides the other.
emit(
    "PASS" if pod_now <= 3.5 * GI else "FAIL",
    "plan.participant-under-3.5GiB-local-no-limit",
    f"pod total at its busiest moment as measured = {pod_now / GI:.2f} GiB (no memory limit, kernel GDAL cache "
    f"{kpk} MiB peak); this is what a laptop compose stack uses",
)
emit(
    "PASS" if pod_k8s <= 3.5 * GI else "FAIL",
    "plan.participant-under-3.5GiB-k8s-estimate",
    f"pod total at its busiest moment = {pod_k8s / GI:.2f} GiB with the k8s-limited kernel peak "
    f"(ESTIMATE: the stack itself ran without limits; sum of per-container peaks, never simultaneous, "
    f"= {pod_peak / GI:.2f} GiB). Load = synthetic tiles + 500 MB raster kernel, heavier than notebooks "
    f"(plan: 2.5-3.5 GiB per participant under notebook load)",
)
# Packing claims pass only if BOTH this run's rule and the committed chart values pass.
B8, B16 = "b3-8 (measured)", "b3-16 (extrap., proportional)"
packing = []
for vname, rr in (("this run's rule", rec), ("chart values", chart_rec)):
    g = sum(r["mem_req"] for r in rr.values()) / GI
    packing.append((vname, g, A8[1] - DS[1] - 2 * g))
n8 = min(fits[("Lab: notebooks", B8)], fits[("chart values.yaml as committed", B8)])
emit(
    "PASS" if n8 >= 2 else "FAIL",
    "plan.b3-8-holds-2-pods",
    f"per b3-8 after ASSUMED DaemonSet requests {DS[1]} GiB: this run's rule {fits[('Lab: notebooks', B8)]} pods, "
    f"chart values {fits[('chart values.yaml as committed', B8)]}; "
    + "; ".join(
        f"{v}: pod {g:.2f} GiB, {left:.2f} GiB left with 2 pods (2 fit only if real DaemonSets "
        f"request < {DS[1] + left:.2f} GiB)"
        for v, g, left in packing
    )
    + f"; {fits[('Lab: 500 MB raster held', B8)]} if every Lab holds the raster (skeptic: ~2)",
)
n16 = min(fits[("Lab: notebooks", B16)], fits[("chart values.yaml as committed", B16)])
need20 = math.ceil(20 / n16) + 1 if n16 else None
emit(
    "PASS" if need20 and need20 <= 6 else "FAIL",
    "plan.20-users-on-4-5-b3-16",
    f"per b3-16 (EXTRAPOLATED, proportional): this run's rule {fits[('Lab: notebooks', B16)]} pods, chart values "
    f"{fits[('chart values.yaml as committed', B16)]} -> {need20} b3-16 for 20 users incl. 1 spare at the lower "
    f"density (skeptic: 4-5 + 1 spare)",
)

# ---------------------------------------------------------------- chart vs measured
steady = {
    s: max(d["idle_mem"], d["load_med_mem"], d["post_mem"]) for s, d in stats.items()
}
peak = {s: (lab_peak_k8s if s == "lab" else d["peak_mem"]) for s, d in stats.items()}
low_req = [
    f"{s} {chart[s]['mem_req']}<{steady[s]:.0f}"
    for s in SERVICES
    if s in chart and chart[s]["mem_req"] < steady[s]
]
low_lim = [
    f"{s} {chart[s]['mem_lim']}<{peak[s]:.0f}"
    for s in SERVICES
    if s in chart and chart[s]["mem_lim"] < peak[s]
]
diff = [
    f"{s} req {chart[s]['mem_req']}->{rec[s]['mem_req']} lim {chart[s]['mem_lim']}->{rec[s]['mem_lim']} "
    f"cpu {chart[s]['cpu_req']}->{rec[s]['cpu_req']}m"
    for s in SERVICES
    if s in chart
    and (chart[s]["mem_req"], chart[s]["mem_lim"], chart[s]["cpu_req"])
    != (rec[s]["mem_req"], rec[s]["mem_lim"], f"{rec[s]['cpu_req']}m")
]
missing = [s for s in SERVICES if s not in chart]
emit(
    "PASS" if not low_req and not missing else "FAIL",
    "chart.requests-cover-steady",
    f"chart memory request >= steady working set (max of idle, load median, after load) for every container; "
    f"below: {low_req or 'none'}; not parsed: {missing or 'none'}",
)
emit(
    "PASS" if not low_lim and not missing else "FAIL",
    "chart.limits-cover-peaks",
    f"chart memory limit >= measured peak (Lab: k8s-adjusted {lab_peak_k8s:.0f} MiB) for every container; "
    f"below: {low_lim or 'none'}",
)
out_lines.append(
    "\nChart (spike/chart/values.yaml) vs this run's rule (MiB / millicores): "
    + ("; ".join(diff) if diff else "identical")
)

# ---------------------------------------------------------------- images
lab_b = images["amd64_compressed_bytes"]["lab (published base: workshop image)"]
emit(
    "PASS" if lab_b and abs(lab_b / 2**30 - 1.8) < 0.2 else "FAIL",
    "images.lab-pull-1.8GiB",
    f"ghcr.io/developmentseed/eoapi-workshop:latest linux/amd64 compressed = {lab_b / 2**30:.2f} GiB",
)
tot = images["amd64_unique_compressed_bytes_all"]
emit(
    "PASS",
    "images.per-node-prepull",
    f"all 9 images, linux/amd64, unique compressed layers = {tot / 2**30:.2f} GiB per node "
    f"(stac-manager alone {images['amd64_compressed_bytes']['stac-manager'] / 2**30:.2f} GiB)",
)
table(
    "Images (local `docker image ls` = arm64 unpacked unless noted; pull = linux/amd64 compressed from the registry)",
    ["image", "pull (amd64, compressed)"],
    [
        [f"{k}: `{images['refs'][k]}`", f"{v / 2**20:.0f} MiB" if v else "n/a"]
        for k, v in images["amd64_compressed_bytes"].items()
    ]
    + [["**unique total (shared layers counted once)**", f"{tot / 2**20:.0f} MiB"]],
)
table(
    "Local `docker image ls` sizes",
    ["image", "size"],
    list(images["local_docker_image_ls"].items()),
)

# ---------------------------------------------------------------- disk
disk = [
    row for row in csv.reader(open(R / "disk.tsv"), delimiter="\t") if len(row) == 2
]
emit(
    "PASS" if disk else "FAIL",
    "disk.ephemeral",
    "; ".join(
        f"{k.removeprefix('eoapi-spike-').removesuffix('-1')}={v}" for k, v in disk
    ),
)

# ---------------------------------------------------------------- GDAL cache
no, lim = gdal.get("nolimit"), gdal.get("limit4g")
if no and lim and no.isdigit() and lim.isdigit():
    emit(
        "PASS" if int(lim) < int(no) else "FAIL",
        "gdal.cachemax-cgroup-aware",
        f"default GDAL_CACHEMAX in the Lab image: {no} MiB without a memory limit, {lim} MiB under --memory 4g",
    )
else:
    emit("FAIL", "gdal.cachemax-cgroup-aware", f"probe output: {gdal}")

(R / "analysis.txt").write_text("\n".join(out_lines) + "\n")
