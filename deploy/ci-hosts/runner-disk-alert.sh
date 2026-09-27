#!/bin/sh
# Warn while there is still time: report any CI-runner container whose root filesystem is fuller than
# THRESHOLD percent. si#327.
#
# WHERE THIS RUNS. On the PROXMOX HOST, not inside a runner. The failure this is about was a ZFS refquota
# on an LXC container, and a container cannot see the pool it is quota'd out of - `df` inside it reports
# the quota, which is exactly right for the in-job preflight and useless for "which of my eight machines
# is about to break". So the sweep belongs one level up, where `pct` can ask each of them.
#
# WHY IT IS NOT A SIMPLON COMMAND. A threshold that pages somebody is the operator's, not the platform's:
# it depends on who is on call and what else is already alerting. The kernel owns the in-job half
# (`simplon support ci-disk-preflight`, which REFUSES below 15% free) and this owns the half that is
# supposed to fire long before that - 80% used, i.e. 20% free, so there is a day of warning rather than a
# red pipeline.
#
# WHY IT DOES NOT PRUNE. Alerting and repairing are different jobs, and a script that quietly fixed the
# symptom would hide a runner that fills up every day from the person who should know it does. The repair
# is `simplon support ci-disk-hygiene` on the machine, once, as root.
set -eu

THRESHOLD="${THRESHOLD:-80}"

# The runner containers, by name. Pattern rather than a list: a ninth runner joins by being called one.
PATTERN="${PATTERN:-ghr-}"

exit_code=0
for ctid in $(pct list 2>/dev/null | awk 'NR > 1 { print $1 }'); do
    name=$(pct config "$ctid" 2>/dev/null | awk -F': ' '/^hostname:/ { print $2 }')
    case "$name" in
        *"$PATTERN"*) ;;
        *) continue ;;
    esac

    # `|| true`: a container that is stopped answers nothing, and one stopped machine must not end the
    # sweep before the seven that are running.
    used=$(pct exec "$ctid" -- df -P / 2>/dev/null | awk 'NR == 2 { gsub("%", "", $5); print $5 }' || true)
    if [ -z "$used" ]; then
        printf '%-10s (ct %s) could not be measured - stopped, or df refused\n' "$name" "$ctid"
        continue
    fi

    docker_used=$(pct exec "$ctid" -- df -P /var/lib/docker 2>/dev/null \
        | awk 'NR == 2 { gsub("%", "", $5); print $5 }' || true)

    if [ "$used" -ge "$THRESHOLD" ]; then
        printf 'ALERT %-10s (ct %s) root %s%% used, /var/lib/docker %s%% - over %s%%\n' \
            "$name" "$ctid" "$used" "${docker_used:-?}" "$THRESHOLD"
        exit_code=1
    else
        printf 'ok    %-10s (ct %s) root %s%% used, /var/lib/docker %s%%\n' \
            "$name" "$ctid" "$used" "${docker_used:-?}"
    fi
done

# Non-zero when at least one machine is over the line, so a systemd unit's failure is the alert and
# whatever already watches failed units needs no second channel.
exit "$exit_code"
