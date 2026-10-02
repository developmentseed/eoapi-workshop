#!/bin/bash
# The image's 990_pgstac.sh sizes shared_buffers etc. from /proc/meminfo, which
# is the HOST's (or node's) memory, not the container's limit. In a pod sharing
# a node with ~20 stacks that would be GBs per Postgres. Pin small values sized
# for one participant's demo data; ALTER SYSTEM applies on the post-init restart.
set -euo pipefail
psql -X -q -v ON_ERROR_STOP=1 <<'EOSQL'
ALTER SYSTEM SET shared_buffers = '128MB';
ALTER SYSTEM SET effective_cache_size = '512MB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';
ALTER SYSTEM SET work_mem = '8MB';
EOSQL
