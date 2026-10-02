# Verify: skeptic re-run and completeness review

*2026-10-02, 07:00–07:30 UTC · branch `spike/per-user-stacks` · Docker Desktop on an arm64 Mac · kind v0.32.0, helm v4.1.4, ingress-nginx controller-v1.15.1 · every number below comes from a run made in this stage, not from earlier reports.*

## Why this file exists

The workflow was interrupted by a usage limit more than once. A first verify attempt had already started (logs dated 2026-10-01 22:35–23:02 UTC, an untracked `checks/footprint/results/verify/` and modified screenshots in the worktree), but it never wrote conclusions. **I treated that attempt as unverified and re-ran everything myself**:

1. Recreated the kind cluster from scratch (it had already been deleted), installed the own chart fresh, deployed the hub, ran both front-door suites plus new refutation probes, then deleted the cluster.
2. Restarted the compose stack (`docker compose ... start`) and re-ran every `spike/checks/*/run.sh`.

## Results (this stage) against what was claimed

| Topic | Claimed (fix / own-chart / hub stage) | This run | Verdict |
|---|---|---|---|
| frontdoor-own (kind, fresh install) | 58 / 1 / 0 | **58 / 1 / 0** | holds |
| frontdoor-hub (kind, fresh deploy) | 64 / 1 / 0 | **64 / 1 / 0** | holds |
| build | 45 / 1 / 0 | **44 / 2 / 0** | weakened: `arch.lab` FAIL, see V1 |
| apis | 61 / 4 / 0 | **61 / 4 / 0** | holds |
| auth | 56 / 4 / 0 | 57 / 3 / 0 first, then **56 / 4 / 0** after a check fix | holds; the first run was a false PASS, see V2 |
| browser-apps | 32 / 1 / 0 | **31 / 2 / 0** | weakened: cold-cache tile check, see V3 |
| notebooks | 135 / 2 / 4 | **135 / 2 / 4** | holds |
| footprint | 31 / 0 / 0 | **31 / 0 / 0** | holds (pod at busiest 3.14 GiB local, 2.80 GiB k8s estimate) |
| verify/own.sh (new) | – | **3 PASS, 1 FAIL** | new finding, see V4 |

The remaining FAILs are the same ones fix.md already names (the `?token=` clash, stac-auth-proxy query encoding upstream, stac-manager Delete upstream, Lab home not persisted, hub token on `/stac`), plus V1, V3 and V4 below.

## Findings from this stage

**V1. The compose Lab runs on an image that no longer exists in the image store.** The `lab` container's image `sha256:0acff379…` returns "No such image", so `build/run.sh` cannot read its architecture (`FAIL arch.lab — ` with an empty detail). Cause: the own-chart tester rebuilt `eoapi-spike-lab` at 21:52 for kind, which orphaned the image the compose container was created from. The stack still works (docs are bind-mounted, and the auth checks show the cookie fix is live), but it is not running the current `eoapi-spike-lab:latest`. The next `docker compose up` will recreate it. In the same file, `arch.stac-browser` and `arch.stac-manager` print PASS unconditionally (`build/run.sh:30-33`), so they prove nothing.

**V2. `auth/run.sh`'s `laptop.stac.lab-token-in-error-log` gave a false PASS. Fixed.** In the first auth run the same `?token=` requests returned 500, but the check reported "no pgstac cursor error since 07:16:15Z". The Docker VM clock lagged the host by about 4 min 12 s after a host sleep: the auth gate requests are logged at 07:12:03 VM time while the host clock read 07:16:1x. `docker logs --since <host time>` therefore skipped them. The check now takes `since` from the stac-fastapi container's own clock. The re-run FAILs as expected: 3 lines carry the Lab token. The same sleep stretched the apis run to 4 min 44 s of wall time, against about 36 s in container time. Results were unaffected; footprint's `sampler.cadence` catches sleeps, but the other suites do not.

**V3. `browser-apps` 32/1 depended on a warm tile cache.** `iframe.raster-world-tile-latency` FAILs on a freshly started stack: the glad world tile 0/0/0 took **112.3 s** (the interrupted verify attempt measured 106.2 s). It takes 0.4 s when warm. The fix stage's PASS came from a warm titiler. Every participant pod starts cold, so on event day the first world-view map in notebook 04 takes about 2 minutes for everyone.

**V4. Pod replacement loses all participant data (own chart).** `checks/verify/own.sh` wrote a STAC collection and a Lab file in u01, replaced the pod with `kubectl rollout restart`, and read them back. Both returned **404**. The DB is an `emptyDir` and the Lab home is the container layer, so eviction, node loss, a pod-template-changing `helm upgrade` or a manual restart wipes the notebook 02 collection and every notebook edit. The evidence so far only showed the Lab-container-restart case. Related: bumping one shared image tag changes **2 of 2** participant pod templates (render-level check), so with `strategy: Recreate` a routine chart change restarts and wipes every stack at once. `upgrade.no-restart` PASSes only for a no-op upgrade. On the hub, `storage.type: none` plus `pgdata` emptyDir means a participant clicking "Stop My Server" deletes the pod and its data. That last point is inferred from KubeSpawner's design, not run.

**V5. Cross-user cookie replay is refused (new check, PASS).** A valid u01 login cookie replayed on `lab-u02`, under either cookie name, gives `/api/status` 403 and `/stac/collections` 302. Each pod has its own cookie secret.

## Provenance of the evidence files

- **No evidence file carries data from the WIP commit 95823c1.**
  - Its footprint files at the root of `results/` were replaced by `cold/`, `warm/` and `warm2/` (fb29e60).
  - Its screenshots were replaced (3fcdbec).
  - `notebooks.md`, `footprint.md` and `browser-apps.md` were rewritten by the re-runs, and each says what it corrected in the WIP.
  - The first own-chart attempt (1f1c4ba, b837872, a09d79b) is superseded by 88ef24b and 6807d5b, which flagged that the 46/0/0 kind run had served stale notebooks.
- **But `build.md`, `apis.md`, `auth.md`, `browser-apps.md`, `notebooks.md` and `footprint.md` all describe the pre-fix stack.** They were last written before ac03acf, and none says it is superseded. For example, `auth.md` still reports "every backend binds 0.0.0.0" and 61/17. The current state lives only in `fix.md` and this file.
- **The token fragment in 95823c1 is dead.** `spike/.env` was regenerated at 20:03, after the WIP commit at 18:08. The blob is still in branch history; removing it before any push is Loïc's call.
- **Raw tester logs.** The hub's `.frontdoor-hub-run3.log` and the previous verify log differ in timings and revisions, so they come from separate runs, not copies.

## Not tested, though the event depends on it

1. **TLS and the real ingress.**
   - No https anywhere locally: `tls.mixed-content` is BLOCKED and Secure cookies were only simulated with X-Forwarded-Proto.
   - No cert-manager or Let's Encrypt. The own chart needs a cert for every `lab-uNN` host: a wildcard means a DNS-01 challenge, and per-host certs mean 20 HTTP-01 issuances plus DNS for each. The hub needs one host.
   - No Calico. NetworkPolicy enforcement was shown on kindnet only.
2. **Kernel websockets through an ingress.** No kind check ran a notebook kernel through ingress-nginx (`proxy-read-timeout 3600` is set but never exercised). Kernels were only run inside the Lab container.
3. **20 participants at once.** Only 2 pods ever ran. Not covered:
   - Scheduler packing, real node allocatable and DaemonSet requests (BLOCKED in footprint).
   - 20 notebook 02 loads hitting Earth Search together, and 20 cold glad world tiles hitting the MAAP S3 bucket together (V3, each about 2 minutes on its own).
4. **Image pull on fresh amd64 nodes.**
   - `eoapi-spike-lab` and `eoapi-spike-db` exist only as local arm64 images. They were never built for amd64 or pushed to a registry.
   - The DB image fetches glad from MAAP at build time.
   - The 3.36 GiB/node pull is an estimate. No pre-puller exists for the own chart, and ghcr.io pull limits are untested.
5. **Node failure, eviction, OOM.** The data loss is shown (V4). Also untested:
   - No PodDisruptionBudget.
   - A kernel OOM at the 3Gi Lab limit: the cgroup kill could take the kernel or the whole container.
   - Rescheduling time when a node dies.
6. **`helm upgrade` mid-event.** Any change under `containers` restarts and wipes every stack (V4). There is no tested procedure for a safe mid-event change.
7. **Data reset between sessions.** No reset procedure was tested. Today a reset means deleting pods, which also wipes participant work. The compose README notes `-V`.
8. **Credential handout.** How 20 passwords reach participants (Secret → sheet) was never exercised. The hub's static authenticator was run with 2 users only.
9. **Long soak.** titiler and stac-fastapi memory was still rising after 1.5 h (footprint BLOCKED `plateau.multi-hour-memory`).
10. **Real browsers on participant laptops.** Only headless Chromium was used. Not covered:
    - Firefox and Safari ITP with the `SameSite=Lax` cookie across the OIDC redirect.
    - Venue Wi-Fi or proxies.
11. **Hub specifics.** Not run:
    - The admin UI.
    - Culling (off).
    - A participant stopping their own server (V4).
    - Notebooks 02-08 under `/user/uNN/`.
    - A laptop reaching `/stac` with a hub token, which FAILs by design.

## Changes made in this stage

- `spike/checks/auth/run.sh`: `since` comes from the container clock (V2).
- New `spike/checks/verify/compose.sh`: runs every compose topic in sequence and prints one summary line per topic.
- New `spike/checks/verify/own.sh` and `own_extra.py`: the V4 and V5 probes on kind.
- `spike/checks/footprint/results/verify/`: raw data of this stage's footprint run.
- Re-captured `spike/evidence/screens/` from this stage's browser-apps and hub runs. A scan found no Lab token or password in the committed text files; the PNGs are what the checks rendered, after the fix that keeps the token off screen.

During the V2 investigation, one diagnostic command printed a stac-fastapi log line containing the current Lab token to this session's tool output. It was not written to any file. Rotate it with `./gen-env.sh` and a stack recreate if wanted.

## Commands

```sh
W=/Users/lhoupert/DevDS/ds/eoapi-workshop/.claude/worktrees/spike-per-user-stacks; S=$W/spike; KC=$S/.kind-kubeconfig
# kind: same steps as evidence/frontdoor-own.md "Reproduce" (compose stopped first)
docker compose -p eoapi-spike -f $S/compose.participant.yml stop
kind create cluster --name eoapi-spike --config $S/kind/cluster.yaml --kubeconfig $KC
kubectl --kubeconfig $KC --context kind-eoapi-spike apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.15.1/deploy/static/provider/kind/deploy.yaml
kind load docker-image --name eoapi-spike eoapi-spike-lab:latest eoapi-spike-db:latest
# docker save --platform ... | ctr import  (as in frontdoor-own.md)
helm --kubeconfig $KC --kube-context kind-eoapi-spike install spike $S/chart -n spike-own --create-namespace --wait   # 17.3 s
$S/checks/frontdoor-own/run.sh          # 58/1/0, 1 min 45 s
$S/checks/verify/own.sh                 # V4, V5
$S/hub/deploy.sh                        # 1 min 17 s
$S/checks/frontdoor-hub/run.sh          # 64/1/0, 1 min 36 s
kind delete cluster --name eoapi-spike
# compose
docker compose -p eoapi-spike -f $S/compose.participant.yml start
$S/checks/verify/compose.sh             # build apis auth browser-apps notebooks footprint
$S/checks/auth/run.sh                   # re-run after the V2 fix
```

## Raw output (trimmed)

```
# verify/compose.sh summary (host clock; the apis span includes a ~4 min host sleep)
build        07:11:23..07:11:28 PASS=44 FAIL=2 BLOCKED=0
apis         07:11:28..07:16:12 PASS=61 FAIL=4 BLOCKED=0
auth         07:16:12..07:16:19 PASS=57 FAIL=3 BLOCKED=0   <- false PASS (V2)
browser-apps 07:16:19..07:19:01 PASS=31 FAIL=2 BLOCKED=0
notebooks    07:19:01..07:21:21 PASS=135 FAIL=2 BLOCKED=4
footprint    07:21:21..07:25:04 PASS=31 FAIL=0 BLOCKED=0
auth (re-run, fixed check)      PASS=56 FAIL=4 BLOCKED=0

# build
FAIL arch.lab —
FAIL proxy.token-not-echoed — Lab token appears in response body of: ['stac/collections']
# V2 evidence: Lab log, auth's laptop gate requests (host.docker.internal = 172.18.0.1) at VM time 07:12:03
2026-10-02T07:12:03.871874637Z ... 302 GET /manager/ (@172.18.0.1)
2026-10-02T07:12:03.916631679Z ... 403 GET /terminals/websocket/1 (@172.18.0.1)
# auth re-run
FAIL laptop.stac.lab-token-in-error-log — stac-fastapi logged 3 x 'asyncpg RaiseError: Could not find item using token: <LAB_TOKEN>' during this run
PASS offpod.tcp-reachable — only the Lab answers
PASS cookie.token-login.xfp-https — flags=['Expires=+2.0d', 'HttpOnly', 'Path=/', 'SameSite=Lax', 'Secure']
# browser-apps
FAIL iframe.raster-world-tile-latency — direct to titiler-pgstac (MOSAIC_CONCURRENCY=1, 100 glad items): 0/0/0 -> 200 in 112.3 s; 0/0/0 -> 200 in 0.4 s; 3/1/2 -> 200 in 1.3 s (first request was cold)
FAIL manager.delete — clicked Options > Delete: DELETE requests sent=0, collection still there=True
PASS manager.create-as-deployed — scope='openid profile email offline_access stac:write'; POST /stac/collections/ -> 307 ... Location: http://localhost:18888/stac/collections
# footprint
PASS sampler.cadence — 97 docker-stats rounds x 9 containers, median interval 2.03 s, max 2.57 s
PASS plan.participant-under-3.5GiB-local-no-limit — pod total at its busiest moment as measured = 3.14 GiB
PASS plan.participant-under-3.5GiB-k8s-estimate — pod total at its busiest moment = 2.80 GiB (ESTIMATE)
# frontdoor-own (fresh install)
PASS u01.lab.docs-current — sha256 of docs/*.ipynb + docs/*.py: pod 30dd11287eb8, worktree 30dd11287eb8
PASS netpol.control.without-policy — policy deleted: u02 Lab → u01 pod: 5432=closed ... 8086=closed 18888=open
FAIL lab.files-survive-container-restart — wrote docs/participant-work.txt, killed the Lab (restartCount=1): file gone
# verify/own.sh
PASS cross.u01-cookie-replayed-on-u02 — u01 cookie on lab-u01 /api/status → 200; replayed on lab-u02: 403 / /stac 302 (both cookie names)
PASS upgrade.image-bump-replaces-every-pod — render with one shared image tag bumped: 2 of 2 participant pod templates change
PASS persist.setup — u01 POST collection spike-verify-persist → 201; GET → 200; PUT ~/verify-work.txt → 201
FAIL persist.pod-replacement — after the u01 pod was replaced: collection spike-verify-persist → 404; ~/verify-work.txt → 404
# frontdoor-hub
FAIL u01.laptop.stac-with-hub-token — 'Authorization: token' → 401, 'Bearer' → 401, ?token= → 302
PASS manager.create — POST chain ['307 /user/u01/stac/collections/ → .../user/u01/stac/collections', '201 /user/u01/stac/collections']
```

Full raw logs (gitignored): `spike/evidence/.verify-*.log`.

## State left behind

- The compose stack `eoapi-spike` is **running**. Open http://localhost:18888 with `LAB_PASSWORD` from `spike/.env`.
- The kind cluster `eoapi-spike` is **deleted**. `spike/.kind-kubeconfig` is now stale and gitignored.
