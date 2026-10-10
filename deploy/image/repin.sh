#!/usr/bin/env bash
# Move deploy/image/image.pin to an image that has ALREADY been published and read back (si#313's order:
# publish first, pin afterwards). Run by release.yml's `image` job after `release image`, and by a person
# by hand the same way. It edits two lines and nothing else: the reference, and the digest record the
# file keeps as the second source for that reference.
#
#   deploy/image/repin.sh <reference> <digest> [<pin file>]
#   deploy/image/repin.sh ghcr.io/marcozwyssig/simplon:v0.27.0 sha256:0123...
#
# Exit 0 when the file now names <reference>, having changed it; 3 when it ALREADY named it and nothing
# was written - "nothing to do" and "done" are two answers, and the caller opens a pull request only on
# the second; 2 on a usage error or a file it cannot read the way it expects.
set -euo pipefail

ref="${1:-}"
digest="${2:-}"
pin="${3:-$(dirname "$0")/image.pin}"

case "$ref" in
    *:v[0-9]*) ;;
    *) echo "repin: '$ref' is not a reference pinned to a release tag (<image>:v<version>)" >&2; exit 2 ;;
esac
case "$digest" in
    sha256:[0-9a-f]*) ;;
    *) echo "repin: '$digest' is not a sha256 digest" >&2; exit 2 ;;
esac
[ -r "$pin" ] || { echo "repin: cannot read $pin" >&2; exit 2; }

current="$(grep -v '^[[:space:]]*#' "$pin" | grep -v '^[[:space:]]*$' | head -n1 || true)"
if [ "$current" = "$ref" ]; then
    echo "repin: $pin already pins $ref; nothing written"
    exit 3
fi
[ -n "$current" ] || { echo "repin: $pin pins nothing yet, so there is no line to move" >&2; exit 2; }
grep -q '^#   v[^:]*: digest sha256:' "$pin" || {
    echo "repin: $pin has no '#   v<version>: digest sha256:...' record to append to" >&2; exit 2; }

tag="${ref##*:}"
tmp="$(mktemp)"
# The digest record goes after the last one and its continuation lines; the reference line is replaced
# where it stands.
awk -v cur="$current" -v ref="$ref" -v rec="#   ${tag}: digest ${digest}" '
    {
        lines[NR] = $0
        # A record may carry continuation lines, indented under it; the new record goes after those.
        if ($0 ~ /^#   v[^:]*: digest sha256:/) last = NR
        else if (last == NR - 1 && $0 ~ /^#     +[^ ]/) last = NR
    }
    END {
        for (i = 1; i <= NR; i++) {
            print (lines[i] == cur ? ref : lines[i])
            if (i == last) print rec
        }
    }' "$pin" > "$tmp"
cat "$tmp" > "$pin"
rm -f "$tmp"
echo "repin: $pin now pins $ref ($digest)"
