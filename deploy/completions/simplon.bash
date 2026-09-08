# GENERATED from simplon.yaml by `simplon support completion`. Do not edit.
#
# The command tree below is simplon.yaml's, resolved once here so that a TAB costs a `case`
# statement in the shell you are already running - no interpreter start, no virtualenv check.
# Regenerate it with `./simplon.sh support completion`; `--check` reports drift and writes nothing.
#
# INSTALL IT - a generated completion nobody sources completes nothing. From the product root:
#
#     echo "source $PWD/deploy/completions/simplon.bash" >> ~/.bashrc
#
# and open a new shell. In zsh the same file works once bash's completion API is loaded:
#
#     autoload -U +X bashcompinit && bashcompinit
#     echo "source $PWD/deploy/completions/simplon.bash" >> ~/.zshrc
#
# It is registered on `simplon.sh` rather than on `./simplon.sh`, and that covers both: bash falls back
# to the portion of a command word following the final slash when the full pathname carries no
# compspec of its own (bash manual 5.3.9, Programmable Completion).

_simplon_nodes() {
    _simplon_reply=()
    case "$1" in
        '') _simplon_reply=('build' 'test' 'release' 'support') ;;
        'build') _simplon_reply=('wheel' 'reference' 'site' 'docs') ;;
        'test') _simplon_reply=('all' 'typecheck-python') ;;
        'release') _simplon_reply=('tag') ;;
        'support') _simplon_reply=('git' 'tasks' 'install' 'completion' 'doctor' 'workflows') ;;
        'support.git') _simplon_reply=('commit' 'push' 'prune-branches' 'submodules' 'auth-scopes') ;;
        'support.tasks') _simplon_reply=('catalogue' 'generate') ;;
    esac
}

_simplon_is_env() {
    return 1
}

_simplon_complete() {
    local cur tok node word i hit
    local -a _simplon_reply
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    node=''
    # Walk the tokens already typed down the tree. An option never moves the node, an
    # environment token is consumed once and only in first position, and a token the current
    # node does not carry means we are inside a command's own arguments - which this file does
    # not describe, so it answers nothing and lets `complete -o default` offer filenames.
    for (( i = 1; i < COMP_CWORD; i++ )); do
        tok="${COMP_WORDS[i]}"
        case "$tok" in ""|-*) continue ;; esac
        if [ -z "$node" ] && _simplon_is_env "$tok"; then
            node='@env'
            continue
        fi
        _simplon_nodes "$node"
        [ ${#_simplon_reply[@]} -gt 0 ] || return 0
        hit=''
        for word in "${_simplon_reply[@]}"; do
            if [ "$word" = "$tok" ]; then hit=1; break; fi
        done
        [ -n "$hit" ] || return 0
        if [ "$node" = '@env' ]; then node="$tok"; else node="${node:+$node.}$tok"; fi
    done
    _simplon_nodes "$node"
    [ ${#_simplon_reply[@]} -gt 0 ] || return 0
    for word in "${_simplon_reply[@]}"; do
        case "$word" in "$cur"*) COMPREPLY+=( "$word" ) ;; esac
    done
}

complete -o default -F _simplon_complete simplon.sh
