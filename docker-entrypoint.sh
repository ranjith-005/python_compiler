#!/bin/sh
# Runs as root only long enough to hand /srv/data to the app user (files copied
# in with `docker compose cp` arrive owned by root), then drops privileges.
set -e
mkdir -p /srv/data
chown -R app:app /srv/data
exec setpriv --reuid=app --regid=app --init-groups "$@"
