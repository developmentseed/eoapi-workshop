"""Host-side probes for the footprint check (stdlib only; calls the docker CLI).

    probe.py sample <samples.csv> <stopfile>   docker stats every 2 s until <stopfile> exists
    probe.py snap <label> <snaps.jsonl>        cgroup counters of every container + Lab processes
    probe.py images <images.json>              local `docker image ls` sizes + linux/amd64 pull sizes

`docker stats` memory on cgroup v2 = memory.current - inactive_file, the same
"working set" that `kubectl top` and the kubelet's eviction logic use.
"""

import csv
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

SERVICES = ["lab", "database", "stac-fastapi", "titiler-pgstac", "tipg", "stac-auth-proxy",
            "mock-oidc", "stac-browser", "stac-manager"]
NAMES = [f"eoapi-spike-{s}-1" for s in SERVICES]
UNITS = {"B": 1, "KiB": 2**10, "MiB": 2**20, "GiB": 2**30, "kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9}


def mib(text):
    num, unit = re.fullmatch(r"([\d.]+)\s*([A-Za-z]+)", text.strip()).groups()
    return float(num) * UNITS[unit] / 2**20


def sample(path, stop):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["t", "service", "cpu_pct", "mem_mib", "pids"])
        nxt = time.time()
        while not os.path.exists(stop):
            t0 = time.time()
            p = subprocess.run(["docker", "stats", "--no-stream", "--format", "json", *NAMES],
                               capture_output=True, text=True)
            for line in p.stdout.splitlines():
                d = json.loads(line)
                svc = d["Name"].removeprefix("eoapi-spike-").removesuffix("-1")
                w.writerow([f"{t0:.3f}", svc, d["CPUPerc"].rstrip("%"),
                            f"{mib(d['MemUsage'].split('/')[0]):.1f}", d["PIDs"]])
            f.flush()
            nxt += 2
            time.sleep(max(0.0, nxt - time.time()))
            nxt = max(nxt, time.time())


CG = ("cat /sys/fs/cgroup/cpu.stat; echo peak $(cat /sys/fs/cgroup/memory.peak); "
      "echo current $(cat /sys/fs/cgroup/memory.current); "
      "grep -E '^(anon|file|inactive_file) ' /sys/fs/cgroup/memory.stat")

# Lab processes: separates the Jupyter server from kernels (ours and other
# testers'). Plain sh + /proc, so the probe itself costs ~no CPU in the Lab.
PS = ("for p in /proc/[0-9]*; do c=$(tr '\\0' ' ' < $p/cmdline 2>/dev/null); case \"$c\" in "
      "*ipykernel*|*jupyter*) echo \"$(awk '/^VmRSS/{print $2}' $p/status) $c\";; esac; done")


def cgroup(name):
    p = subprocess.run(["docker", "exec", name, "sh", "-c", CG], capture_output=True, text=True)
    d = {}
    for line in p.stdout.splitlines():
        k, _, v = line.partition(" ")
        if v.strip().isdigit():
            d[k] = int(v)
    return d


def snap(label, path):
    t0 = time.time()
    with ThreadPoolExecutor(len(NAMES)) as ex:
        cg = dict(zip(SERVICES, ex.map(cgroup, NAMES)))
    p = subprocess.run(["docker", "exec", "eoapi-spike-lab-1", "sh", "-c", PS], capture_output=True, text=True)
    procs = []
    for line in p.stdout.splitlines():
        rss, _, cmd = line.partition(" ")
        if not rss.isdigit() or cmd.startswith("sh -c"):  # skip this probe's own shell
            continue
        kernel = "ipykernel" in cmd
        # Lab-started kernels carry kernel-<id>.json; anything else (nbclient, ...) is "external".
        kid = cmd.split("kernel-")[-1].split(".json")[0][:8] if "kernel-" in cmd else "external"
        procs.append({"kind": "kernel" if kernel else "server",
                      "kernel": kid if kernel else "",
                      "rss_mib": round(int(rss) / 1024, 1)})
    with open(path, "a") as f:
        f.write(json.dumps({"label": label, "t": t0, "cgroup": cg, "lab_procs": procs}) + "\n")


def manifest(ref):
    p = subprocess.run(["docker", "buildx", "imagetools", "inspect", "--raw", ref],
                       capture_output=True, text=True)
    return json.loads(p.stdout) if p.returncode == 0 else None


def amd64_layers(ref):
    """Compressed linux/amd64 layers [(digest, size)] from the registry, or None."""
    m = manifest(ref)
    if m and "manifests" in m:  # index: pick linux/amd64
        d = next((x["digest"] for x in m["manifests"]
                  if x.get("platform", {}).get("os") == "linux"
                  and x.get("platform", {}).get("architecture") == "amd64"), None)
        if d is None:
            return None
        repo = ref.split("@")[0] if "@" in ref else ref.rsplit(":", 1)[0]
        m = manifest(f"{repo}@{d}")
    if not m or "layers" not in m:
        return None
    return [(x["digest"], x["size"]) for x in m["layers"]]


# What a participant node pulls. The Lab and DB are built locally in the spike;
# their published/base counterparts are what a node would pull today.
REFS = {
    "lab (published base: workshop image)": "ghcr.io/developmentseed/eoapi-workshop:latest",
    "database (base: pgstac)": "ghcr.io/stac-utils/pgstac:v0.9.11",
    "stac-fastapi": "ghcr.io/stac-utils/stac-fastapi-pgstac:7.0.0",
    "titiler-pgstac": "ghcr.io/stac-utils/titiler-pgstac:3.2.0",
    "tipg": "ghcr.io/developmentseed/tipg:1.6.1",
    "stac-auth-proxy": "ghcr.io/developmentseed/stac-auth-proxy:v1.2.0",
    "mock-oidc": "ghcr.io/alukach/mock-oidc-server@sha256:5972adac0b6e3a094ea043be0f1851c65e3fd54e17a546f0b71dedd17c7a2d6a",
    "stac-browser": "ghcr.io/radiantearth/stac-browser:5.1.0",
    "stac-manager": "ghcr.io/developmentseed/stac-manager:1.0.3",
}
# As the stack runs locally (mock-oidc is pinned by digest; locally it is tagged latest).
LOCAL = {"eoapi-spike-lab:latest", "eoapi-spike-db:latest", "ghcr.io/stac-utils/stac-fastapi-pgstac:7.0.0",
         "ghcr.io/stac-utils/titiler-pgstac:3.2.0", "ghcr.io/developmentseed/tipg:1.6.1",
         "ghcr.io/developmentseed/stac-auth-proxy:v1.2.0", "ghcr.io/alukach/mock-oidc-server:latest",
         "ghcr.io/radiantearth/stac-browser:5.1.0", "ghcr.io/developmentseed/stac-manager:1.0.3"}


def images(path):
    p = subprocess.run(["docker", "image", "ls", "--format", "json"], capture_output=True, text=True)
    local = {}
    for line in p.stdout.splitlines():
        d = json.loads(line)
        if f"{d['Repository']}:{d['Tag']}" in LOCAL:
            local[f"{d['Repository']}:{d['Tag']}"] = d["Size"]
    for name in ("eoapi-spike-lab", "eoapi-spike-db"):
        arch = subprocess.run(["docker", "image", "inspect", name, "-f", "{{.Architecture}}"],
                              capture_output=True, text=True).stdout.strip()
        local[f"{name}:latest (arch)"] = arch
    with ThreadPoolExecutor(len(REFS)) as ex:
        layers = dict(zip(REFS, ex.map(amd64_layers, REFS.values())))
    seen, unique = set(), 0
    for ls in layers.values():
        for dg, sz in ls or []:
            if dg not in seen:
                seen.add(dg)
                unique += sz
    out = {
        "local_docker_image_ls": local,
        "amd64_compressed_bytes": {k: (sum(s for _, s in v) if v else None) for k, v in layers.items()},
        "amd64_unique_compressed_bytes_all": unique,
        "refs": REFS,
    }
    with open(path, "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    {"sample": sample, "snap": snap, "images": images}[cmd](*args)
