# Dotfiles bootstrap

Get a fresh Linux machine authenticated with GitHub so it can clone the private
[`jackpinto/dot-files`](https://github.com/jackpinto/dot-files) repository.

This directory is a standalone project. Publish it as a **public repository**
so it is accessible before signing in. A release attached to the private dotfiles
repository would still require authentication.

## Usage

Download `bootstrap.sh` from the public repository or a public release, then run
it as your regular user:

```bash
bash bootstrap.sh
```

Defaults:

- Repository: `jackpinto/dot-files`
- Destination: `~/projects/dot-files`

Customize either:

```bash
bash bootstrap.sh --destination "$HOME/dotfiles"
bash bootstrap.sh --repo your-user/dot-files --destination "$HOME/projects/dot-files"
bash bootstrap.sh --help
```

Quote paths containing spaces. Relative destinations are resolved from your
current directory. The shell expands `~` in an unquoted path; use `$HOME` in a
quoted path.

## What it does

1. Detects Fedora, Ubuntu, or Arch Linux.
2. Installs missing Git and GitHub CLI packages, plus CA certificates, through
   the distribution's package manager. Installation uses `sudo`.
3. Reuses an authenticated GitHub session, or starts browser/device login with
   `gh auth login --hostname github.com --git-protocol https --web`.
4. Runs `gh auth setup-git --hostname github.com` to configure the GitHub
   credential helper in your global Git configuration.
5. Clones the dotfiles over HTTPS and prints the next setup commands.

On a headless machine, open the URL displayed by GitHub CLI on another device
and enter the device code. Choose an account with access to the private
repository; authorize organization SSO if required.

Ubuntu needs the `universe` repository enabled for its `gh` package. Arch needs
an initialized, current package database; update the system with `sudo pacman
-Syu` first if package downloads fail. The bootstrap uses `pacman -S` rather than
performing a database refresh that could cause a partial upgrade.

Existing checkouts with a matching origin are reused without fetching, pulling,
or changing their contents. Other existing destination paths are rejected.
SSH and HTTPS origin URLs are recognized when checking an existing checkout.

The clone ignores global/system Git configuration and explicitly uses GitHub
CLI credentials, so an existing HTTPS-to-SSH rewrite cannot block it. Your
regular Git configuration applies afterward; the full dotfiles setup can then
configure SSH access, GPG signing, Git identity, and your editor.

Authentication is handled by GitHub CLI using its normal credential storage.
The bootstrap package contains no credentials. It does not generate keys,
deploy Stow packages, or run the full dotfiles installer.

## After cloning

The script prints commands using the chosen destination. With the defaults:

```bash
cd "$HOME/projects/dot-files"
git submodule update --init
(cd install && ./install.sh -h)
```

Read the dotfiles README and choose the installation/configuration steps for
your machine.

## Checks

Python 3 is needed only for the tests, not for the bootstrap itself. Tests use
temporary homes and command stubs, with no network access or actual package
installation.

```bash
bash -n bootstrap.sh
python3 -m unittest discover -s tests -v
```

## Public release

The script is self-contained: `bootstrap.sh` and this README are enough to
distribute it. To build a small release archive locally:

```bash
mkdir -p dist
tar -czf dist/dot-files-bootstrap.tar.gz bootstrap.sh README.md
(cd dist && sha256sum dot-files-bootstrap.tar.gz > SHA256SUMS)
```

Upload the archive and `SHA256SUMS` as assets of a release in the public
bootstrap repository. Recipients can download both, run `sha256sum -c
SHA256SUMS`, extract the archive, and run `bash bootstrap.sh`. These checksums
detect corruption; they are not a substitute for trusting the release source.
