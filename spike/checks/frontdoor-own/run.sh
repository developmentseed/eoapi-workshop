#!/usr/bin/env bash
# Own-chart front door on the local kind cluster (spike/chart, release `spike`,
# namespace spike-own). Prereq: see spike/evidence/frontdoor-own.md "Reproduce".
# Prints one line per check: PASS|FAIL|BLOCKED <name> — <detail>. Always exits 0.
# Never prints a password, token or JWT.
#
# Mutates the local kind cluster only: deletes the NetworkPolicy for an A/B
# control, then `helm upgrade` (the upgrade check) puts it back.
set -uo pipefail
cd "$(dirname "$0")"
SPIKE=$(cd ../.. && pwd)
KC="$SPIKE/.kind-kubeconfig"
K=(kubectl --kubeconfig "$KC" --context kind-eoapi-spike -n spike-own)
H=(helm --kubeconfig "$KC" --kube-context kind-eoapi-spike -n spike-own)
say() { echo "$1 $2 — $3"; }
ok() { if eval "$1"; then say PASS "$2" "$3"; else say FAIL "$2" "$3"; fi; }

if ! "${K[@]}" get deploy spike-u01 spike-u02 >/dev/null 2>&1; then
  say BLOCKED cluster "release spike not found in spike-own on kind-eoapi-spike"; exit 0
fi

# ---- render: nothing cluster-scoped ----
kinds=$(helm template spike "$SPIKE/chart" -n spike-own 2>/dev/null | awk '/^kind:/{print $2}' | sort -u | tr '\n' ' ')
cluster=$(kubectl --kubeconfig "$KC" --context kind-eoapi-spike api-resources --namespaced=false --no-headers | awk '{print $NF}' | sort -u)
hits=$(for k in $kinds; do grep -qx "$k" <<<"$cluster" && echo "$k"; done | tr '\n' ' ')
ok '[ -z "$hits" ]' render.no-cluster-scoped "kinds: $kinds; cluster-scoped among them: ${hits:-none}"

# ---- render: the same containers as compose.participant.yml ----
helm template spike "$SPIKE/chart" -n spike-own 2>/dev/null | python3 parity.py
# control: two one-word drifts in the render must be caught
n=$(helm template spike "$SPIKE/chart" -n spike-own 2>/dev/null \
  | sed -e 's/- \/stac$/- \/stacx/' -e 's/value: "\/raster"/value: "\/rasterx"/' | python3 parity.py | grep -c '^FAIL')
ok '[ "$n" = 2 ]' parity.control.drift-detected "render with --root-path and TITILER root path altered → $n FAIL lines (want 2)"

# ---- pods ----
for u in u01 u02; do
  p=$("${K[@]}" get pod -l participant=$u -o json)
  ready=$(jq -r '[.items[0].status.containerStatuses[], .items[0].status.initContainerStatuses[]] | map(select(.ready)) | length' <<<"$p")
  restarts=$(jq -r '[.items[0].status.containerStatuses[], .items[0].status.initContainerStatuses[]] | map(.restartCount) | add' <<<"$p")
  ok '[ "$ready" = 9 ] && [ "$restarts" = 0 ]' "$u.pod.ready" "$ready/9 containers ready, $restarts restarts"
  side=$(jq -r '.items[0].spec.initContainers[0] | "\(.name) restartPolicy=\(.restartPolicy) startupProbe=\(.startupProbe.exec.command[0])"' <<<"$p")
  dbs=$(jq -r '.items[0].status.initContainerStatuses[0].state.running.startedAt' <<<"$p")
  labs=$(jq -r '.items[0].status.containerStatuses[] | select(.name=="lab") | .state.running.startedAt' <<<"$p")
  ok '[[ "$side" == "database restartPolicy=Always startupProbe=pg_isready" && "$labs" > "$dbs" ]]' "$u.pod.db-native-sidecar" "$side; db started $dbs, lab $labs"
  sa=$(jq -r '.items[0].spec.automountServiceAccountToken' <<<"$p")
  mnt=$("${K[@]}" exec deploy/spike-$u -c lab -- sh -c 'ls /var/run/secrets/kubernetes.io 2>&1 | head -1')
  ok '[ "$sa" = false ]' "$u.pod.no-sa-token" "automountServiceAccountToken=$sa; /var/run/secrets/kubernetes.io: $mnt"
  cs='[.items[0].spec.initContainers[], .items[0].spec.containers[]]'
  req=$(jq -r "$cs"' | map("\(.name)=\(.resources.requests.cpu)/\(.resources.requests.memory)/\(.resources.limits.memory)") | join(" ")' <<<"$p")
  nres=$(jq -r "$cs"' | map(select(.resources.requests.cpu and .resources.requests.memory and .resources.limits.memory and (.resources.limits.cpu|not))) | length' <<<"$p")
  ok '[ "$nres" = 9 ]' "$u.pod.resources" "$nres/9 with cpu+memory requests, a memory limit, no cpu limit (request/request/limit): $req"
  arch=$(for c in stac-browser stac-manager stac-fastapi; do printf '%s=%s ' $c "$("${K[@]}" exec deploy/spike-$u -c $c -- uname -m 2>&1)"; done)
  ok '[ "$arch" = "stac-browser=x86_64 stac-manager=x86_64 stac-fastapi=aarch64 " ]' "$u.pod.arch" "$arch(browser/manager emulated on the arm64 node)"
  secs=$(jq -r '.items[0].status.conditions | map({(.type): (.lastTransitionTime|fromdateiso8601)}) | add | .Ready - .PodScheduled' <<<"$p")
  ok '[ "$secs" -le 120 ]' "$u.pod.cold-start" "PodScheduled → Ready in ${secs}s (images preloaded on the node)"
  # The chart's Lab has no docs mount (compose mounts ../docs): the notebooks
  # are the ones baked into the image, so a stale image means stale notebooks.
  want=$(cd "$SPIKE/.." && shasum -a 256 docs/*.ipynb docs/*.py | shasum -a 256 | cut -c1-12)
  got=$("${K[@]}" exec deploy/spike-$u -c lab -- sh -c 'cd /home/jovyan && sha256sum docs/*.ipynb docs/*.py' | shasum -a 256 | cut -c1-12)
  ok '[ "$want" = "$got" ]' "$u.lab.docs-current" "sha256 of docs/*.ipynb + docs/*.py: pod $got, worktree $want"
done

# ---- credentials (read once, before the upgrade: used again after it) ----
sec() { "${K[@]}" get secret spike-credentials -o jsonpath="{.data.$1}" | base64 -d; }
for u in u01 u02; do
  U=$(tr a-z A-Z <<<"$u")
  export "${U}_PASSWORD=$(sec $u-password)" "${U}_TOKEN=$(sec $u-token)"
done
d1=$(sec u01-db); d2=$(sec u02-db)
ok '[ ${#U01_PASSWORD} = 12 ] && [ "$U01_PASSWORD" != "$U02_PASSWORD" ] && [ "$d1" != "$d2" ] && [ "$U01_TOKEN" != "$U02_TOKEN" ]' \
  secret.per-user "6 keys; Lab password 12 chars; password, token and DB password differ between u01 and u02"

# ---- NetworkPolicy: from u02's Lab terminal to u01's pod IP ----
IP1=$("${K[@]}" get pod -l participant=u01 -o jsonpath='{.items[0].status.podIP}')
PORTS="5432 8080 8081 8082 8083 8084 8085 8086 18888"
probe() {  # <participant> <target ip>: "port=open|closed|timeout ..."
  "${K[@]}" exec deploy/spike-$1 -c lab -- python -c "
import socket, sys
out = []
for p in map(int, sys.argv[2:]):
    s = socket.socket(); s.settimeout(3)
    try: s.connect((sys.argv[1], p)); out.append(f'{p}=open')
    except socket.timeout: out.append(f'{p}=timeout')
    except OSError: out.append(f'{p}=closed')
    finally: s.close()
print(' '.join(out))" "$2" $PORTS
}
self=$(probe u02 127.0.0.1)
ok '[ "$(grep -o "=open" <<<"$self" | wc -l | tr -d " ")" = 9 ]' netpol.control.own-localhost "u02 → its own 127.0.0.1: $self"
cross=$(probe u02 "$IP1")
ok '! grep -q "=open" <<<"$cross"' netpol.u02-to-u01-blocked "u02 Lab → u01 pod $IP1: $cross"
ING=("${K[@]/spike-own/ingress-nginx}" exec deploy/ingress-nginx-controller --)
lab=$("${ING[@]}" curl -s -o /dev/null -m 5 -w '%{http_code}' "http://$IP1:18888/login")
sap=$("${ING[@]}" curl -s -o /dev/null -m 5 -w '%{http_code}' "http://$IP1:8084/stac/" 2>/dev/null)
ok '[ "$lab" = 200 ] && [ "$sap" = 000 ]' netpol.ingress-to-lab-only "ingress-nginx pod → u01 :18888 HTTP $lab; → :8084 HTTP $sap (000 = no connection)"

# Egress from u01's Lab terminal: cluster addresses closed, public 443 open.
NODE=$(kubectl --kubeconfig "$KC" --context kind-eoapi-spike get node -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
egress() {
  "${K[@]}" exec deploy/spike-u01 -c lab -- python -c "
import socket, sys
out = []
for name, host, port in (a.split(':') for a in sys.argv[1:]):
    s = socket.socket(); s.settimeout(3)
    try: s.connect((host, int(port))); out.append(f'{name}=open')
    except socket.timeout: out.append(f'{name}=timeout')
    except socket.gaierror: out.append(f'{name}=nodns')
    except OSError: out.append(f'{name}=closed')
    finally: s.close()
print(' '.join(out))" api:kubernetes.default.svc:443 other-ns:ingress-nginx-controller.ingress-nginx.svc:80 \
    node:"$NODE":10250 earth-search:earth-search.aws.element84.com:443 s3:s3.us-west-2.amazonaws.com:443
}
out=$(egress)
ok '[ "$out" = "api=timeout other-ns=timeout node=timeout earth-search=open s3=open" ]' netpol.egress "u01 Lab → $out"

# A/B: without the policy the same probe must succeed, or the "blocked" above proves nothing.
"${K[@]}" delete networkpolicy spike-lab-only >/dev/null
for _ in 1 2 3 4 5 6 7 8 9 10; do open=$(probe u02 "$IP1"); grep -q "18888=open" <<<"$open" && break; sleep 1; done
ok 'grep -q "18888=open" <<<"$open"' netpol.control.without-policy "policy deleted: u02 Lab → u01 pod: $open"
out=$(egress)
ok '[ "$out" = "api=open other-ns=open node=open earth-search=open s3=open" ]' netpol.control.egress-without-policy "policy deleted: u01 Lab → $out"
# Second layer: the backends bind 127.0.0.1, so even without the policy only the Lab answers.
ok '[ "$(grep -o "=open" <<<"$open" | wc -l | tr -d " ")" = 1 ]' loopback.without-policy "policy deleted: only :18888 open on u01's pod IP"

# ---- helm upgrade: restores the policy, keeps the credentials, restarts nobody ----
before=$("${K[@]}" get secret spike-credentials -o jsonpath='{.data}' | shasum -a 256 | cut -c1-12)
uids=$("${K[@]}" get pod -l app.kubernetes.io/instance=spike -o jsonpath='{.items[*].metadata.uid}')
rev=$("${H[@]}" upgrade spike "$SPIKE/chart" --reset-values --wait --timeout 5m 2>/dev/null | awk '/^REVISION/{print $2}')
after=$("${K[@]}" get secret spike-credentials -o jsonpath='{.data}' | shasum -a 256 | cut -c1-12)
uids2=$("${K[@]}" get pod -l app.kubernetes.io/instance=spike -o jsonpath='{.items[*].metadata.uid}')
ok '[ -n "$rev" ] && [ "$before" = "$after" ]' upgrade.keeps-credentials "revision $rev; Secret data sha256 $before → $after"
ok '[ "$uids" = "$uids2" ]' upgrade.no-restart "participant pod UIDs unchanged across the upgrade"
for _ in 1 2 3 4 5 6 7 8 9 10; do cross=$(probe u02 "$IP1"); grep -q "=open" <<<"$cross" || break; sleep 1; done
ok '! grep -q "=open" <<<"$cross"' netpol.restored-by-upgrade "after upgrade: u02 Lab → u01 pod: $cross"

# Adding a participant mid-event must not restart the others (then put it back).
"${H[@]}" upgrade spike "$SPIKE/chart" --set 'participants={u01,u02,u03}' --wait --timeout 5m >/dev/null 2>&1
n3=$("${K[@]}" get pod -l participant=u03 -o jsonpath='{.items[0].status.containerStatuses[?(@.name=="lab")].ready}')
uids3=$("${K[@]}" get pod -l participant!=u03,app.kubernetes.io/instance=spike -o jsonpath='{.items[*].metadata.uid}')
# --reset-values: with no value flags, `helm upgrade` silently reuses the last --set.
"${H[@]}" upgrade spike "$SPIKE/chart" --reset-values --wait --timeout 5m >/dev/null 2>&1
gone=$("${K[@]}" get deploy spike-u03 2>&1 | grep -c NotFound)
p1=$(sec u01-password)
ok '[ "$n3" = true ] && [ "$uids" = "$uids3" ] && [ "$gone" = 1 ] && [ "$p1" = "$U01_PASSWORD" ]' upgrade.add-remove-participant \
  "u03 added (lab ready=$n3) and removed (deployment gone=$gone); u01/u02 pod UIDs unchanged; u01 password unchanged"

# ---- the host's published port (what a browser on this Mac opens) ----
host=$(docker run --rm --add-host lab-u01.spike.local:host-gateway eoapi-spike-lab python -c \
  "import urllib.request as u; print(u.urlopen('http://lab-u01.spike.local:18080/login', timeout=10).status)" 2>&1 | tail -1)
ok '[ "$host" = 200 ]' host.port-18080 "http://lab-u01.spike.local:18080/login via the host's 127.0.0.1:18080 → HTTP $host"

# ---- through the ingress, with the pre-upgrade passwords ----
docker run --rm -i --network kind -e U01_PASSWORD -e U01_TOKEN -e U02_PASSWORD -e U02_TOKEN \
  eoapi-spike-lab /entrypoint.sh python - < ingress.py 2>&1 \
  || say FAIL ingress.py "exited non-zero (see output above)"

# ---- a Lab container restart (OOM at its limit, a crash) keeps the participant's files? ----
# Last on purpose: it restarts u02's Lab, then a rollout gives u02 a clean pod again.
labrc() { "${K[@]}" get pod -l participant=u02 -o jsonpath='{.items[0].status.containerStatuses[?(@.name=="lab")].restartCount}'; }
rc0=$(labrc)
"${K[@]}" exec deploy/spike-u02 -c lab -- sh -c 'echo work > /home/jovyan/work/participant-work.txt && kill 1' >/dev/null 2>&1
for _ in $(seq 60); do rc=$(labrc); [ "$rc" != "$rc0" ] && break; sleep 1; done
"${K[@]}" wait pod -l participant=u02 --for=condition=Ready --timeout=120s >/dev/null 2>&1
kept=$("${K[@]}" exec deploy/spike-u02 -c lab -- cat /home/jovyan/work/participant-work.txt 2>/dev/null)
ok '[ "$kept" = work ]' lab.files-survive-container-restart \
  "wrote work/participant-work.txt, killed the Lab (restartCount=$rc): file $([ "$kept" = work ] && echo kept || echo gone)"
"${K[@]}" rollout restart deploy/spike-u02 >/dev/null && "${K[@]}" rollout status deploy/spike-u02 --timeout=5m >/dev/null
exit 0
