#!/bin/sh
set -eu

umask 077
mkdir -p "${CODEX_HOME:?}"
cp /run/secrets/codex-auth.json "$CODEX_HOME/auth.json"
exec krabville-inference
