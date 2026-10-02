# Footprint: memory and CPU of one participant's stack

> **Superseded.** This is the pre-fix run of 2026-10-01. The current stack is described by `fix.md` (the fixes and a re-run of every topic) and `verify.md` (the independent re-run). The method and the reproduce steps below still apply.
>
> Only each run's `results/<label>/analysis.txt` is kept in the tree. The raw samples this page cites (`run.out`, `samples.csv`, ...) are in commit e3c0479; `run.sh` regenerates them.

*2026-10-01, verified rerun · Docker Desktop on an arm64 Mac (VM: 6 vCPU, 23.4 GiB, cgroup v2, kernel 6.12.54-linuxkit) · branch `spike/per-user-stacks` · reproducible with `spike/checks/footprint/run.sh <label>` · committed data: `results/cold/` (seed 1790874859, ~17:14Z), `results/warm/` (seed 1790875096, ~17:18Z) and `results/warm2/` (seed 1790880490, ~18:48Z), all on the stack restarted at 17:09Z.*

This file replaces the WIP version from commit 95823c1, which a usage limit interrupted. Every number below comes from runs made in this session, except WIP figures quoted as such. Where the WIP differed, see [What changed from the WIP](#what-changed-from-the-wip-attempt).

## Result

- **Memory sets the packing, not CPU.** The chart's committed requests are **2.72 GiB and 0.37 CPU per participant pod** (`spike/chart/values.yaml`).
  - They cover every steady state and peak in all three fresh runs (`chart.requests-cover-steady` and `chart.limits-cover-peaks`: PASS in each).
  - Applied to each run, the rule in `analyze.py` gives **1.95 → 2.16 → 2.27 GiB per pod** (cold → warm → warm2). It still rises, though more slowly, and titiler is still growing.
  - **Keep the chart's memory values, and raise titiler to 464Mi / 768Mi**, the warm2 rule. That makes 2.75 GiB per pod. Don't trim toward the rule until a multi-hour soak shows a plateau.
- **Pods per node** with the chart values plus the titiler raise; with the chart as committed the counts are the same (requests-based; DaemonSet requests ASSUMED at 0.25 CPU / 0.25 GiB):

  | node | allocatable | pods | nodes for 10 / 20 / 40 users (+1 spare) |
  |---|---|---|---|
  | b3-8 | 1.84 CPU / 5.77 GiB (**measured**) | **2 only on paper**: 0.02 GiB left (0.08 as committed). **1 pod** if real DaemonSets request > 0.27 GiB. Plan on 1. | 6 / 11 / 21 at 2 per node (11 / 21 / 41 at 1) |
  | b3-16 | **EXTRAPOLATED**: 3.68 / 11.54 (proportional) to 3.84 / 13.22 (fixed reserve) | **4** | 4 / **6** / 11 |
  | b3-32 | **EXTRAPOLATED**: 7.36 / 23.08 to 7.84 / 28.12 | **8–10** | 2–3 / 3–4 / 5–6 |

  - Against Loïc's "10–20 participants, 2–3 nodes added":
    - 3 added b3-16 hold 12 pods (extrapolated): 10 users fit with 2 pods of slack, but no spare node;
    - 20 users need 6 b3-16 or 3–4 b3-32, unless the existing b3-8 nodes take some pods (not measured here).
- **One stack's memory** (working set, `docker stats`):
  - **0.64 GiB fresh**: 651 MiB, 3 min after start, before any use.
  - **1.0–1.4 GiB warm idle or steady after a load run.** It rose run by run: 1.05, then 1.23, then 1.37 GiB after load.
  - **2.72–3.00 GiB at its busiest moment on k8s (ESTIMATE).** This is with map tiles, STAC searches and a 478 MiB raster held in a kernel. As measured here without limits it was 3.05–3.33 GiB, which is what a laptop compose stack uses. Both are under the plan's 3.5 GiB.
- **Only the Lab spikes.**
  - The raster kernel peaks at **1277 MiB under a 3 GiB limit** and 1619 MiB without one. GDAL's default block cache is 5 % of the memory it sees.
  - So the Lab's 3Gi limit holds **one** such kernel, but not two peaking together (2045 + 1277 MiB > 3072 MiB).
- **Backends grow with use** (fresh → after the third run): titiler 145 → 370 MiB (still rising), tipg 63 → 132 (flat since run 2), stac-fastapi 62 → 95, Postgres 41 → 302, stac-auth-proxy 151 → 169.
- **CPU never binds.**
  - The pod averaged **0.26 and 0.30 cores** over the load window in the cold run and warm2.
  - It averaged **0.49** in the warm run, where another tester also ran notebooks inside the same Lab.
  - Bursts are short. Postgres peaked at 1.2 cores averaged over the ~1.4 s vector-tile phase (2.0 cores in one 1 s sample). titiler costs 35–51 ms of CPU per tile.
- **Pre-pull: 3.36 GiB compressed (linux/amd64) per node** for all 9 images.
  - The Lab is 1.78 GiB.
  - stac-manager is 0.79 GiB, for a static app using 44–79 MiB of RAM.
- **Checks:** 31 PASS / 0 FAIL / 0 BLOCKED in each of cold, warm and warm2 (`results/{cold,warm,warm2}/run.out`). Not measured (see the end): amd64 CPU, real DaemonSets, multi-hour memory.

## How to reproduce

```sh
# stack up (evidence/build.md), then, with docker reachable:
spike/checks/footprint/run.sh cold      # ~6 min; first run after `compose ... up`/`start`
spike/checks/footprint/run.sh warm      # same again on the now-warm stack (warm2: later again)
FOOTPRINT_SEED=1790874859 spike/checks/footprint/run.sh cold   # replay the committed cold run's exact requests
python3 spike/checks/footprint/analyze.py spike/checks/footprint/results/warm   # re-analyse saved data
python3 spike/checks/footprint/cleanup_test.py   # SIGTERM run.sh mid-load, check nothing is left behind (~20 s)
```

- **What `run.sh` does:**
  - It prints one `PASS|FAIL|BLOCKED <name> — <detail>` line per check and always exits 0.
  - It writes `results/<label>/`:
    - raw data: `samples.csv`, `phases.tsv`, `snaps.jsonl`, `load.jsonl`, `kernel-3g.jsonl`, `images.json`, `disk.tsv`, `gdal.tsv`;
    - output: `analysis.txt` and `run.out`.
  - The host must stay awake for the whole run. `sampler.cadence` FAILs on any gap over 5 s.
  - If interrupted, it kills its sampler, removes its `spike-footprint-*` containers and deletes the Lab's `/tmp/spike-footprint-pylib`.
    - `cleanup_test.py` verifies this by sending SIGTERM to the process group mid-titiler load. Result: `PASS run.sh.cleanup-on-SIGTERM — exit 130 0 s after SIGTERM; containers left: none; Lab pip dir left: False; sampler still writing: False`.
    - Before `--init` was added, the load container ignored SIGTERM (Python ran as PID 1) and kept going for 407 s.
- **Files:**
  - `probe.py`: host-side `docker stats` sampler, cgroup snapshots, image sizes.
  - `load.py`: load generator and kernel code.
  - `analyze.py`: tables, rules and checks.
- **Provenance:**
  - `results/warm2/` was produced end-to-end by the committed `run.sh` and `analyze.py`.
  - `results/cold/` and `results/warm/` were collected by `run.sh` before the `--init`/cleanup change, which doesn't affect what is measured. Their `run.out` and `analysis.txt` were regenerated from their raw data with the committed `analyze.py`.

## Method

- **Sampling:**
  - `docker stats --no-stream` for all 9 containers every 2.02 s (median), 91–94 rounds per run; max gap 2.06 s (cold), 2.57 s (warm) and 2.56 s (warm2).
  - On cgroup v2 docker reports `memory.current − inactive_file`. That is the working set `kubectl top` and kubelet eviction use.
  - CPU per phase comes from cgroup `cpu.stat usage_usec` deltas (`docker exec … cat`) before and after each phase. These are exact CPU-seconds, so ~1 s bursts are still counted.
- **Timeline** (`phases.tsv`):
  1. idle 7 s (3–4 samples);
  2. titiler, 200 tiles;
  3. tipg, 100 tiles;
  4. STAC, 50 searches;
  5. kernel;
  6. "all": the four together, on a second tile set;
  7. post 10 s.

  Each load is followed by a 6 s settle.
- **Load** runs in throwaway `docker run --init --network container:eoapi-spike-lab-1` containers.
  - They share the pod's `localhost`, but their own CPU and memory are charged to no stack container.
  - Concurrency is 4. Auth uses the `Authorization: token` header, not `?token=` (build finding F1).
  - **titiler:** 200 PNG tiles through the Lab proxy, browser-style: `localhost:18888/raster/collections/glad-global-forest-change-1.11/tiles/WebMercatorQuad/{z}/{x}/{y}.png?assets=treecover2000&rescale=0,100&colormap_name=greens`.
    - Zooms 5–12 are mixed: 3×3 tiles around 3 centres in the glad band, shuffled.
    - A seeded longitude shift gives each run a fresh tile set, so titiler's caches start cold.
    - Tiles read MAAP COGs on S3 us-west-2.
  - **tipg:** 100 MVT tiles of `features.ecoregions` through the Lab proxy, zooms 1–7.
  - **STAC:** 50 searches straight to stac-auth-proxy (`localhost:8084/stac`), kernel-style.
    - The mix is POST `/search` with bbox and limit 100, GET `/items` with bbox, and POST with datetime + sortby.
  - **Kernel:** a real Lab kernel, started with `POST /api/kernels` and driven over its websocket.
    1. It reads a **22400×22400 uint8 window (478 MiB)** of notebook 04's COG `Hansen_GFC-2023-v1.11_lossyear_40N_080W.tif` with `rioxarray.open_rasterio(...).isel(...).load()`.
    2. It makes one same-size temporary: `(da.values > 0).sum()`.
    3. It holds the array 12 s, then `del` + `gc`.
    4. It reports `VmRSS`/`VmHWM` per step.
    - **rioxarray, xarray and pandas are not in the workshop image** (`environment.yml`), and no notebook uses rioxarray, so this kernel is a synthetic stress test.
    - `run.sh` installs them with `pip --target /tmp/spike-footprint-pylib` inside the Lab after the idle window, then deletes them. The shared conda env is untouched.
  - **The same raster job under `--memory 3g --memory-swap 3g`** runs outside the stack. This is what the Lab sees on k8s with the chart's 3Gi limit.
- **Fresh-stack baseline:** one manual `docker stats --no-stream` at 17:12:45Z, 3 min after the stack was restarted and before any run. Its values are in the first column of the table below.

### Noise (read before using the numbers)

- **Other testers used the same stack concurrently.**
  - Between the fresh sample (17:12:45Z) and the cold run's start (~17:14Z), someone warmed it: Postgres went 41 → 198 MiB, titiler 145 → 182, stac-manager 33 → 60.
  - A foreign kernel `3540812a` (56 MiB) was in the Lab at the cold run's start.
  - **During the warm run's titiler → kernel phases, another tester ran notebooks headless inside the same Lab.**
    - It used an `external` (nbclient) kernel of up to 214 MiB, and jupyter CLI processes of +87 MiB.
    - In the Lab that cost 14.8 CPU-s during our titiler phase and 11.3 during our kernel phase, plus some stac-fastapi and stac-auth-proxy CPU.
    - The warm run's Lab CPU therefore reflects "a participant running notebooks while their map loads", not our load alone.
  - The cold run's stac-manager burst (1.0 core in a 1 s sample, 2.3 CPU-s in "all") is someone else using it. It is emulated amd64.
  - In warm2 an idle foreign kernel `3619d1fa` (56 MiB) sat in the Lab. The process snapshots show no other kernels and flat jupyter processes (138–141 MiB). Warm2 is therefore the cleanest "our load only" run on a warm stack.
  - Between warm (~17:18Z) and warm2 (~18:48Z), other testers kept using the stack. That is part of why warm2 is warmer.
- **CPU is Apple Silicon in Docker Desktop's VM.** OVH b3 vCPUs (amd64) were not measured. stac-browser and stac-manager run emulated, so their CPU is inflated.
- **The load is one participant's synthetic burst.** It is heavier than notebooks 02–08, which call APIs and hold no big arrays.
- **S3 latency dominates titiler:** p50 ≈ 1.0 s and p95 2.1–2.6 s per tile, from a European laptop to us-west-2.
- **Sum of per-container peaks ≠ pod peak.** "Busiest moment" is the largest sum over the 9 containers within one sampling round. The kernel's ~0.5 s spike between samples (VmHWM − held RSS = 478 MiB) is added back to that round. This is conservative.
- **Host suspension.** Two earlier attempts at the third run were invalid: the Mac was suspended mid-run, with sampler gaps of 933 s and 925 s and a 7 s `sleep` taking 76 s. `caffeinate -i` did not prevent it. Both were stopped, cleaned up and discarded, not analysed. The third attempt (`results/warm2/`) ran uninterrupted, with a max gap of 2.56 s.

## Results

### Memory per container (MiB, working set)

| container | fresh (17:12:45Z) | cold: idle / steady | warm: idle / steady | warm2: idle / steady | peak, per run (cold / warm / warm2) | chart request / limit |
|---|---|---|---|---|---|---|
| lab | 96 | 150 / 128 | 117 / 145 | 189 / 231 | 2217 / 2387 / 1950 (k8s-adj. 1875 / 2045 / 1608) | 1024 / 3072 |
| database | 41 | 198 / 278 | 278 / 278 | 176 / 302 | 278 / 307 / 302 | 560 / 960 |
| stac-fastapi | 62 | 62 / 62 | 62 / 85 | 88 / 95 | 62 / 86 / 95 | 176 / 320 |
| titiler-pgstac | 145 | 182 / 254 | 254 / 330 | 360 / 370 | 256 / 331 / **372** | 432 / 704 |
| tipg | 63 | 77 / 77 | 77 / 126 | 130 / 132 | 77 / 132 / 132 | 176 / 320 |
| stac-auth-proxy | 151 | 152 / 152 | 152 / 174 | 170 / 169 | 152 / 179 / 170 | 224 / 384 |
| mock-oidc | 42 | 43 / 43 | 43 / 44 | 44 / 44 | 43 / 44 / 44 | 80 / 128 |
| stac-browser | 17 | 17 / 17 | 17 / 18 | 19 / 21 | 17 / 18 / 27 | 32 / 128 |
| stac-manager | 33 | 60 / 60 | 60 / 60 | 60 / 44 | 70 / 60 / 79 | 80 / 128 |
| **pod** | **651** | 943 / 1073 | 1062 / 1260 | 1235 / 1408 | busiest moment 3154 / 3412 / 3123 (k8s-adj. 2812 / 3070 / 2781) | **2784 / 6144** |

- **Steady** is the mean over the 10 s after all loads, and "under load (median)" is in `analysis.txt`. **Peak** is the highest 2 s sample.
- For the Lab, the peak adds back the kernel's VmHWM spike. "k8s-adj." replaces the uncapped kernel peak (1619) with the one measured under a 3 GiB limit (1277).
- The Lab's peak includes other testers' kernels whenever they were present.
- **Growth with use:** every backend that does work grew from the fresh sample on (titiler, tipg, stac-fastapi, Postgres, stac-auth-proxy). Python processes keep what they touch.
  - Over three runs, tipg and stac-auth-proxy flattened, and stac-fastapi slowed (62 → 85 → 95).
  - **titiler is still rising** (254 → 330 → 370 after load), despite `GDAL_CACHEMAX=200`.
  - Postgres's working set dropped between runs (278 → 176 idle), probably idle pool connections closing, then returned to ~300 under load.

### The Lab kernel (the 478 MiB raster)

These values were identical in all three runs, and to the WIP's numbers.

| | no memory limit (in the Lab) | `--memory 3g` (k8s-like) |
|---|---|---|
| GDAL default `GDAL_CACHEMAX` | 1199 MiB (5 % of 23.4 GiB) | 153 MiB (5 % of 3 GiB) |
| RSS after imports (numpy, rasterio, rioxarray, xarray, pandas, osgeo) | 152 MiB | 134 MiB |
| RSS holding the array | 1141 MiB | **799 MiB** |
| **peak (`VmHWM`), during the same-size temporary** | **1619 MiB** | **1277 MiB** |
| RSS after `del` + `gc` (GDAL cache still holds blocks) | 612 MiB | 321 MiB |
| time to read 478 MiB from S3 us-west-2 | 6.5–7.1 s | (not compared) |

- `gdal.cachemax-cgroup-aware` PASS: the Lab image's GDAL defaults to 1199 MiB, but to 204 MiB under `--memory 4g`. On k8s the container limit caps GDAL's cache, so no override is needed in the Lab. Locally, with no limit, the kernel caches up to 1.2 GiB.
- The kernel survived the 3 GiB limit. The k8s-adjusted Lab peak (1608–2045 MiB, server + kernel + any other kernels) leaves 1.0–1.4 GiB under 3Gi. A second such kernel peaking at once would not fit.
- The Lab already culls idle kernels after 1 h (`lab/jupyter_server_config.py:27`). That matters because a "freed" kernel still holds 321–612 MiB.

### CPU (millicores averaged per phase from `cpu.stat`; pod totals)

| run | idle | titiler (200 tiles) | tipg (100 tiles) | STAC (50) | kernel | all | whole load window |
|---|---|---|---|---|---|---|---|
| cold | 53 | 219 | 1598 | 765 | 156 | 352 | **255** |
| warm (+ another tester's notebooks in the Lab) | 24 | 461 | 2100 | 760 | 823 | 346 | **486** |
| warm2 | 146 | 330 | 1508 | 730 | 282 | 313 | **304** |

Lab alone, whole load window: 61m (cold), **229m (warm, with the other tester's notebooks)** and 73m (warm2).

CPU-seconds and per-request costs, cold run (`analysis.txt` has per-container tables):
- **titiler:** 8.2 CPU-s for 200 tiles, so **41 ms per tile**. The "all" phase gave 44 ms per tile; warm gave 35 and 51 ms.
- **Lab proxy:** 1.9 CPU-s in the Lab during the 200 proxied raster tiles, so ≤ 9.5 ms per tile, idle included. Vector tiles cost 0.2 CPU-s per 100.
- **tipg:** Postgres does the work: 2.0 CPU-s in a ~1.4 s phase (1.2 cores average, 2.0 cores in one 1 s sample). tipg itself used 0.4 CPU-s.
- **STAC:** 1.0 CPU-s per 50 searches, so 20 ms each. 12 ms of that is stac-auth-proxy; stac-fastapi took 2 ms and Postgres 4 ms.
- **Kernel:** 2.8 CPU-s in the Lab for the 478 MiB read.

### Load results

All requests returned 2xx in both runs (titiler 204 = tile outside data):

| run | titiler set a: wall / p50 / p95 | titiler set b (with the rest at once) | tipg p50 / p95 | STAC p50 / p95 |
|---|---|---|---|---|
| cold | 54.2 s / 0.98 / 2.12 s | 55.1 s / 1.01 / 2.63 s | 7 / 166 ms | 47 / 87 ms |
| warm | 55.7 s / 0.99 / 2.25 s | 51.6 s / 0.97 / 2.12 s | 6 / 131 ms | 49 / 74 ms |
| warm2 | 48.7 s / 0.85 / 2.11 s | 54.5 s / 0.99 / 2.63 s | 6 / 134 ms | 46 / 77 ms |

## Recommended requests and limits

**The rule in `analyze.py`:**
- memory request = 1.25 × max(idle, load median, after load), on a 16 Mi grid;
- memory limit = 2 × peak, on a 64 Mi grid; for the Lab, 1.5 × the k8s-adjusted peak on a 512 Mi grid;
- Lab request = (idle Lab + 2 kernels with the scientific stack imported) × 1.25, on a 256 Mi grid;
- CPU request = average over the whole load window, at least 10m.

Per run, against the chart (memory request / limit, Mi):

| container | cold rule | warm rule | warm2 rule | chart now | **proposed** |
|---|---|---|---|---|---|
| lab | 768 / 3072 | 768 / 3072 | 768 / 2560 | 1024 / 3072 | keep |
| database | 352 / 576 | 352 / 640 | 384 / 640 | 560 / 960 | keep |
| stac-fastapi | 80 / 128 | 112 / 192 | 128 / 192 | 176 / 320 | keep |
| titiler-pgstac | 320 / 512 | 416 / 704 | **464 / 768** | 432 / 704 | **464 / 768** |
| tipg | 112 / 192 | 160 / 320 | 176 / 320 | 176 / 320 | keep |
| stac-auth-proxy | 192 / 320 | 224 / 384 | 224 / 384 | 224 / 384 | keep |
| mock-oidc | 64 / 128 | 64 / 128 | 64 / 128 | 80 / 128 | keep |
| stac-browser | 32 / 128 | 32 / 128 | 32 / 128 | 32 / 128 | keep |
| stac-manager | 80 / 192 | 80 / 128 | 80 / 192 | 80 / 128 | 80 / **192** |
| **pod** | 2000 / 5248 | 2208 / 5696 | 2320 / 5312 | 2784 / 6144 | **2816 / 6272** |

**Memory: keep the chart's values, except titiler and stac-manager's limit.**
- The chart is ≥ every steady state and ≥ every peak measured (Lab: k8s-adjusted).
- But titiler's working set is still rising (370 MiB after warm2), and the warm2 rule's 464 Mi request now exceeds the chart's 432.
- Do **not** trim toward the rule's lower pod total (2.0–2.3 GiB), which would allow 5 per b3-16 instead of 4:
  - (a) the rule's output rose with every run;
  - (b) the WIP's earlier stack lifetime, after hours of other testers' use, sat higher (pod warm idle 1700 MiB; unverified, not re-measurable after the restart);
  - (c) only ~20 min of synthetic load was measured in total.
- Trim only after a multi-hour soak.

**CPU: raise a few requests.** CPU doesn't bind packing, but requests set each container's CFS share when a node is contended. The warm run shows a participant running notebooks in the Lab while their map loads.

| container | chart now | measured whole-window average (cold / warm / warm2) | proposed |
|---|---|---|---|
| lab | 100m | 61m / **229m** / 73m | **250m** (sized for the notebooks-in-Lab case) |
| titiler-pgstac | 120m | 106m / 117m / 138m | 140m |
| stac-fastapi | 10m | 3m / 21m / 4m | 30m |
| tipg | 10m | 6m / 11m / 9m | 20m |
| stac-auth-proxy | 40m | 11m / 44m / 16m | 50m |
| database | 60m | 47m / 57m / 56m | keep |
| others | 10m each | 2–17m | keep |

- The pod goes from 370m to 580m. It still fits: 2 per b3-8 is 1.41 of 1.84 CPU with assumed DaemonSets, 4 per b3-16 is 2.57 of 3.68, and 10 per b3-32 is 6.05 of 7.84.
- **No CPU limits.** They would only throttle ~1 s tile and MVT bursts.

## Participant pods per node (`analysis.txt`, requests-based)

- **b3-8 allocatable is measured on "labs":** 1.84 CPU / 5.77 GiB.
- **b3-16 and b3-32 are EXTRAPOLATED** two ways, from nominal 4 vCPU / 16 GB and 8 vCPU / 32 GB:
  - **proportional:** the same allocatable/nominal ratio as b3-8, conservative;
  - **fixed reserve:** the same absolute reserve as b3-8, optimistic. This depends on b3-8 being 8 GB rather than 8 GiB, which was not checked.
- **DaemonSet requests are ASSUMED** at 0.25 CPU / 0.25 GiB per node.

| request profile | b3-8 (measured) | b3-16 prop. / fixed | b3-32 prop. / fixed |
|---|---|---|---|
| **proposed** (2.75 GiB, 0.58 CPU; computed by hand from the chart rows) | **2 on paper** (0.02 GiB spare) | **4 / 4** | **8 / 10** |
| chart as committed (2.72 GiB, 0.37 CPU) | 2 (0.08 GiB spare) | 4 / 4 | 8 / 10 |
| warm2 rule, Lab "notebooks" (2.27 GiB, 0.35 CPU) | 2 | 4 / 5 | 10 / 12 |
| warm2 rule, Lab holding the raster (2.77 GiB) | **1** | 4 / 4 | 8 / 10 |
| warm rule (2.16 GiB, 0.54 CPU) | 2 | 5 / 6 | 10 / 12 |
| cold rule (1.95 GiB, 0.31 CPU) | 2 | 5 / 6 | 11 / 14 |

- Memory binds in every row.
- **Plan on 1 pod per b3-8** unless the pool's real DaemonSet requests are measured under 0.27 GiB.
- At these densities the memory **limits** sum to 1.6–2.6× allocatable. If several participants on one node push their Labs toward 3Gi at once, the node runs short. The kubelet then evicts the pod furthest above its requests, **and that takes the whole participant stack, including its emptyDir database.**
- Mitigations:
  - prefer b3-16 or b3-32;
  - keep notebook content well below the Lab limit;
  - use a PVC for the DB if data must survive an eviction.

## Images and pre-pull

The pull size is linux/amd64 compressed, from the registry manifest (`docker buildx imagetools inspect --raw`). The local size is `docker image ls` (arm64 unpacked unless noted).

| image | pull (amd64, compressed) | local `docker image ls` |
|---|---|---|
| Lab: `ghcr.io/developmentseed/eoapi-workshop:latest` (same `Dockerfile.local` + `environment.yml`; the spike adds jupyter-server-proxy, a 602 kB layer per `docker history`) | **1822 MiB** | 6.68 GB (`eoapi-spike-lab`) |
| DB: `ghcr.io/stac-utils/pgstac:v0.9.11` (the spike adds a 48.8 MB ecoregions layer + 20 kB glad + 12 kB tuning) | 258 MiB | 1.13 GB (`eoapi-spike-db`) |
| `ghcr.io/stac-utils/stac-fastapi-pgstac:7.0.0` | 73 MiB | 362 MB |
| `ghcr.io/stac-utils/titiler-pgstac:3.2.0` | 138 MiB | 1.23 GB |
| `ghcr.io/developmentseed/tipg:1.6.1` | 63 MiB | 279 MB |
| `ghcr.io/developmentseed/stac-auth-proxy:v1.2.0` | 61 MiB | 289 MB |
| `ghcr.io/alukach/mock-oidc-server@sha256:5972ad…` | 161 MiB | 629 MB |
| `ghcr.io/radiantearth/stac-browser:5.1.0` | 47 MiB | 223 MB (amd64) |
| `ghcr.io/developmentseed/stac-manager:1.0.3` | **814 MiB** | 3.75 GB (amd64) |
| **unique layers, all 9** | **3437 MiB = 3.36 GiB per node** | |

- `images.lab-pull-1.8GiB` PASS: 1.78 GiB.
- **Disk:**
  - The containers' writable layers are tiny: Lab 12–14 MB, stac-manager 27 MB, mock-oidc 10 MB, the rest under 0.3 MB.
  - **The Postgres data dir is 207 MiB (cold) and 184 MiB (warm).** That is the emptyDir's size.
  - The rioxarray install added ~92 MB to the Lab's layer while present. A participant's `pip install` does the same.

## What changed from the WIP attempt

| WIP claim | Rerun |
|---|---|
| Kernel 1619 / 1277 MiB peak, GDAL 1199 / 204 / 153 MiB, images 1.78 / 3.36 GiB, titiler ~35–74 ms CPU per tile | **Reproduced** exactly or within range |
| Warm idle pod 1.7 GiB (DB 447, stac-fastapi 129, tipg 136, Lab 370 MiB) | **Not reproduced** (1.06 GiB here). That was an earlier stack lifetime after hours of other testers' use, and the stack has been restarted since. Kept only as a reason not to trim the chart, not as a measurement. |
| "Lab limit 3Gi (overridden from the rule's 3.5Gi)", pod limits 6144Mi | The WIP's own `analysis.txt` printed **3584Mi / 6656Mi**: the evidence did not match its script. The rule now lives in `analyze.py` (1.5 × k8s-adjusted Lab peak) and prints 3072Mi (cold, warm) and 2560Mi (warm2). |
| `plan.participant-under-3.5GiB-under-load` PASS at 3.27 GiB | The WIP changed this check's criterion after it FAILed. It now emits two lines: `-k8s-estimate` and `-local-no-limit`. Re-analysing the WIP's raw data with the final script, the local line **FAILs** (3.61 GiB). On the fresh runs both PASS (local 3.08 / 3.33 / 3.05 GiB, k8s 2.75 / 3.00 / 2.72 GiB). |
| `sampler.cadence` checked only the median | The median alone would have passed the suspended attempts (one gap of 933 s among ~2 s intervals). It now also FAILs on any gap over 5 s. |
| "b3-8 holds 2" | True only on paper: a 0.08 GiB margin with the committed chart (0.02 GiB with the titiler raise) under the ASSUMED DaemonSets. The check detail now says so, and passes only if both the rule and the chart values fit. |

## Raw output (`results/warm/run.out`, trimmed; `results/cold/run.out` and `results/warm2/run.out` have the same 31 checks, all PASS)

```
PASS sampler.cadence — 93 docker-stats rounds x 9 containers, median interval 2.02 s, max 2.57 s (FAIL if median > 2.5 s or any gap > 5 s)
PASS sampler.idle-samples — 3 rounds in the idle window
PASS load.titiler-a — 200/200 2xx codes={'200': 197, '204': 3} wall=55.7s p50=0.993s p95=2.247s max=4.577s c=4 seed=1790875096 lon_shift=-0.56
PASS load.tipg-a — 100/100 2xx codes={'200': 100} wall=0.7s p50=0.006s p95=0.131s max=0.263s c=4 seed=1790875096 lon_shift=-0.56
PASS load.stac-a — 50/50 2xx codes={'200': 50} wall=0.6s p50=0.049s p95=0.074s max=0.093s c=4 seed=1790875096 lon_shift=-0.56
PASS load.tipg-b — 100/100 2xx … PASS load.stac-b — 50/50 2xx … PASS load.titiler-b — 200/200 2xx codes={'200': 194, '204': 6} wall=51.6s p50=0.965s p95=2.12s
PASS kernel.rioxarray-500MB — 478 MiB uint8 [22400, 22400] in 6.7 s; kernel RSS start=55 imported=152 loaded=1141 computed=1141 freed=612 MiB; PEAK (VmHWM)=1619 MiB; GDAL_CACHEMAX=1199 MiB; other kernels at start: []
PASS kernel.rioxarray-500MB-under-3GiB-limit — same job, --memory 3g: GDAL_CACHEMAX=153 MiB; RSS imported=134 loaded=799 held=799 freed=321 MiB; PEAK (VmHWM)=1277 MiB; not OOM-killed
PASS mem.lab — idle 117 MiB, load median 274, peak 2387, after load 145 (cgroup memory.peak incl. page cache 2150); CPU idle 0.0%, avg under load 229m, busiest phase 698m, peak 1-s sample 153%
PASS mem.database — idle 278 MiB, load median 278, peak 307, after load 278 (…434); CPU … avg under load 57m, busiest phase 1128m
PASS mem.titiler-pgstac — idle 254 MiB, load median 283, peak 331, after load 330 (…338); CPU … avg under load 117m, busiest phase 195m
PASS mem.tipg — idle 77 MiB, load median 97, peak 132, after load 126 (…148)
PASS mem.stac-fastapi — idle 62 MiB, load median 64, peak 86, after load 85 (…123)
PASS mem.stac-auth-proxy — idle 152 MiB, load median 154, peak 179, after load 174 (…218); CPU … busiest phase 455m
PASS plan.backend-idle-under-1.5GiB — backend (all but Lab) idle = 945 MiB with one uvicorn worker each (skeptic review claim)
PASS plan.participant-under-3.5GiB-local-no-limit — pod total at its busiest moment as measured = 3.33 GiB (no memory limit, kernel GDAL cache 1619 MiB peak); this is what a laptop compose stack uses
PASS plan.participant-under-3.5GiB-k8s-estimate — pod total at its busiest moment = 3.00 GiB with the k8s-limited kernel peak (ESTIMATE: …; sum of per-container peaks, never simultaneous, = 3.46 GiB) …
PASS plan.b3-8-holds-2-pods — per b3-8 after ASSUMED DaemonSet requests 0.25 GiB: this run's rule 2 pods, chart values 2; this run's rule: pod 2.16 GiB, 1.21 GiB left with 2 pods (…< 1.46 GiB); chart values: pod 2.72 GiB, 0.08 GiB left with 2 pods (2 fit only if real DaemonSets request < 0.33 GiB); 2 if every Lab holds the raster (skeptic: ~2)
PASS plan.20-users-on-4-5-b3-16 — per b3-16 (EXTRAPOLATED, proportional): this run's rule 5 pods, chart values 4 -> 6 b3-16 for 20 users incl. 1 spare at the lower density (skeptic: 4-5 + 1 spare)
PASS chart.requests-cover-steady — chart memory request >= steady working set (max of idle, load median, after load) for every container; below: none; not parsed: none
PASS chart.limits-cover-peaks — chart memory limit >= measured peak (Lab: k8s-adjusted 2045 MiB) for every container; below: none
PASS images.lab-pull-1.8GiB — ghcr.io/developmentseed/eoapi-workshop:latest linux/amd64 compressed = 1.78 GiB
PASS images.per-node-prepull — all 9 images, linux/amd64, unique compressed layers = 3.36 GiB per node (stac-manager alone 0.79 GiB)
PASS disk.ephemeral — stac-manager=27.3MB …; lab=13.8MB (virtual 4.83GB); pgdata MiB=184
PASS gdal.cachemax-cgroup-aware — default GDAL_CACHEMAX in the Lab image: 1199 MiB without a memory limit, 204 MiB under --memory 4g
```

Cold run, the lines that differ in substance:

```
PASS mem.lab — idle 150 MiB, load median 179, peak 2217, after load 128 …; CPU … avg under load 61m, busiest phase 132m
PASS mem.database — idle 198 MiB, load median 272, peak 278, after load 278 …; CPU … busiest phase 1213m, peak 1-s sample 199%
PASS plan.participant-under-3.5GiB-local-no-limit — … = 3.08 GiB …
PASS plan.participant-under-3.5GiB-k8s-estimate — … = 2.75 GiB … sum of per-container peaks … = 3.10 GiB …
PASS plan.b3-8-holds-2-pods — … this run's rule: pod 1.95 GiB, 1.61 GiB left with 2 pods …; chart values: pod 2.72 GiB, 0.08 GiB left …
PASS plan.20-users-on-4-5-b3-16 — … this run's rule 5 pods, chart values 4 -> 6 b3-16 for 20 users incl. 1 spare …
PASS chart.limits-cover-peaks — … (Lab: k8s-adjusted 1875 MiB) … below: none
```

Warm2 run (seed 1790880490), the lines that differ in substance:

```
PASS sampler.cadence — 91 docker-stats rounds x 9 containers, median interval 2.02 s, max 2.56 s (FAIL if median > 2.5 s or any gap > 5 s)
PASS mem.lab — idle 189 MiB, load median 259, peak 1950, after load 231 (…2150); CPU idle 5.2%, avg under load 73m, busiest phase 204m, peak 1-s sample 90%
PASS mem.database — idle 176 MiB, load median 298, peak 302, after load 302 (…434); CPU … busiest phase 1092m
PASS mem.stac-fastapi — idle 88 MiB, load median 95, peak 95, after load 95 (…128)
PASS mem.titiler-pgstac — idle 360 MiB, load median 370, peak 372, after load 370 (…411); CPU idle 0.1%, avg under load 138m
PASS mem.tipg — idle 130 MiB, load median 131, peak 132, after load 132 (…149)
PASS plan.participant-under-3.5GiB-local-no-limit — … = 3.05 GiB …
PASS plan.participant-under-3.5GiB-k8s-estimate — … = 2.72 GiB … sum of per-container peaks … = 3.10 GiB …
PASS plan.b3-8-holds-2-pods — … this run's rule: pod 2.27 GiB, 0.99 GiB left with 2 pods …; chart values: pod 2.72 GiB, 0.08 GiB left …; 1 if every Lab holds the raster (skeptic: ~2)
PASS plan.20-users-on-4-5-b3-16 — per b3-16 (EXTRAPOLATED, proportional): this run's rule 4 pods, chart values 4 -> 6 b3-16 for 20 users incl. 1 spare …
PASS chart.requests-cover-steady — … below: none; not parsed: none
PASS chart.limits-cover-peaks — … (Lab: k8s-adjusted 1608 MiB) … below: none
```

## Not measured

- **A full plateau.** Over three valid runs (~1.5 h of stack life) tipg and stac-auth-proxy flattened, but titiler (254 → 330 → 370 MiB) and stac-fastapi (62 → 85 → 95) were still rising. Two more attempts were invalidated by host suspension (see Noise).
- **Memory over hours** (a workshop day), and notebooks 02–08 as the load. Another tester ran the notebooks concurrently; they show up here only as noise.
- **amd64 CPU cost on b3 vCPUs.**
- **The real DaemonSet requests on a workshop-pool node.** They decide whether a b3-8 holds 1 or 2 pods.
- **More than one participant pod per node.** The kind cluster exists but is stopped, and was left alone.
- **A browser:** STAC Browser and stac-manager page loads (covered by the browser-apps topic).
