#!/bin/sh
set -eu

compose() {
  /usr/bin/docker compose --env-file deploy/.env --profile inference "$@"
}

compose up -d --no-deps inference
container_id="$(compose ps -q inference)"
if [ -z "$container_id" ]; then
  echo "Krabville inference container did not start" >&2
  exit 1
fi

set +e
exit_code="$(/usr/bin/docker wait "$container_id")"
wait_status=$?
set -e
if [ "$wait_status" -ne 0 ]; then
  exit 1
fi
case "$exit_code" in
  ''|*[!0-9]*) exit 1 ;;
  *) exit "$exit_code" ;;
esac
