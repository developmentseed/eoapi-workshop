#!/bin/sh
# Write participant/.env once (gitignored): random DB password, Lab password and token.
set -eu
f="$(cd "$(dirname "$0")" && pwd)/.env"
if [ -f "$f" ]; then echo "$f exists; delete it to regenerate"; exit 0; fi
umask 077
cat > "$f" <<EOF
POSTGRES_PASSWORD=$(openssl rand -hex 16)
LAB_PASSWORD=$(openssl rand -hex 6)
LAB_TOKEN=$(openssl rand -hex 24)
EOF
echo "wrote $f"
