#!/bin/sh
set -eu
# Keep this service private; only the Python HTTP service receives a public domain.
: "${HYDRADB_AUTH_TOKEN:?Set a private token in the hosting service variables}"
umask 077
mkdir -p /data/store /data/cache
printf '%s' "$HYDRADB_AUTH_TOKEN" > /data/auth-token
unset HYDRADB_AUTH_TOKEN
export GRAPH_ADVERTISED_BOLT_ADDR="${RAILWAY_PRIVATE_DOMAIN:-hydradb}:7687"
export GRAPH_BOLT_NODE_ADDRESSES="node-0=127.0.0.1:7687"
exec /usr/local/bin/graph-node
