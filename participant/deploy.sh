#!/usr/bin/env bash
# Deploy the participant stacks (participant/chart), print their credentials, or tear
# them down. The kube context and the namespace are always explicit.
#
#   participant/deploy.sh CONTEXT NAMESPACE up TAG N             # participants u01..uNN
#   participant/deploy.sh CONTEXT NAMESPACE creds > slips.csv   # participant,url,password,token
#   CONFIRM=NAMESPACE participant/deploy.sh CONTEXT NAMESPACE down
#
#   TAG          the image tag the publish workflow pushed (sha-<commit>), or
#                `local` for images loaded into kind
#   VALUES=f     extra values: host, origin, ingress.tlsSecret, nodeSelector, ...
#   RELEASE=r    default: participants
#   REMOVE=1     let `up` lower N (deletes the highest ids' stack, data and
#                credentials; re-adding them gives new ones)
#
# `up` passes N with --reset-values: a bare `helm upgrade` silently
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
  [ $# = 2 ] && [[ $2 =~ ^[0-9]+$ ]] || usage
  TAG=$1 N=$((10#$2))
  [ "$TAG" != latest ] || { echo "pin the sha- tag, not latest" >&2; exit 2; }
  # a release from before the count stored a list: u01..u03 = 3
  now=$("${H[@]}" get values "$REL" --all -o json 2>/dev/null | jq '.participants | if type == "array" then length else . end' || echo 0)
  if [ "$N" -lt "$now" ] && [ "${REMOVE:-}" != 1 ]; then
    echo "this would delete the stack, data and credentials of u$(printf %02d $((N + 1)))..u$(printf %02d "$now") (set REMOVE=1)" >&2
    exit 1
  fi
  "${H[@]}" upgrade --install "$REL" "$(dirname "$0")/chart" --reset-values ${VALUES:+-f "$VALUES"} \
    --set image.tag="$TAG" --set participants="$N" \
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
