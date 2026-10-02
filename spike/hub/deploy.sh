#!/usr/bin/env bash
# z2jh front door on the LOCAL kind cluster (namespace spike-hub, release hub):
# images, the password Secret (once), the pinned chart, then pre-spawn every user.
# Prereq: kind cluster eoapi-spike and the images eoapi-spike-lab, eoapi-spike-db.
set -euo pipefail
cd "$(dirname "$0")"
SPIKE=$(cd .. && pwd)
KC="$SPIKE/.kind-kubeconfig"
K=(kubectl --kubeconfig "$KC" --context kind-eoapi-spike -n spike-hub)
USERS=(u01 u02)  # keep in step with hub.config.Authenticator.allowed_users

# A fixed tag: the pre-puller would pull a :latest image with policy Always.
docker build -q -t eoapi-spike-hub-lab:spike . >/dev/null
docker tag eoapi-spike-db:latest eoapi-spike-db:spike
kind load docker-image --name eoapi-spike eoapi-spike-hub-lab:spike eoapi-spike-db:spike

"${K[@]}" get ns spike-hub >/dev/null 2>&1 || "${K[@]}" create ns spike-hub
# One password per user, generated once and kept (delete the Secret to rotate all).
if ! "${K[@]}" get secret participant-passwords >/dev/null 2>&1; then
  pw=(); for u in "${USERS[@]}"; do pw+=("--from-literal=$u=$(openssl rand -hex 6)"); done
  "${K[@]}" create secret generic participant-passwords "${pw[@]}" >/dev/null
fi

# --reset-values: never silently reuse an earlier --set.
helm --kubeconfig "$KC" --kube-context kind-eoapi-spike -n spike-hub upgrade --install hub jupyterhub \
  --repo https://hub.jupyter.org/helm-chart/ --version 4.4.2 --reset-values -f values.yaml \
  --set-file singleuser.extraFiles.workshop_filters.stringData="$SPIKE/../docs/workshop_filters.py" \
  --set-file singleuser.extraFiles.stac_browser_conf.stringData="$SPIKE/stac-browser/default.conf.template" \
  --wait --timeout 15m

# Pre-spawn through the hub REST API with the spike-admin service token (from
# Secret `hub`), from inside the hub pod; the token travels on stdin only.
token=$("${K[@]}" get secret hub -o jsonpath='{.data.hub\.services\.spike-admin\.apiToken}' | base64 -d)
for u in "${USERS[@]}"; do
  printf 'import urllib.request as r\nq = r.Request("http://localhost:8081/hub/api/users/%s/server", method="POST", headers={"Authorization": "token %s"})\ntry: print("%s", r.urlopen(q).status)\nexcept Exception as e: print("%s", e)\n' \
    "$u" "$token" "$u" "$u" | "${K[@]}" exec -i deploy/hub -- python -
done
for _ in $(seq 60); do
  [ "$("${K[@]}" get pod -l component=singleuser-server -o name | wc -l)" -ge ${#USERS[@]} ] && break; sleep 2
done
"${K[@]}" wait pod -l component=singleuser-server --for=condition=Ready --timeout=10m
