#!/usr/bin/env bash
# Deploy the participant stacks (participant/chart), print their credentials, or tear
# them down. The kube context and the namespace are always explicit.
#
#   participant/deploy.sh CONTEXT NAMESPACE up TAG u01 u02 ...   # exactly these participants
#   participant/deploy.sh CONTEXT NAMESPACE creds > slips.csv   # participant,url,password,token
#   CONFIRM=NAMESPACE participant/deploy.sh CONTEXT NAMESPACE down
#
#   TAG          the image tag the publish workflow pushed (sha-<commit>), or
#                `local` for images loaded into kind
#   VALUES=f     extra values: host, origin, ingress.tlsSecret, nodeSelector, ...
#   RELEASE=r    default: participants
#   REMOVE=1     let `up` drop participants deployed now (deletes their stack,
#                data and credentials; re-adding them gives new ones)
#
# `up` passes the whole list with --reset-values: a bare `helm upgrade` silently
# reuses the previous --set. `down` uninstalls the release, which owns the
# volumes; it never deletes the namespace.
set -euo pipefail
usage() { sed -n '2,18p' "$0" >&2; exit 2; }
[ $# -ge 3 ] || usage
CTX=$1 NS=$2 CMD=$3
shift 3
REL=${RELEASE:-participants}
H=(helm --kube-context "$CTX" -n "$NS")
echo "target: context $CTX, namespace $NS, release $REL" >&2

case $CMD in
up)
  [ $# -ge 2 ] || usage
  TAG=$1
  shift
  [ "$TAG" != latest ] || { echo "pin the sha- tag, not latest" >&2; exit 2; }
  now=$("${H[@]}" get values "$REL" --all -o json 2>/dev/null | jq -r '.participants[]' || true)
  gone=$(comm -23 <(sort <<<"$now") <(printf '%s\n' "$@" | sort) | xargs)
  if [ -n "$gone" ] && [ "${REMOVE:-}" != 1 ]; then
    echo "this would delete the stack, data and credentials of: $gone (set REMOVE=1)" >&2
    exit 1
  fi
  "${H[@]}" upgrade --install "$REL" "$(dirname "$0")/chart" --reset-values ${VALUES:+-f "$VALUES"} \
    --set image.tag="$TAG" --set-json "participants=$(printf '%s\n' "$@" | jq -Rnc '[inputs]')" \
    --wait --timeout 20m
  ;;
creds)
  origin=$("${H[@]}" get values "$REL" --all -o json | jq -r .origin)
  echo participant,url,password,token
  kubectl --context "$CTX" -n "$NS" get secret "$REL-credentials" -o json | jq -r --arg o "$origin" '
    .data as $d | $d | keys[] | select(endswith("-password")) | rtrimstr("-password") as $u
    | [$u, ($o | sub("%s"; $u)), ($d[$u + "-password"] | @base64d), ($d[$u + "-token"] | @base64d)] | @csv'
  ;;
down)
  [ "${CONFIRM:-}" = "$NS" ] || { echo "deletes every stack and its data: set CONFIRM=$NS" >&2; exit 2; }
  "${H[@]}" uninstall "$REL" --wait
  ;;
*) usage ;;
esac
