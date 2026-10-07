#!/usr/bin/env bash
# Authenticate on a fresh Linux machine and clone private dotfiles.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bash bootstrap.sh [--repo OWNER/NAME] [--destination PATH]

Install missing Git/GitHub CLI packages, sign in to github.com, and clone
dotfiles over HTTPS. Supports Fedora, Ubuntu, and Arch Linux.

Options:
  --repo OWNER/NAME    GitHub repository (default: jackpinto/dot-files)
  --destination PATH  Checkout directory (default: ~/projects/dot-files)
  -h, --help          Show this help without changing the machine

Run as your regular user. Package installation uses sudo when necessary.
EOF
}

die() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

detect_distro() {
    local ID=''
    [[ -r /etc/os-release ]] || die 'Cannot detect Linux distribution: /etc/os-release is missing.'
    source /etc/os-release
    case "$ID" in
        fedora|ubuntu|arch) printf '%s\n' "$ID" ;;
        *) die "Unsupported distribution: ${ID:-unknown}. Supported: Fedora, Ubuntu, Arch." ;;
    esac
}

install_dependencies() {
    local distro="$1"
    local -a packages=()
    command -v git >/dev/null 2>&1 || packages+=(git)
    if ! command -v gh >/dev/null 2>&1; then
        case "$distro" in
            arch) packages+=(github-cli) ;;
            *) packages+=(gh) ;;
        esac
    fi
    if (( ${#packages[@]} == 0 )); then
        printf 'Git and GitHub CLI are already installed.\n'
        return 0
    fi

    command -v sudo >/dev/null 2>&1 || die 'Install sudo, or ask an administrator to install Git and GitHub CLI.'
    # HTTPS must work even on minimal installations. Use distribution packages
    # so no extra package repository, downloaded installer, or runtime is needed.
    packages+=(ca-certificates)
    printf 'Installing missing dependencies using %s packages...\n' "$distro"
    case "$distro" in
        fedora) sudo dnf install -y "${packages[@]}" ;;
        ubuntu)
            sudo apt-get update
            sudo apt-get install -y "${packages[@]}"
            ;;
        arch)
            # Do not refresh the database with -Sy: that risks a partial upgrade.
            sudo pacman -S --needed --noconfirm "${packages[@]}"
            ;;
    esac
    command -v git >/dev/null 2>&1 || die 'Git installation did not provide git on PATH.'
    command -v gh >/dev/null 2>&1 || die 'GitHub CLI installation did not provide gh on PATH.'
}

authenticate() {
    if ! gh auth status --hostname github.com >/dev/null 2>&1; then
        printf 'Sign in to GitHub in your browser. On a headless machine, open the displayed URL on another device.\n'
        gh auth login --hostname github.com --git-protocol https --web
    else
        printf 'Reusing the authenticated GitHub session.\n'
    fi
    gh auth setup-git --hostname github.com
}

validate_destination() {
    local repo="$1" destination="$2" origin
    if [[ ! -e "$destination" && ! -L "$destination" ]]; then
        return 0
    fi
    [[ -d "$destination" && -e "$destination/.git" ]] ||
        die "Destination already exists and is not a Git checkout: $destination. Choose another --destination."
    command -v git >/dev/null 2>&1 || die "Cannot inspect existing destination without Git: $destination."
    origin=$(git -C "$destination" config --get remote.origin.url) ||
        die "Destination has no origin remote: $destination."
    # Read the stored URL, not remote get-url, which applies insteadOf rewrites.
    case "$origin" in
        "https://github.com/$repo"|"https://github.com/$repo.git"|\
        "git@github.com:$repo"|"git@github.com:$repo.git"|\
        "ssh://git@github.com/$repo"|"ssh://git@github.com/$repo.git") ;;
        *) die "Destination belongs to another repository: $destination (origin: $origin)." ;;
    esac
}

clone_dotfiles() {
    local repo="$1" destination="$2"
    if [[ -e "$destination" || -L "$destination" ]]; then
        printf 'Reusing existing checkout without pulling or changing its files: %s\n' "$destination"
        return 0
    fi

    mkdir -p -- "$(dirname -- "$destination")"
    printf 'Cloning %s into %s...\n' "$repo" "$destination"
    # Existing global config may rewrite HTTPS to SSH, require LFS, or use an
    # unavailable credential helper. Isolate this clone and explicitly use gh.
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 git \
        -c credential.helper= \
        -c 'credential.https://github.com.helper=!gh auth git-credential' \
        clone -- "https://github.com/$repo.git" "$destination"
}

main() {
    local repo='jackpinto/dot-files' destination="$HOME/projects/dot-files" distro
    while (( $# > 0 )); do
        case "$1" in
            --repo|--destination)
                (( $# >= 2 )) && [[ -n "$2" && "$2" != --* ]] || die "Missing value for $1."
                case "$1" in
                    --repo) repo="$2" ;;
                    --destination) destination="$2" ;;
                esac
                shift 2
                ;;
            -h|--help) usage; return 0 ;;
            *) die "Unknown argument: $1. Use --help for usage." ;;
        esac
    done
    [[ "$repo" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*/[a-zA-Z0-9_][a-zA-Z0-9_.-]*$ ]] ||
        die 'Repository must be OWNER/NAME on github.com, without a URL or .git suffix.'
    [[ "$repo" != *.git ]] || die 'Use OWNER/NAME without the .git suffix.'
    # Remove trailing slashes so an existing symlink is checked consistently.
    while [[ "$destination" != / && "$destination" == */ ]]; do
        destination="${destination%/}"
    done
    [[ "$destination" == /* ]] || destination="$PWD/$destination"
    (( EUID != 0 )) || die 'Run as your regular user, not root. Only package installation needs sudo.'

    distro=$(detect_distro)
    validate_destination "$repo" "$destination"
    install_dependencies "$distro"
    authenticate
    clone_dotfiles "$repo" "$destination"

    printf '\nBootstrap complete. Your dotfiles are at: %s\n' "$destination"
    printf 'Next, inspect the repository README and available installer flags:\n\n'
    printf '  cd %q\n' "$destination"
    printf '  git submodule update --init\n'
    printf '  (cd install && ./install.sh -h)\n\n'
    printf 'Choose the full setup steps from the README. SSH, GPG, Git identity, and Stow configuration can be set up there.\n'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
