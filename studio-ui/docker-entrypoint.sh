#!/bin/sh
set -eu
envsubst '${AUTH_UPSTREAM} ${AGENT_UPSTREAM} ${EXECUTION_UPSTREAM} ${STORAGE_UPSTREAM}' \
  < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
