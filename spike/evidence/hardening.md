# Hardening: persistence, egress, pinned images, deploy.sh

*2026-10-02 · Docker Desktop on an arm64 Mac · kind v0.32.0 (node v1.36.1, kindnet), helm v4.1.4, ingress-nginx controller-v1.15.1 · branch `spike/per-user-stacks` · every number below comes from a run made today, after these changes*

## What changed

- **Persistence.** Each participant has a PVC for the DB and one for `/home/jovyan/work`.
  - `PGDATA` sits one level down (`.../data/pgdata`), because a fresh block volume holds `lost+found` and initdb refuses a non-empty directory. Compose sets the same path.
  - The pod has `fsGroup: 1000` (jovyan) so the Lab can write to `work/`.
  - The PVCs belong to the release: removing a participant, or `helm uninstall`, deletes them.
- **Egress.** The NetworkPolicy also limits what leaves a participant pod.
  - Allowed: DNS to kube-dns, and TCP 80/443 to `0.0.0.0/0` minus the private, CGNAT and link-local ranges.
  - `egressExcept` closes more, for example a public API server address.
- **Images.**
  - The chart pulls `<registry>/eoapi-workshop-{lab,db}:<image.tag>`.
  - `.github/workflows/publish-participant-images.yml` builds both images on amd64 runners and pushes them as `sha-<commit>`. Pull requests only build.
  - On kind the local builds are tagged `:local` and loaded with `kind load`.
- **Node pool.** `nodeSelector`/`tolerations` pin participant pods to the workshop pool. `prepull: true` adds a DaemonSet whose init containers pull every image onto each pool node; every image has `sh`, which the init containers run.
- **`deploy.sh`.**
  - `up` takes the context, namespace, image tag and the whole participant list every time, and uses `--reset-values`.
  - `creds` prints the credentials as CSV.
  - `down` needs `CONFIRM=<namespace>` and never deletes the namespace.

## Results

| Topic | Before (`verify.md`) | Now | Remaining FAILs |
|---|---|---|---|
| frontdoor-own (kind) | 58 / 1 / 0 | **61 / 0 / 0** | none. Was 1 FAIL: Lab files lost on a container restart. 2 new egress checks |
| verify/own.sh (kind) | 3 / 1 / 0 | **4 / 0 / 0** | none. `persist.pod-replacement` FAILed before |
| build (compose) | 44 / 2 / 0 | **45 / 1 / 0** | `proxy.token-not-echoed`, the `?token=` design limit |
| apis (compose) | 61 / 4 / 0 | **61 / 4 / 0** | `?token=` limits and upstream stac-auth-proxy encoding, as before |
| auth (compose) | 56 / 4 / 0 | **56 / 4 / 0** | `?token=` limits, as before |
| browser-apps (compose) | 31 / 2 / 0 | **31 / 2 / 0** | the cold glad world tile (112.7 s on a fresh stack, V3) and stac-manager's Delete (upstream), as before |
| notebooks (compose, `POINTS=0`) | 135 / 2 / 4 | **133 / 2 / 4** | the two stac-auth-proxy encoding FAILs, as before; 2 fewer PASS because the 100 Earth Search counts were skipped |

Notebook 00 executes with 0 errored cells, and its links cell answers 200 through the Lab.

### Egress (kind, from u01's Lab terminal)

```
PASS netpol.egress — u01 Lab → api=timeout other-ns=timeout node=timeout earth-search=open s3=open
PASS netpol.control.egress-without-policy — policy deleted: u01 Lab → api=open other-ns=open node=open earth-search=open s3=open
```

The probes are `kubernetes.default.svc:443`, `ingress-nginx-controller.ingress-nginx.svc:80`, the node IP on `:10250`, and `earth-search.aws.element84.com:443` and `s3.us-west-2.amazonaws.com:443`. The control proves that the policy is what closes the first three.

### Persistence (kind)

```
PASS lab.files-survive-container-restart — wrote work/participant-work.txt, killed the Lab (restartCount=1): file kept
PASS persist.setup — u01 POST collection spike-verify-persist → 201; GET → 200; PUT ~/work/verify-work.txt → 201
PASS persist.pod-replacement — after the u01 pod was replaced: collection spike-verify-persist → 200; ~/work/verify-work.txt → 200
```

### deploy.sh (kind, namespace `spike-deploy`, prepull on)

- `up latest u01` → refused: "pin the sha- tag, not latest".
- `up local d01 d02` → both stacks 9/9 and the prepull pod 1/1 Running in 28 s.
- `creds` → `participant,url,password,token`, one row per participant: 12-char password, 48-char token.
- `up local d01`, run without `REMOVE=1` → exit 1: "this would delete the stack, data and credentials of: d02". With `REMOVE=1`:
  - d02's Deployment and PVCs are gone;
  - d01's pod UID is unchanged.
- `down` → exit 2 without `CONFIRM`, and exit 2 with the wrong namespace. With `CONFIRM=spike-deploy`:
  - no resources are left in the namespace;
  - the namespace is still Active;
  - release `spike` in `spike-own` is untouched.

## Not tested here (the rehearsal on labs)

- **`fsGroup` on Cinder.** kind's local-path volumes are hostPath, where the kubelet does not apply fsGroup. PR #35's chart uses the same `fsGroup: 1000` for its Lab PVCs on labs.
- **Calico enforcing the egress rules.** kindnet does here.
- **CoreDNS labels on OVH.** If they are not `k8s-app: kube-dns` in `kube-system`, DNS breaks.
- **The API server address on labs.** If its endpoint is public, add it to `egressExcept`.
- **The amd64 build itself.** The workflow's first run is on the PR.
- **GHCR package visibility.** A private package needs a pull secret on the namespace's default ServiceAccount.

## Reproduce

From the worktree root, with the compose stack and the kind cluster as in `spike/README.md`:

```sh
for i in lab db; do docker tag eoapi-spike-$i ghcr.io/developmentseed/eoapi-workshop-$i:local; done
kind load docker-image --name eoapi-spike ghcr.io/developmentseed/eoapi-workshop-{lab,db}:local
kubectl --kubeconfig spike/.kind-kubeconfig --context kind-eoapi-spike create namespace spike-own
KUBECONFIG=spike/.kind-kubeconfig RELEASE=spike spike/deploy.sh kind-eoapi-spike spike-own up local u01 u02
spike/checks/frontdoor-own/run.sh; spike/checks/verify/own.sh
for t in build apis auth browser-apps; do spike/checks/$t/run.sh; done
POINTS=0 spike/checks/notebooks/run.sh
```
