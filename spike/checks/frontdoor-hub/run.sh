#!/usr/bin/env bash
# z2jh front door on the local kind cluster (release hub, namespace spike-hub,
# chart jupyterhub 4.4.2). Prereq: spike/hub/deploy.sh has run.
# Prints one line per check: PASS|FAIL|BLOCKED <name> — <detail>. Always exits 0.
# Never prints a password, token or JWT.
#
# Mutates the local kind cluster only: deletes the singleuser NetworkPolicy for an
# A/B control, then `helm upgrade` (same values) puts it back.
set -uo pipefail
cd "$(dirname "$0")"
HERE=$PWD
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT  # DB passwords, compared then removed
SPIKE=$(cd ../.. && pwd)
KC="$SPIKE/.kind-kubeconfig"
K=(kubectl --kubeconfig "$KC" --context kind-eoapi-spike -n spike-hub)
CHART=(jupyterhub --repo https://hub.jupyter.org/helm-chart/ --version 4.4.2)
FILES=(--set-file "singleuser.extraFiles.workshop_filters.stringData=$SPIKE/../docs/workshop_filters.py"
       --set-file "singleuser.extraFiles.stac_browser_conf.stringData=$SPIKE/stac-browser/default.conf.template")
say() { echo "$1 $2 — $3"; }
ok() { if eval "$1"; then say PASS "$2" "$3"; else say FAIL "$2" "$3"; fi; }
pod() { echo "jupyter-$1"; }  # KubeSpawner's default pod name

if ! "${K[@]}" get deploy hub >/dev/null 2>&1; then
  say BLOCKED cluster "release hub not found in spike-hub on kind-eoapi-spike"; exit 0
fi

# ---- render: what is left cluster-scoped ----
cluster=$(kubectl --kubeconfig "$KC" --context kind-eoapi-spike api-resources --namespaced=false --no-headers | awk '{print $NF}' | sort -u)
scoped() { awk '/^kind:/{print $2}' | sort -u | while read -r k; do grep -qx "$k" <<<"$cluster" && echo "$k"; done | tr '\n' ' '; }
ours=$(helm template hub "${CHART[@]}" -n spike-hub -f "$SPIKE/hub/values.yaml" "${FILES[@]}" 2>/dev/null)
kinds=$(awk '/^kind:/{print $2}' <<<"$ours" | sort -u | tr '\n' ' ')
hits=$(scoped <<<"$ours")
ok '[ -n "$kinds" ] && [ -z "$hits" ]' render.no-cluster-scoped "kinds: $kinds; cluster-scoped among them: ${hits:-none}"
def=$(helm template hub "${CHART[@]}" -n spike-hub 2>/dev/null | scoped)
prio=$(helm template hub "${CHART[@]}" -n spike-hub --set scheduling.podPriority.enabled=true 2>/dev/null | scoped)
ok '[ -n "$def" ]' render.control.defaults "chart defaults render cluster-scoped: ${def:-none}; with podPriority on: ${prio:-none} (values.yaml turns these off)"

# ---- hub pods ----
core=$("${K[@]}" get pods -o json | jq -r '[.items[] | select(.metadata.labels.component | IN("hub","proxy","continuous-image-puller")) | "\(.metadata.labels.component)=\(.status.containerStatuses | map(select(.ready)) | length)/\(.status.containerStatuses | length)"] | sort | join(" ")')
ok '[ "$core" = "continuous-image-puller=1/1 hub=1/1 proxy=1/1" ]' hub.core-pods "$core"
pv=$("${K[@]}" get pvc hub-db-dir -o jsonpath='{.status.phase} {.spec.storageClassName} {.status.capacity.storage}')
ok '[[ "$pv" == Bound* ]]' hub.db-pvc "hub sqlite on PVC hub-db-dir: $pv (needs a StorageClass on labs)"

# ---- participant pods (pre-spawned by deploy.sh through the REST API) ----
for u in u01 u02; do
  p=$("${K[@]}" get pod "$(pod $u)" -o json 2>/dev/null)
  if [ -z "$p" ]; then say FAIL "$u.pod.ready" "pod $(pod $u) not found (not spawned?)"; continue; fi
  ready=$(jq -r '[.status.containerStatuses[], .status.initContainerStatuses[]] | map(select(.ready)) | length' <<<"$p")
  restarts=$(jq -r '[.status.containerStatuses[], .status.initContainerStatuses[]] | map(.restartCount) | add' <<<"$p")
  ok '[ "$ready" = 9 ] && [ "$restarts" = 0 ]' "$u.pod.ready" "$ready/9 containers ready, $restarts restarts"
  side=$(jq -r '.spec.initContainers | map("\(.name):\(.restartPolicy // "-")") | join(" ")' <<<"$p")
  dbs=$(jq -r '.status.initContainerStatuses[] | select(.name=="database") | .state.running.startedAt' <<<"$p")
  labs=$(jq -r '.status.containerStatuses[] | select(.name=="notebook") | .state.running.startedAt' <<<"$p")
  ok '[ "$side" = "database:Always" ] && [[ "$labs" > "$dbs" ]]' "$u.pod.db-native-sidecar" "initContainers $side; db started $dbs, notebook $labs"
  sa=$(jq -r '.spec.automountServiceAccountToken' <<<"$p")
  mnt=$("${K[@]}" exec "$(pod $u)" -c notebook -- ls /var/run/secrets/kubernetes.io 2>&1 | head -1)
  ok '[ "$sa" = false ]' "$u.pod.no-sa-token" "automountServiceAccountToken=$sa; /var/run/secrets/kubernetes.io: $mnt"
  req=$(jq -r '[.spec.initContainers[], .spec.containers[]] | map("\(.name)=\(.resources.requests.cpu)/\(.resources.requests.memory)/\(.resources.limits.memory)") | join(" ")' <<<"$p")
  nres=$(jq -r '[.spec.initContainers[], .spec.containers[]] | map(select(.resources.requests.cpu and .resources.requests.memory and .resources.limits.memory)) | length' <<<"$p")
  ok '[ "$nres" = 9 ]' "$u.pod.resources" "$nres/9 with cpu+memory requests and a memory limit: $req"
  secs=$(jq -r '.status.conditions | map({(.type): (.lastTransitionTime|fromdateiso8601)}) | add | .Ready - .PodScheduled' <<<"$p")
  ok '[ "$secs" -le 120 ]' "$u.pod.cold-start" "PodScheduled → Ready in ${secs}s (images preloaded on the node)"
  # Every backend root path carries this user's prefix ({username} expanded by KubeSpawner).
  roots=$(jq -r '[.spec.containers[] | (.env // [])[] | select(.name | IN("ROOT_PATH","TITILER_PGSTAC_API_ROOT_PATH","TIPG_ROOT_PATH","ISSUER","SB_pathPrefix","PUBLIC_URL")) | .value] | join(" ")' <<<"$p")
  rp=$(jq -r '.spec.containers[] | select(.name=="stac-fastapi") | .args | join(" ")' <<<"$p" | grep -o -- '--root-path [^ ]*')
  n=$(tr ' ' '\n' <<<"$roots $rp" | grep -c "/user/$u/")
  ok '[ "$n" = 7 ] && ! grep -q "{username}" <<<"$roots"' "$u.pod.prefix-expanded" "$roots $rp"
  pw=$(jq -r '[.spec.initContainers[], .spec.containers[]] | map((.env // [])[] | select(.name | IN("PGPASSWORD","POSTGRES_PASSWORD","POSTGRES_PASS")) | .value) | unique | length' <<<"$p")
  ph=$(jq -r '[.spec.initContainers[], .spec.containers[]] | map((.env // [])[] | select(.value=="generated-per-pod")) | length' <<<"$p")
  jq -r '[.spec.initContainers[], .spec.containers[]] | map((.env // [])[] | select(.name=="PGPASSWORD") | .value) | first' <<<"$p" >"$TMP/pw-$u"
  ok '[ "$pw" = 1 ] && [ "$ph" = 0 ]' "$u.pod.db-password" "one generated DB password shared by the pod's 6 DB clients ($pw distinct value), $ph placeholders left"
  want=$(cd "$SPIKE/.." && shasum -a 256 docs/*.ipynb docs/*.py | shasum -a 256 | cut -c1-12)
  got=$("${K[@]}" exec "$(pod $u)" -c notebook -- bash -c 'cd /home/jovyan && sha256sum docs/*.ipynb docs/*.py' | shasum -a 256 | cut -c1-12)
  ok '[ "$want" = "$got" ]' "$u.lab.docs-current" "sha256 of docs/*.ipynb + docs/*.py: pod $got, worktree $want"
done
ok '[ -s "$TMP/pw-u01" ] && ! cmp -s "$TMP/pw-u01" "$TMP/pw-u02"' db-password.per-user "u01 and u02 DB passwords differ"

# ---- NetworkPolicy: from u02's Lab terminal to u01's pod IP ----
IP1=$("${K[@]}" get pod "$(pod u01)" -o jsonpath='{.status.podIP}')
PORTS="5432 8080 8081 8082 8083 8084 8085 8086 8888"
probe() {  # <participant> <target ip>: "port=open|closed|timeout ..."
  "${K[@]}" exec -i "$(pod $1)" -c notebook -- /entrypoint.sh python - "$2" $PORTS <<'EOF'
import socket, sys
out = []
for p in map(int, sys.argv[2:]):
    s = socket.socket(); s.settimeout(3)
    try: s.connect((sys.argv[1], p)); out.append(f'{p}=open')
    except socket.timeout: out.append(f'{p}=timeout')
    except OSError: out.append(f'{p}=closed')
    finally: s.close()
print(' '.join(out))
EOF
}
self=$(probe u02 127.0.0.1)
ok '[ "$(grep -o "=open" <<<"$self" | wc -l | tr -d " ")" = 9 ]' netpol.control.own-localhost "u02 → its own 127.0.0.1: $self"
cross=$(probe u02 "$IP1")
ok '[ -n "$cross" ] && ! grep -q "=open" <<<"$cross"' netpol.u02-to-u01-blocked "u02 Lab → u01 pod $IP1: $cross"
ING=(kubectl --kubeconfig "$KC" --context kind-eoapi-spike -n ingress-nginx exec deploy/ingress-nginx-controller --)
lab=$("${ING[@]}" curl -s -o /dev/null -m 5 -w '%{http_code}' "http://$IP1:8888/user/u01/api" 2>/dev/null)
ok '[ "$lab" = 000 ]' netpol.ingress-not-to-user-pod "ingress-nginx pod → u01 :8888 HTTP $lab (000 = no connection; only the hub's proxy may connect)"
hubapi=$("${K[@]}" exec "$(pod u02)" -c notebook -- /entrypoint.sh python -c "import urllib.request as u; print(u.urlopen('http://hub:8081/hub/api/', timeout=5).status)" 2>&1 | tail -1)
ok '[ "$hubapi" = 200 ]' netpol.user-to-hub-allowed "u02 Lab → hub:8081/hub/api/ → $hubapi (the singleuser server must reach the hub)"

# A/B: without the policy the same probe must succeed, or "blocked" above proves nothing.
"${K[@]}" delete networkpolicy singleuser >/dev/null
for _ in 1 2 3 4 5 6 7 8 9 10; do open=$(probe u02 "$IP1"); grep -q "8888=open" <<<"$open" && break; sleep 1; done
ok 'grep -q "8888=open" <<<"$open"' netpol.control.without-policy "policy deleted: u02 Lab → u01 pod: $open"
ok '[ "$(grep -o "=open" <<<"$open" | wc -l | tr -d " ")" = 1 ]' loopback.without-policy "policy deleted: only :8888 open on u01's pod IP"
uids=$("${K[@]}" get pod -l component=singleuser-server -o jsonpath='{.items[*].metadata.uid}')
helm --kubeconfig "$KC" --kube-context kind-eoapi-spike -n spike-hub upgrade hub "${CHART[@]}" --reset-values \
  -f "$SPIKE/hub/values.yaml" "${FILES[@]}" --wait --timeout 10m >/dev/null 2>&1
for _ in 1 2 3 4 5 6 7 8 9 10; do cross=$(probe u02 "$IP1"); grep -q "=open" <<<"$cross" || break; sleep 1; done
ok '[ -n "$cross" ] && ! grep -q "=open" <<<"$cross"' netpol.restored-by-upgrade "after helm upgrade: u02 Lab → u01 pod: $cross"
uids2=$("${K[@]}" get pod -l component=singleuser-server -o jsonpath='{.items[*].metadata.uid}')
ok '[ "$uids" = "$uids2" ]' upgrade.user-pods-untouched "helm upgrade leaves the participant pods alone (they are the hub's, not helm's): UIDs unchanged"

# ---- a hub restart (any hub config change does one) leaves every participant running ----
"${K[@]}" rollout restart deploy/hub >/dev/null && "${K[@]}" rollout status deploy/hub --timeout=5m >/dev/null 2>&1
uids3=$("${K[@]}" get pod -l component=singleuser-server -o jsonpath='{.items[*].metadata.uid}')
ok '[ "$uids" = "$uids3" ]' hub.restart-keeps-user-pods "rollout restart deploy/hub: participant pod UIDs unchanged (the HTTP checks below run through the new hub)"

# ---- through the host's published port, as a browser ----
for _ in $(seq 30); do
  [ "$("${K[@]}" get deploy hub -o jsonpath='{.status.readyReplicas}')" = 1 ] && break; sleep 2
done
sec() { "${K[@]}" get secret participant-passwords -o jsonpath="{.data.$1}" | base64 -d; }
export U01_PASSWORD U02_PASSWORD
U01_PASSWORD=$(sec u01); U02_PASSWORD=$(sec u02)
docker run --rm -i --add-host hub.spike.local:host-gateway -e U01_PASSWORD -e U02_PASSWORD \
  eoapi-spike-lab /entrypoint.sh python - < hub.py 2>&1 || say FAIL hub.py "exited non-zero (see output above)"

# ---- the browser: STAC Browser + stac-manager OIDC under /user/u01/<app>/ ----
mkdir -p "$SPIKE/evidence/screens"
docker run --rm --add-host hub.spike.local:host-gateway --shm-size=1g -e U01_PASSWORD \
  -v "$HERE:/checks:ro" -v "$SPIKE/evidence/screens:/screens" \
  eoapi-spike-playwright python /checks/browser.py 2>&1 || say FAIL browser.py "exited non-zero (see output above)"

# ---- what each request with a Bearer JWT costs the hub ----
n=$("${K[@]}" logs deploy/hub --since=10m 2>/dev/null | grep -c -E '40[34] GET /hub/api/user ')
ok '[ "$n" -gt 0 ]' hub.bearer-lookups-observed "hub log, last 10 min: $n failed /hub/api/user lookups: each request carrying a Bearer JWT is first tried as a hub token"
exit 0
