#!/bin/sh
# Network Test Tool launcher for Linux x86_64 and macOS arm64 (run without installing).
#
#   curl -fsSL https://droltr.github.io/Network_Test_Tool/run.sh | sh
#
# Downloads the release binary into ~/.cache/network-test-tool/bin/<tag>/ (reused on
# later runs), verifies its SHA-256 against the release's SHA256SUMS.txt and starts it
# in the background. No root, no system changes.
#
# Optional environment variables (put them after the pipe: ... | NTT_NO_LAUNCH=1 sh):
#   NTT_VERSION=v0.8.1   Use this release tag instead of the latest release.
#   NTT_NO_LAUNCH=1      Download and verify only, do not start the app.
#   NTT_SKIP_HASH=1      Run even if the release has no SHA256SUMS.txt (not recommended).
#   NTT_SUMS_URL=<url>   Read checksums from this URL or local file (testing).
#   NTT_PLATFORM=...     Override platform detection: linux-x86_64 or macos-arm64 (testing).
#
# Everything runs inside main(), so a truncated download executes nothing.
# Keep this file ASCII-only and POSIX sh.

REPO="droltr/Network_Test_Tool"
RELEASES_PAGE="https://github.com/$REPO/releases/latest"
SUMS_NAME="SHA256SUMS.txt"
KEEP_VERSIONS=2

say() { printf '  %s\n' "$*"; }
fail() {
    printf '\n  ERROR: %s\n  Manual download: %s\n\n' "$*" "$RELEASES_PAGE" >&2
    exit 1
}
flag() {
    case "$1" in ''|0|false|no) return 1 ;; *) return 0 ;; esac
}

# fetch URL [OUTFILE]: print to stdout or write to OUTFILE. Returns non-zero on HTTP errors.
fetch() {
    if command -v curl >/dev/null 2>&1; then
        if [ -n "$2" ]; then
            curl -fsSL --retry 2 --connect-timeout 20 -H "User-Agent: NetworkTestTool-launcher" -o "$2" "$1"
        else
            curl -fsSL --retry 2 --connect-timeout 20 -H "User-Agent: NetworkTestTool-launcher" "$1"
        fi
    elif command -v wget >/dev/null 2>&1; then
        if [ -n "$2" ]; then
            wget -q -T 30 -U "NetworkTestTool-launcher" -O "$2" "$1"
        else
            wget -q -T 30 -U "NetworkTestTool-launcher" -O - "$1"
        fi
    else
        fail "Neither curl nor wget is installed."
    fi
}

latest_tag_from_redirect() {
    # github.com/<repo>/releases/latest redirects to .../releases/tag/<tag>.
    if command -v curl >/dev/null 2>&1; then
        final=$(curl -fsSLI -o /dev/null -w '%{url_effective}' --connect-timeout 20 "$RELEASES_PAGE") || return 1
    else
        final=$(wget -q -S --spider "$RELEASES_PAGE" 2>&1 | sed -n 's/^ *[Ll]ocation: *//p' | tail -n 1 | tr -d '\r') || return 1
    fi
    case "$final" in
        */releases/tag/*) printf '%s\n' "${final##*/releases/tag/}" ;;
        *) return 1 ;;
    esac
}

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        fail "Neither sha256sum nor shasum is installed; cannot verify the download."
    fi
}

# verify_file PATH: true when PATH exists and matches every checksum we have
# (SHA256SUMS.txt and GitHub's asset digest). Uses the globals expected and api_digest.
verify_file() {
    [ -f "$1" ] || return 1
    [ -n "$expected$api_digest" ] || return 0
    vf_hash=$(sha256_of "$1")
    for vf_want in "$expected" "$api_digest"; do
        if [ -n "$vf_want" ] && [ "$vf_hash" != "$vf_want" ]; then
            return 1
        fi
    done
    return 0
}

main() {
    printf '\n  Network Test Tool launcher\n'

    platform="${NTT_PLATFORM:-}"
    if [ -z "$platform" ]; then
        os=$(uname -s); arch=$(uname -m)
        case "$os/$arch" in
            Linux/x86_64|Linux/amd64) platform="linux-x86_64" ;;
            Darwin/arm64|Darwin/aarch64) platform="macos-arm64" ;;
            Darwin/*) fail "Only Apple silicon (arm64) Macs have a prebuilt binary." ;;
            Linux/*) fail "Only Linux x86_64 has a prebuilt binary (this machine is $arch)." ;;
            *) fail "Unsupported system: $os $arch. On Windows use: irm https://droltr.github.io/Network_Test_Tool/run.ps1 | iex" ;;
        esac
    fi

    # ---- 1. Resolve the release ----------------------------------------------------
    tag="${NTT_VERSION:-}"
    case "$tag" in ''|v*) ;; *) tag="v$tag" ;; esac
    if [ -n "$tag" ]; then
        say "Looking up release $tag on GitHub..."
        api="https://api.github.com/repos/$REPO/releases/tags/$tag"
    else
        say "Looking up the latest release on GitHub..."
        api="https://api.github.com/repos/$REPO/releases/latest"
    fi
    json=$(fetch "$api" 2>/dev/null) || json=""
    if [ -n "$json" ]; then
        # Flatten the JSON so each key/value pair is on its own line; no jq needed.
        flat=$(printf '%s' "$json" | tr ',{}' '\n\n\n')
        tag=$(printf '%s\n' "$flat" | sed -n 's/^ *"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)
        urls=$(printf '%s\n' "$flat" | sed -n 's/^ *"browser_download_url": *"\([^"]*\)".*/\1/p')
        exe_url=$(printf '%s\n' "$urls" | grep -E "/NetworkTestTool-[^/]+-$platform\$" | head -n 1)
        sums_url=$(printf '%s\n' "$urls" | grep -E "/$SUMS_NAME\$" | head -n 1)
        [ -n "$tag" ] || fail "Unexpected answer from the GitHub API."
        [ -n "$exe_url" ] || fail "Release $tag has no $platform build."
        exe_name="${exe_url##*/}"
        # GitHub's own SHA-256 of the asset ("digest" field), checked in addition to SHA256SUMS.txt.
        api_digest=$(printf '%s\n' "$flat" | awk -v n="$exe_name" '
            /^ *"url": *"[^"]*\/releases\/assets\// { found = 0 }
            /^ *"name": *"/ { v = $0; sub(/^ *"name": *"/, "", v); sub(/".*/, "", v); if (v == n) found = 1 }
            found && /^ *"digest": *"sha256:[0-9a-fA-F]/ { v = $0; sub(/^ *"digest": *"sha256:/, "", v); print tolower(substr(v, 1, 64)); exit }')
    else
        say "GitHub API unavailable; using direct release links."
        if [ -z "$tag" ]; then
            tag=$(latest_tag_from_redirect) || fail "Cannot reach GitHub. Check your internet connection, proxy or firewall."
        elif ! fetch "https://github.com/$REPO/releases/tag/$tag" >/dev/null 2>&1; then
            fail "Release $tag was not found, or GitHub cannot be reached."
        fi
        exe_name="NetworkTestTool-${tag#v}-$platform"
        exe_url="https://github.com/$REPO/releases/download/$tag/$exe_name"
        sums_url="https://github.com/$REPO/releases/download/$tag/$SUMS_NAME"
    fi
    [ -n "${NTT_SUMS_URL:-}" ] && sums_url="$NTT_SUMS_URL"
    say "Release: $tag ($exe_name)"

    # ---- 2. Expected checksum ------------------------------------------------------
    expected=""
    api_digest="${api_digest:-}"
    if [ -n "$sums_url" ]; then
        if [ -f "$sums_url" ]; then
            sums=$(cat "$sums_url")
        else
            sums=$(fetch "${sums_url#file://}" 2>/dev/null) || sums=""
        fi
        if [ -n "$sums" ]; then
            expected=$(printf '%s\n' "$sums" | tr -d '\r' | awk -v n="$exe_name" '{f=$2; sub(/^\*/, "", f); if (f == n && length($1) == 64) {print tolower($1); exit}}')
            [ -n "$expected" ] || fail "$SUMS_NAME of $tag has no entry for $exe_name. Refusing to run an unverified file."
        fi
    fi
    if [ -z "$expected" ]; then
        if flag "${NTT_SKIP_HASH:-}"; then
            say "WARNING: $tag has no $SUMS_NAME; NTT_SKIP_HASH=1 is set, continuing without it."
        else
            fail "Release $tag has no $SUMS_NAME, so the download cannot be verified. Wait for a newer release, download it manually, or rerun with NTT_SKIP_HASH=1 to run it unverified at your own risk."
        fi
    fi

    if [ -n "$expected$api_digest" ] && ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
        fail "Neither sha256sum nor shasum is installed; cannot verify the download."
    fi

    # ---- 3. Download (or reuse the cache) ------------------------------------------
    bin_dir="${XDG_CACHE_HOME:-$HOME/.cache}/network-test-tool/bin"
    ver_dir="$bin_dir/$(printf '%s' "$tag" | tr -c 'A-Za-z0-9._-' '_')"
    exe_path="$ver_dir/$exe_name"
    mkdir -p "$ver_dir" || fail "Cannot create $ver_dir"

    # Remove partial downloads left behind by interrupted runs (older than a day).
    find "$ver_dir" -type f -name '*.part*' -mtime +0 -exec rm -f {} + 2>/dev/null

    if verify_file "$exe_path"; then
        say "Using the cached copy."
    else
        # A unique temp file per run, so parallel runs never write into the same file.
        part=$(mktemp "$exe_path.part.XXXXXX" 2>/dev/null) || part="$exe_path.part.$$"
        say "Downloading..."
        if ! fetch "$exe_url" "$part"; then
            rm -f "$part"
            fail "Download failed: $exe_url"
        fi
        if [ -n "$expected$api_digest" ]; then
            actual=$(sha256_of "$part")
            for want in "$expected" "$api_digest"; do
                if [ -n "$want" ] && [ "$actual" != "$want" ]; then
                    rm -f "$part"
                    fail "Checksum mismatch for $exe_name (expected $want, got $actual). The file was deleted."
                fi
            done
            if [ -n "$expected" ]; then say "SHA-256 verified against $SUMS_NAME."
            else say "SHA-256 verified against the GitHub asset digest only."; fi
        fi
        chmod +x "$part"
        # rename() is atomic on the same file system; a verified copy from another run
        # is simply replaced by this verified copy.
        mv -f "$part" "$exe_path" || { rm -f "$part"; fail "Cannot write $exe_path"; }
    fi
    chmod +x "$exe_path" 2>/dev/null
    touch "$ver_dir"

    # ---- 4. Keep only the newest versions ------------------------------------------
    # shellcheck disable=SC2012
    ls -1t "$bin_dir" 2>/dev/null | tail -n +$((KEEP_VERSIONS + 1)) | while IFS= read -r old; do
        [ -n "$old" ] && rm -rf "${bin_dir:?}/$old"
    done

    # ---- 5. Launch -----------------------------------------------------------------
    # Check the final file once more right before using it.
    verify_file "$exe_path" || fail "$exe_path changed or failed verification just before launch. Run the command again."
    if flag "${NTT_NO_LAUNCH:-}"; then
        say "NTT_NO_LAUNCH is set; not starting. File: $exe_path"
        return 0
    fi
    if [ "$platform" = "linux-x86_64" ] && [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}${QT_QPA_PLATFORM:-}" ]; then
        say "WARNING: no graphical session found (DISPLAY/WAYLAND_DISPLAY unset); the app may not open."
    fi
    say "Starting Network Test Tool..."
    (cd "$ver_dir" && nohup "$exe_path" >/dev/null 2>&1 &)
    printf '\n'
}

main "$@"
