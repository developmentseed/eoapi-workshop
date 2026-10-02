# Own chart, one pod per participant, on local kind

*2026-10-01, re-run after the fix stage · kind v0.32.0 (node v1.36.1, kindnet `kindnetd:v20260528-9350166c`), helm v4.1.4, ingress-nginx controller-v1.15.1 (the version on "labs") · Docker Desktop on an arm64 Mac · branch `spike/per-user-stacks` · reproducible with `spike/checks/frontdoor-own/run.sh`*

Option 1 from the scoping plan as a minimal Helm chart, `spike/chart/`. Each participant gets one Deployment (the 9 containers of `compose.participant.yml`, Postgres as a native sidecar) and a Service for the Lab port only. The release adds one credentials Secret, one ConfigMap (chapter-7 filters and the stac-browser nginx template), one Ingress for all `lab-uNN` hosts, and one NetworkPolicy.

## Results

`checks/frontdoor-own/run.sh`, final run (run 3): **58 PASS, 1 FAIL, 0 BLOCKED**. The FAIL is a design finding (finding 1), not broken wiring. Runs 1 and 2 had 58 PASS, 0 FAIL; they ran before the restart check was added. Run 1 was against a **fresh `helm install`** (release uninstalled and namespace deleted first), not an upgrade of the earlier attempt's release.

- **The chart runs the same stack as compose.** `parity.py` compares every container of the rendered chart with `compose.participant.yml`: image, command line, env names, and non-secret env values, with the origin swapped (`http://lab-u01.spike.local:18080` ↔ `http://localhost:18888`). All 9 match.
  - **Control:** altering `--root-path /stac` and `TITILER_PGSTAC_API_ROOT_PATH` in the render gives exactly 2 FAIL lines.
  - So the fix stage's changes are in the chart: loopback binds for every service but the Lab, `--root-path /stac`, the stac-manager `stac:write` scope sed, stac-auth-proxy through uvicorn, the stac-browser loopback nginx template, and no `STAC_AUTH_PROXY_ENDPOINT`.
- **Login works per user through the ingress, and only the right credentials open each Lab.**
  - Anonymous requests to all six prefixes get 302 → `/login`, with no content leak.
  - u01's password on `lab-u02` → 401, then `/api/status` → 403. u01's token on `lab-u02` → 403; `/stac/?token=<u01 token>` → 302 to the login.
  - A `stac:write` JWT minted by u01's mock-oidc is refused by u02's stac-auth-proxy (401). Each pod's mock-oidc has its own signing key.
- **`/stac`, `/raster`, `/vector` work through each Lab, and the URLs they generate carry the participant's own origin**, e.g. `self=http://lab-u02.spike.local:18080/stac/` and tilejson tiles `http://lab-u01.spike.local:18080/raster/…`. jupyter-server-proxy passes the ingress `Host` through, so the `{origin}` values are the only per-user rewriting.
  - Both stacks serve the baked data: glad, 100 items; `features.ecoregions`, 2548 features.
  - Bearer writes through `/stac/`: 401 without a JWT, 201 with one, then DELETE 200.
  - mock-oidc's issuer is `http://lab-uNN.spike.local:18080/oidc`. `/browser/` and `/manager/` return 200.
- **kindnet in kind v0.32 enforces NetworkPolicy.** This is an A/B test, not an assumption:
  - **With the policy**, a socket probe from u02's Lab container (`kubectl exec … -c lab`, the participant's terminal) to u01's pod IP **times out on all 9 ports**: 5432, 8080–8086 and 18888.
  - **With the policy deleted**, `:18888` is **open**. The other 8 ports are now **refused** (`closed`), not open: since the fix stage they bind 127.0.0.1. The earlier attempt saw all 9 open here.
  - The `timeout` vs `refused` difference on the 8 backend ports, and `timeout` vs `open` on 18888, is the policy at work.
  - **Controls:** the same probe to u02's own `127.0.0.1` finds all 9 open, so the probe can see open ports. The ingress controller pod reaches u01 on `:18888` (HTTP 200) but not on `:8084` (no connection).
  - **Labs runs Calico, not kindnet.** This result does not prove enforcement there; re-run the same probe on the cluster.
- **Two layers now isolate the backends:** the NetworkPolicy, and the loopback binds. Either alone keeps another participant off ports 5432/8080–8086 (`loopback.without-policy`).
- **`helm upgrade` keeps passwords and restarts nobody.**
  - The Secret data hash is identical across every upgrade in the three runs (`0c74acf52bbc`, revisions 1 → 13).
  - Participant pod UIDs are unchanged across an upgrade.
  - Adding u03 with `--set` and removing it again did not restart u01 or u02, and u01's password is unchanged.
- **`helm template` renders only namespaced kinds:** ConfigMap, Deployment, Ingress, NetworkPolicy, Secret, Service, checked against `kubectl api-resources --namespaced=false`.
- **The native sidecar works.** `database` is an initContainer with `restartPolicy: Always` and a `pg_isready` startupProbe. The other 8 containers start 4–8 s after it (pod `Initialized` at the startupProbe pass).
- **Cold start is 6–15 s from scheduled to Ready**, images preloaded on the node. A fresh `helm install --wait` of two participants returned in 15.6 s.
  - The spread is the Lab's `readinessProbe` (default 10 s period), not the stack: in run 1 both pods had every container started 5 s after scheduling, yet u01 went Ready at 15 s and u02 at 6 s.
- **Requests and limits are the footprint values** on all 9 containers: CPU and memory requests, a memory limit, no CPU limit. Per pod: **580m CPU and 2816 Mi memory requested**.
  - database 60m/560Mi/960Mi, lab 250m/1Gi/3Gi, stac-fastapi 30m/176Mi/320Mi, mock-oidc 10m/80Mi/128Mi, stac-auth-proxy 50m/224Mi/384Mi, titiler-pgstac 140m/464Mi/768Mi, tipg 20m/176Mi/320Mi, stac-browser 10m/32Mi/128Mi, stac-manager 10m/80Mi/192Mi (request CPU/request memory/limit memory).
- **Idle memory is 707 / 703 MiB per pod** (`crictl stats` working set), the same as compose.
  - database 121, titiler 136, stac-auth-proxy 136, lab 92/88, tipg 65, stac-fastapi 63/64, mock-oidc 49, stac-manager 31, stac-browser 14.
- **The Lab's notebooks are the current `docs/`** (`lab.docs-current`: the sha256 of `docs/*.ipynb` and `docs/*.py` in the pod matches the worktree). See finding 2: before this run they were not.
- `automountServiceAccountToken: false`: there is no `/var/run/secrets/kubernetes.io` in the Lab.
- A 2 MB upload through the ingress (`PUT /api/contents`) returns 201. `proxy-body-size: 64m` is set in values. I did not A/B-test this against nginx's 1m default.
- The host port works: `http://lab-u01.spike.local:18080/login` through the host's `127.0.0.1:18080` → 200.

## What changed since the earlier attempt

The earlier attempt (commits 1f1c4ba, b837872, a09d79b, reporting 45/0/0) ran before the fix stage. The fix stage then updated the chart and `run.sh` and re-ran it (46/0/0), but did not rewrite this file. This run re-checked everything from a fresh install.

- **Chart:** the fix stage's changes (loopback binds, `--root-path /stac`, the stac-manager scope sed, stac-auth-proxy via uvicorn, the stac-browser nginx template in the ConfigMap, footprint requests, no `STAC_AUTH_PROXY_ENDPOINT`) were already in `spike/chart/`. `parity.py` now proves the chart matches compose; nothing in the chart needed changing in this run.
- **Lab image on kind was stale; now rebuilt.** The `eoapi-spike-lab-base` image was built at 15:26, before the notebook fixes (caac1d9). The chart's Lab has no `docs` mount, so the fix stage's 46/0/0 kind run served the **pre-fix notebooks**. Its routing and isolation results still hold, but its Lab did not carry the fixed notebooks. I rebuilt the base and Lab images, loaded them with `kind load`, and added `lab.docs-current`.
- **Without the policy, only `:18888` answers.** The earlier attempt saw all 9 ports open.
- **Requests** are now the footprint values. The earlier attempt had lab 100m, titiler 120m/432Mi, stac-auth-proxy 40m, stac-fastapi and tipg 10m.
- **Checks:**
  - New: `parity.*` and its drift control, `lab.docs-current`, `lab.files-survive-container-restart`.
  - The always-PASS `pod.requests`, `pod.arch` and `pod.cold-start` lines are now real checks: `pod.resources` needs all 9 containers sized, `pod.arch` needs browser/manager x86_64 and stac-fastapi aarch64, `pod.cold-start` needs Ready within 120 s.
  - The earlier finding that a bare `helm upgrade` reuses `--set` was re-verified by hand in this run (finding 3).
- **Lines owned:** 351 → 370. Most of it is `stac-browser/default.conf.template` (15), which the chart now mounts and `loc.py` did not count before.

## Findings

1. **A Lab container restart loses the participant's work** (`lab.files-survive-container-restart`, FAIL). `/home/jovyan` is the container's writable layer, with no volume. I wrote `docs/participant-work.txt` and killed the Lab process; the container restarted (restartCount 1) and the file was gone.
   - The Lab is the container most likely to restart: it has the 3 Gi limit that a large notebook can hit, and an OOM kill restarts only that container.
   - Compose doesn't have this problem, because it bind-mounts `../docs`.
   - **Options (not applied, your call):** an `emptyDir` for the home survives container restarts but not pod deletion, at about 8 lines: a volume, a mount, and an init step copying the image's home into it. A PVC per participant survives both, but needs a StorageClass on labs. PR #35 / z2jh uses a PVC per user.
2. **The notebooks come from the Lab image, and a stale image is silent.** Rebuild `eoapi-spike-lab-base` and the Lab image whenever `docs/` changes. Run 1 caught nothing before `lab.docs-current` existed; the fix stage's kind run used the old notebooks.
   - On labs, the image also needs a versioned tag. With `:latest` and `IfNotPresent`, a node that already has `:latest` keeps the old notebooks.
3. **`helm upgrade` with no value flags silently reuses the previous `--set` values.** This was re-verified here: after `--set participants={u01,u02,u03}` (revision 11), a bare `helm upgrade spike chart` (revision 12) kept `USER-SUPPLIED VALUES: participants: [u01, u02, u03]`, and `spike-u03` stayed.
   - **Deploy glue must always pass `--reset-values`, or always `-f` the participant list.** Otherwise a "remove a participant" run is a no-op that reports success. `run.sh` uses `--reset-values`.
4. **Removing a participant deletes their Secret keys.** After removing u03, the Secret holds only the 6 u01/u02 keys. Re-adding them generates a **new** password and token, and their DB (emptyDir) is gone with the pod. Fine for a one-day workshop; put it in the runbook.
5. **The NetworkPolicy is ingress-only.** Participant pods can't reach each other. A Lab terminal can still reach anything else in the cluster that has no policy of its own: other namespaces, node IPs, and the API server (anonymously, since no token is mounted).
   - z2jh's default singleuser policy also restricts egress to private ranges.
   - If labs' other tenants matter, add an egress rule (about 10 lines): DNS, plus 0.0.0.0/0 except the cluster/private CIDRs. Not done here.
6. **The kubelet's readinessProbe (httpGet `/login` on the pod IP) passes under the policy**, because kindnet lets node-originated traffic through. Calico does too by default, but this is unverified on labs.
   - The probe's default 10 s period adds up to 10 s to Ready. `periodSeconds: 2` would trim it; not changed.
7. **The amd64-only images run emulated on the arm64 kind node.** `uname -m` in stac-browser and stac-manager returns `x86_64`.
   - `kind load docker-image` fails for those multi-platform images with Docker's containerd image store, so they are imported with `docker save --platform X | ctr import --platform X` (Reproduce). The single-platform local images (`eoapi-spike-lab`, `eoapi-spike-db`) load with plain `kind load`.
   - This is a laptop-only problem: labs nodes are amd64 and pull directly.
8. **Laptop artefact: the kind node's clock was about 15 minutes behind the host during the fresh install.** helm recorded 21:22:31Z; the API server stamped the objects 21:07:19Z. The clock was back in sync by 21:26Z. Durations inside one pod's startup are unaffected; the absolute timestamps in run 1 and run 3 are node time.

## Lines we own for this variant

`python3 spike/checks/frontdoor-own/loc.py` (non-blank, non-comment; Helm `{{/* */}}` blocks and Python docstrings count as comments):

| lines | file | group |
|---:|---|---|
| 4 | `spike/chart/Chart.yaml` | chart |
| 153 | `spike/chart/values.yaml` | chart |
| 49 | `spike/chart/templates/participant.yaml` | chart |
| 57 | `spike/chart/templates/shared.yaml` | chart |
| 15 | `spike/stac-browser/default.conf.template` (the chart mounts it via a `chart/files/` symlink) | chart |
| 7 | `spike/lab/Dockerfile` | lab image + config |
| 28 | `spike/lab/jupyter_server_config.py` | lab image + config |
| 22 | `spike/db/Dockerfile` | db image |
| 18 | `spike/db/glad_to_sql.py` | db image |
| 7 | `spike/db/initdb/zz_00_tuning.sh` | db image |
| 10 | `spike/kind/cluster.yaml` | deploy glue (local kind only) |
| **370** | **total** | |

- **Not counted:**
  - `chart/files/workshop_filters.py`, a symlink to `docs/workshop_filters.py`. It is shared with compose and also exists in PR #35's chart.
  - The checks.
  - `docs/workshop_setup.py`, the notebook contract every variant needs.
- **For comparison:**
  - PR #35's chart is about 930 non-comment lines (skeptic review); its `values.yaml` alone is 267.
  - `compose.participant.yml` is 169.
- **`values.yaml` duplicates compose (153 vs 169 lines).** The same env lives in two files, which is this variant's main maintenance cost. `parity.py` now turns any drift into a FAIL. Removing the duplication, by generating one file from the other or by dropping the per-participant compose file, is not done.
- **Still missing for labs, estimated:**
  - Deploy glue with `--reset-values` and a `urls` printer that reads the Secret: about 15 lines.
  - TLS: values only (`tlsSecret`, plus the cert-manager annotation).
  - An image pre-puller DaemonSet: about 25 lines.
  - Home persistence (finding 1): about 8 lines for an emptyDir, more for a PVC.
  - Optionally the egress rule (finding 5): about 10 lines.
  - That puts the variant at roughly 430 lines.

## Reproduce

All kubectl/helm commands carry the kind kubeconfig and context explicitly. Run from the worktree root.

```sh
S=spike; KC=$S/.kind-kubeconfig
docker compose -p eoapi-spike -f $S/compose.participant.yml stop          # free memory; volumes kept
kind create cluster --name eoapi-spike --config $S/kind/cluster.yaml --kubeconfig $KC   # or: docker start eoapi-spike-control-plane
kubectl --kubeconfig $KC --context kind-eoapi-spike apply -f \
  https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.15.1/deploy/static/provider/kind/deploy.yaml
# local images: rebuild the base whenever docs/ changes (the chart's Lab serves the baked notebooks)
docker build -f Dockerfile.local -t eoapi-spike-lab-base . && docker build -t eoapi-spike-lab $S/lab
kind load docker-image --name eoapi-spike eoapi-spike-lab:latest eoapi-spike-db:latest
# public images, per platform (kind load fails on multi-platform indexes with the containerd store)
docker save --platform linux/arm64 ghcr.io/stac-utils/stac-fastapi-pgstac:7.0.0 ghcr.io/stac-utils/titiler-pgstac:3.2.0 \
  ghcr.io/developmentseed/tipg:1.6.1 ghcr.io/developmentseed/stac-auth-proxy:v1.2.0 \
  | docker exec -i eoapi-spike-control-plane ctr -n k8s.io images import --platform linux/arm64 --digests -
docker save --platform linux/amd64 ghcr.io/radiantearth/stac-browser:5.1.0 ghcr.io/developmentseed/stac-manager:1.0.3 \
  | docker exec -i eoapi-spike-control-plane ctr -n k8s.io images import --platform linux/amd64 --digests -
# mock-oidc (pinned by digest) is pulled by the node itself
helm --kubeconfig $KC --kube-context kind-eoapi-spike install spike $S/chart -n spike-own --create-namespace --wait
$S/checks/frontdoor-own/run.sh
python3 $S/checks/frontdoor-own/loc.py
```

This run started from the fix stage's cluster (node running, release at revision 18), then:

```sh
helm --kubeconfig $KC --kube-context kind-eoapi-spike -n spike-own uninstall spike --wait
kubectl --kubeconfig $KC --context kind-eoapi-spike delete namespace spike-own --wait
# rebuild + kind load the Lab image as above, then helm install (15.6 s with --wait) and run.sh three times
```

Credentials for a browser on this Mac: open `http://lab-u01.spike.local:18080` (add `127.0.0.1 lab-u01.spike.local lab-u02.spike.local` to `/etc/hosts`). The password is:

```sh
kubectl --kubeconfig spike/.kind-kubeconfig --context kind-eoapi-spike -n spike-own \
  get secret spike-credentials -o jsonpath='{.data.u01-password}' | base64 -d
```

**State left behind:** the kind cluster is running with release `spike` at revision 13 (u01 and u02, NetworkPolicy present, both pods 9/9 with 0 restarts). The compose stack `eoapi-spike` is stopped, with its volumes kept. Teardown, not done: `kind delete cluster --name eoapi-spike`.

## How the checks look at the system

- **`run.sh`, host side:**
  - `helm template` kinds against `api-resources`.
  - `parity.py` on the rendered chart, plus the drift control.
  - Pod status JSON: ready count, restarts, the sidecar spec, `startedAt`, resources, `automountServiceAccountToken`, and Scheduled → Ready.
  - `uname -m` per container.
  - The docs hash: `sha256sum` in the Lab against `shasum -a 256` in the worktree.
  - Credentials are read from the Secret into env vars and never printed.
  - The NetworkPolicy probes and the A/B test: `kubectl exec` into u02's `lab` container runs a Python socket connect with a 3 s timeout. The ingress-side control runs `curl` from the ingress-nginx pod.
  - The upgrade checks.
  - The host port check: a throwaway container with `--add-host lab-u01.spike.local:host-gateway` fetches `:18080/login`.
  - Last, the Lab restart check, followed by a rollout so u02 ends with a clean pod.
- **`ingress.py`** runs in a throwaway `eoapi-spike-lab` container on the `kind` docker network. Every request goes to `http://eoapi-spike-control-plane` (node port 80) with `Host: lab-uNN.spike.local:18080`, the exact Host a browser sends through the published `127.0.0.1:18080`. Every printed line is redacted: no password, token or JWT.
- **Mutations, all on the kind cluster:**
  - The NetworkPolicy is deleted for the A/B test and restored by the upgrade check.
  - u03 is added and removed.
  - u02's Lab is killed once, then u02 gets a rollout restart.
  - Test collections `spike-frontdoor-u01` and `spike-frontdoor-u02` are created then deleted, and `spike-frontdoor-cross` is refused.
  - `spike-upload.txt` is created then deleted.

## Not tested

- **No real browser.** STAC Browser and stac-manager OIDC PKCE logins and `map.html` were not exercised through kind; `evidence/browser-apps.md` covers them on compose.
- **No TLS.** `ingress.tlsSecret`, `trust_xheaders`, the `Secure` cookie and https-generated links are untested: there is no cert-manager on kind, and every URL here is `http://…:18080`.
- **No tile fetches from S3.** Only the tilejson was fetched.
- **No notebook runs inside the kind pods.** `lab.docs-current` proves the notebooks are the fixed ones, and `evidence/notebooks.md` runs them on compose with the same images and env, which `parity.py` checks.
- **Calico enforcement on labs.** Only kindnet was tested.
- **Memory or CPU under load on k8s.** Only the idle working set was read; footprint.md stays the source for load figures.
- **Websocket kernel sessions through the ingress.** `proxy-read-timeout: 3600` is set but not exercised.
- **Eviction behaviour when limits overcommit the node.**

## Raw output (run 3, the final run)

```
PASS render.no-cluster-scoped — kinds: ConfigMap Deployment Ingress NetworkPolicy Secret Service ; cluster-scoped among them: none
PASS parity.database — image, command and 6 env vars match compose (origin swapped)
PASS parity.lab — image, command and 18 env vars match compose (origin swapped)
PASS parity.mock-oidc — image, command and 4 env vars match compose (origin swapped)
PASS parity.stac-auth-proxy — image, command and 13 env vars match compose (origin swapped)
PASS parity.stac-browser — image, command and 3 env vars match compose (origin swapped)
PASS parity.stac-fastapi — image, command and 9 env vars match compose (origin swapped)
PASS parity.stac-manager — image, command and 7 env vars match compose (origin swapped)
PASS parity.tipg — image, command and 10 env vars match compose (origin swapped)
PASS parity.titiler-pgstac — image, command and 22 env vars match compose (origin swapped)
PASS parity.control.drift-detected — render with --root-path and TITILER root path altered → 2 FAIL lines (want 2)
PASS u01.pod.ready — 9/9 containers ready, 0 restarts
PASS u01.pod.db-native-sidecar — database restartPolicy=Always startupProbe=pg_isready; db started 2026-10-01T21:07:19Z, lab 2026-10-01T21:07:23Z
PASS u01.pod.no-sa-token — automountServiceAccountToken=false; /var/run/secrets/kubernetes.io: ls: cannot access '/var/run/secrets/kubernetes.io': No such file or directory
PASS u01.pod.resources — 9/9 with cpu+memory requests, a memory limit, no cpu limit (request/request/limit): database=60m/560Mi/960Mi lab=250m/1Gi/3Gi stac-fastapi=30m/176Mi/320Mi mock-oidc=10m/80Mi/128Mi stac-auth-proxy=50m/224Mi/384Mi titiler-pgstac=140m/464Mi/768Mi tipg=20m/176Mi/320Mi stac-browser=10m/32Mi/128Mi stac-manager=10m/80Mi/192Mi
PASS u01.pod.arch — stac-browser=x86_64 stac-manager=x86_64 stac-fastapi=aarch64 (browser/manager emulated on the arm64 node)
PASS u01.pod.cold-start — PodScheduled → Ready in 15s (images preloaded on the node)
PASS u01.lab.docs-current — sha256 of docs/*.ipynb + docs/*.py: pod 30dd11287eb8, worktree 30dd11287eb8
PASS u02.pod.ready — 9/9 containers ready, 0 restarts
PASS u02.pod.db-native-sidecar — database restartPolicy=Always startupProbe=pg_isready; db started 2026-10-01T21:33:58Z, lab 2026-10-01T21:34:06Z
PASS u02.pod.no-sa-token — automountServiceAccountToken=false; /var/run/secrets/kubernetes.io: ls: cannot access '/var/run/secrets/kubernetes.io': No such file or directory
PASS u02.pod.resources — 9/9 with cpu+memory requests, a memory limit, no cpu limit (request/request/limit): (same as u01)
PASS u02.pod.arch — stac-browser=x86_64 stac-manager=x86_64 stac-fastapi=aarch64 (browser/manager emulated on the arm64 node)
PASS u02.pod.cold-start — PodScheduled → Ready in 11s (images preloaded on the node)
PASS u02.lab.docs-current — sha256 of docs/*.ipynb + docs/*.py: pod 30dd11287eb8, worktree 30dd11287eb8
PASS secret.per-user — 6 keys; Lab password 12 chars; password, token and DB password differ between u01 and u02
PASS netpol.control.own-localhost — u02 → its own 127.0.0.1: 5432=open 8080=open 8081=open 8082=open 8083=open 8084=open 8085=open 8086=open 18888=open
PASS netpol.u02-to-u01-blocked — u02 Lab → u01 pod 10.244.0.12: 5432=timeout 8080=timeout 8081=timeout 8082=timeout 8083=timeout 8084=timeout 8085=timeout 8086=timeout 18888=timeout
PASS netpol.ingress-to-lab-only — ingress-nginx pod → u01 :18888 HTTP 200; → :8084 HTTP 000 (000 = no connection)
PASS netpol.control.without-policy — policy deleted: u02 Lab → u01 pod: 5432=closed 8080=closed 8081=closed 8082=closed 8083=closed 8084=closed 8085=closed 8086=closed 18888=open
PASS loopback.without-policy — policy deleted: only :18888 open on u01's pod IP
PASS upgrade.keeps-credentials — revision 8; Secret data sha256 0c74acf52bbc → 0c74acf52bbc
PASS upgrade.no-restart — participant pod UIDs unchanged across the upgrade
PASS netpol.restored-by-upgrade — after upgrade: u02 Lab → u01 pod: 5432=timeout 8080=timeout 8081=timeout 8082=timeout 8083=timeout 8084=timeout 8085=timeout 8086=timeout 18888=timeout
PASS upgrade.add-remove-participant — u03 added (lab ready=true) and removed (deployment gone=1); u01/u02 pod UIDs unchanged; u01 password unchanged
PASS host.port-18080 — http://lab-u01.spike.local:18080/login via the host's 127.0.0.1:18080 → HTTP 200
PASS u01.anonymous-blocked — 6 prefixes without login → 302 /login or 403; leaks: none
PASS u01.login.wrong-password — POST /login wrong password → 401 (no redirect)
PASS u01.login.password — POST /login → 302 /; /api/status with cookie → 200
PASS u01.login.token — /api/status?token=<own token> → 200
PASS u01.stac — self=http://lab-u01.spike.local:18080/stac/; collections=['glad-global-forest-change-1.11']; glad items=100
PASS u01.raster — healthz 200; tilejson 200 tiles[0]=http://lab-u01.spike.local:18080/raster/collections/glad-global-forest-change-1.11/items/hansen-gfc-2023-v1.11-80N-180W/tiles/WebMercatorQuad/{z}/{x}/{y}?assets=gain&tilesize=512
PASS u01.vector — collections=['features.ecoregions']; ecoregions numberMatched=2548
PASS u01.oidc-browser-manager — issuer=http://lab-u01.spike.local:18080/oidc; /browser/ 200; /manager/ 200
PASS u01.stac.bearer-write — POST without JWT 401; with own JWT 201; DELETE 200
PASS u02.… — the same 8 checks as u01, all PASS, with lab-u02 URLs
PASS u01.lab.upload-2mb — PUT 2 MB via /api/contents → 201; DELETE 204
PASS cross.u01-password-on-u02 — POST lab-u02/login with u01's password → 401; /api/status → 403
PASS cross.u01-token-on-u02 — lab-u02 /api/status?token=<u01 token> → 403; /stac/?token=<u01 token> → 302
PASS cross.u01-jwt-on-u02-stac — u01-minted stac:write JWT → POST lab-u02/stac/collections → 401
FAIL lab.files-survive-container-restart — wrote docs/participant-work.txt, killed the Lab (restartCount=1): file gone (the Lab's home is the container's writable layer; no volume)
```

Full logs of the three runs (gitignored): `spike/evidence/.frontdoor-own-run{1,2,3}.log`.
