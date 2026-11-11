#!/bin/sh
# Refuse, and alert, when a CI runner's service user cannot run a container. si#624.
#
# WHAT HAPPENED. On 2026-11-11 a runner update on ghr-8 left every docker call a job made refused with
# `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`. Nothing on
# the host said so: the runner kept taking jobs, and each job went red about thirty steps in, on symptoms.
#
# WHERE THIS RUNS. On the RUNNER machine (inside the LXC), not on the Proxmox host: the question is what
# the runner's own service user may do with this machine's docker socket, and only this machine has both.
# That is the difference from runner-disk-alert.sh, which sweeps every runner from one level up.
#
# TWO WAYS IN, one check:
#
#   runner-docker-check.sh --self
#       As ExecStartPre= of the runner's unit (runner-docker-check.conf). systemd runs it as the unit's
#       User= with that user's groups, which are the credentials the runner itself is about to start
#       with, so a non-zero exit refuses the start - loudly, in `systemctl status` and the journal.
#
#   runner-docker-check.sh            (as root, from runner-docker-check.timer)
#       For every RUNNING unit matching $PATTERN, the check runs with the credentials of that unit's main
#       process as they are NOW - uid, gid and supplementary groups read from /proc/<pid>/status. Not the
#       user's groups from /etc/group: a group is inherited at process start, so a runner started before
#       its user joined the docker group cannot use the socket however /etc/group reads. And not only at
#       start: the runner updates itself without restarting through systemd, so ExecStartPre= never sees
#       what an update changed.
#       A LIMIT, measured with transient units: a unit read in the instant after it started can still
#       show systemd's root credentials, before it dropped to User=, and is then checked as root. A
#       runner that has been up for a timer interval is past that.
#
# GREEN ONLY FROM A CONTAINER THAT RAN. `docker version` answering proves a daemon, not that this user
# may start a container through it. The image is the kernel's own pinned busybox (`test:file`'s, and
# si#623's in-job probe's), and src/tests/test_ci_hosts.py holds the two equal.
#
# WHY IT IS NOT A SIMPLON COMMAND, for runner-disk-alert.sh's reason: the in-job half is the kernel's
# (si#623, `support ci-docker-preflight`), and the host half belongs to whoever operates the machine.
#
# Exit 0: every checked runner ran a container. Exit 1: at least one could not, or there was nothing to
# check - no running unit matched, which is a runner taking no jobs and not a healthy one.
set -u

IMAGE="${IMAGE:-busybox:1.37.0-musl@sha256:5cec3fc171c87218698e85a52af7087de727372aae264a787b8112901a5b0092}"
# The runner units, by name: `actions.runner.<owner>-<repo>.<name>.service` as config.sh/svc.sh installs them.
PATTERN="${PATTERN:-actions.runner.*.service}"
SOCKET="${SOCKET:-/var/run/docker.sock}"
# A run that hangs is neither green nor red: the probe may have to pull IMAGE first, and gets this long.
TIMEOUT="${TIMEOUT:-120}"

# The facts a refusal is diagnosed from, and the way out. $1 names who was checked.
facts() {
    printf '  checked as: %s\n' "$1"
    if [ -e "$SOCKET" ]; then
        printf '  socket: %s\n' "$(stat -c '%n uid %u (%U), gid %g (%G), mode 0%a' "$SOCKET")"
    else
        printf '  socket: %s does not exist - is docker running? systemctl status docker\n' "$SOCKET"
        return
    fi
    printf '  way out: the socket wants gid %s with mode 0660; add the runner user to that group\n' \
        "$(stat -c %g "$SOCKET")"
    printf '    (usermod -aG %s <user>, or simplon support ci-privileges <user>) and RESTART the runner\n' \
        "$(stat -c %G "$SOCKET")"
    printf '    service - a group is inherited at process start; a socket at 0600 needs SocketMode=0660\n'
    printf '    in docker.socket and a docker restart\n'
}

# Run one container with the credentials given as setpriv options (none: as this process). $1 = label.
probe() {
    label="$1"; shift
    out=$(timeout "$TIMEOUT" "$@" docker run --rm --network none "$IMAGE" true 2>&1)
    rc=$?
    if [ "$rc" -eq 0 ]; then
        printf 'ok    %s ran a container (%s)\n' "$label" "$IMAGE"
        return 0
    fi
    if [ "$rc" -eq 124 ]; then
        printf 'ALERT %s: docker did not finish within %ss\n' "$label" "$TIMEOUT"
    else
        printf 'ALERT %s could not run a container (rc %s):\n' "$label" "$rc"
    fi
    printf '%s\n' "$out" | sed 's/^/    /'
    return 1
}

if [ "${1:-}" = "--self" ]; then
    who="$(id)"
    probe "$who" && exit 0
    facts "$who"
    exit 1
fi

checked=0
exit_code=0
for unit in $(systemctl list-units --type=service --state=running --no-legend --plain "$PATTERN" 2>/dev/null \
                | awk '{ print $1 }'); do
    pid=$(systemctl show -p MainPID --value "$unit")
    status="/proc/$pid/status"
    if [ -z "$pid" ] || [ "$pid" = 0 ] || [ ! -r "$status" ]; then
        printf 'ALERT %s is running but has no main process to read (MainPID=%s)\n' "$unit" "${pid:-?}"
        exit_code=1
        continue
    fi
    uid=$(awk '/^Uid:/ { print $2 }' "$status")
    gid=$(awk '/^Gid:/ { print $2 }' "$status")
    groups=$(awk '/^Groups:/ { $1 = ""; gsub(/^ +| +$/, ""); gsub(/ +/, ","); print }' "$status")
    who="$unit, pid $pid, uid $uid, gid $gid, groups ${groups:-none}"
    # The process's own HOME and DOCKER_HOST, because they steer which daemon its docker CLI talks to.
    home=$(tr '\0' '\n' < "/proc/$pid/environ" | sed -n 's/^HOME=//p')
    dhost=$(tr '\0' '\n' < "/proc/$pid/environ" | sed -n 's/^DOCKER_HOST=//p')
    checked=$((checked + 1))
    if [ -n "$groups" ]; then
        set -- setpriv --reuid "$uid" --regid "$gid" --groups "$groups"
    else
        set -- setpriv --reuid "$uid" --regid "$gid" --clear-groups
    fi
    set -- "$@" env HOME="${home:-/nonexistent}" ${dhost:+DOCKER_HOST="$dhost"}
    if ! probe "$who" "$@"; then
        facts "$who"
        exit_code=1
    fi
done

if [ "$checked" -eq 0 ] && [ "$exit_code" -eq 0 ]; then
    printf 'ALERT no running unit matches %s: no runner here is taking jobs\n' "$PATTERN"
    exit 1
fi
exit "$exit_code"
