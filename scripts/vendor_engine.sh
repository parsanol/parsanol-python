#!/usr/bin/env bash
# Vendor the engine into the wheel build (the cibuildwheel BEFORE_ALL).
#
# Runs INSIDE each wheel build environment — native runners, and the
# QEMU-emulated manylinux/musllinux containers for the cross-arch
# legs, where the emulated host is the target: rustup installs the
# emulated toolchain and cargo builds natively for it (the
# leptris/leptris-py#346 pattern). macOS builds both slices and lipos
# a universal2 engine; Windows legs pass PARSANOL_RUST_TARGET for the
# cross arches (the runner stays x64).
#
# The ENGINE SOURCE comes from the pinned release tree
# (parsanol-rs-version.txt carries the release COMMIT; the engine
# ships without tags), fetched here: cibuildwheel copies only the
# package directory into its build containers, and a submodule's
# content does not ride along — the leptris-py codeload pattern, with
# the commit bumped by every ride PR.
set -eu
cd "$(dirname "$0")/.."

echo "vendor_engine: uname -m=$(uname -m)"
if ! command -v cargo >/dev/null 2>&1; then
  case "$(uname -m)" in
    armv7l | armv8l)
      # sh.rustup.rs's install script detects the armv7-musl host and
      # 404s BEFORE rustup-init ever runs (no standalone installer
      # exists for that triple) - no rustup-init flag can matter. Fetch
      # the x86_64 GNU rustup-init directly: glibc-linked, runs native
      # on the x86_64 runner (the musl-flavored toolchain's binaries
      # need the absent musl loader), and the arch case below adds the
      # armv7 std target.
      curl --proto '=https' --tlsv1.2 -sSfL \
        https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init \
        -o /tmp/rustup-init
      chmod +x /tmp/rustup-init
      /tmp/rustup-init -y --profile minimal --default-host x86_64-unknown-linux-gnu
      ;;
    *)
      curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
      ;;
  esac
  export PATH="$HOME/.cargo/bin:$PATH"
fi

commit="$(cat parsanol-rs-version.txt)"
mkdir -p tmp/engine
curl -sL "https://codeload.github.com/parsanol/parsanol-rs/tar.gz/${commit}" \
  | tar xz --strip-components=1 -C tmp/engine

mkdir -p src/parsanol/lib

build() {
  extra="${1:-}"
  (cd tmp/engine && cargo build -p parsanol-ffi --release $extra)
}

# The runner-side cross link (the Windows-leg pattern, on Linux too):
# cargo-zigbuild supplies the foreign-musl C toolchain via zig cc; the
# emulated container never runs a toolchain installer, it only smokes
# the finished wheel.
build_cross() {
  target="${1:?cross mode needs PARSANOL_RUST_TARGET}"
  (cd tmp/engine && cargo zigbuild -p parsanol-ffi --release --target "$target")
}

os="$(uname -s)"
case "$os" in
  Linux)
    lib="libparsanol.so"
    out="tmp/engine/target/release/libparsanol.so"
    if [ -n "${PARSANOL_RUST_TARGET:-}" ]; then
      rustup target add "$PARSANOL_RUST_TARGET"
      build_cross "$PARSANOL_RUST_TARGET"
      out="tmp/engine/target/$PARSANOL_RUST_TARGET/release/libparsanol.so"
    else
    case "$(uname -m)" in
      x86_64 | aarch64)
        # the emulated container is the target: a plain host build
        build
        ;;
      i686)
        rustup target add i686-unknown-linux-gnu
        build "--target i686-unknown-linux-gnu"
        out="tmp/engine/target/i686-unknown-linux-gnu/release/libparsanol.so"
        ;;
      armv7l | armv8l)
        rustup target add armv7-unknown-linux-musleabihf
        build "--target armv7-unknown-linux-musleabihf"
        out="tmp/engine/target/armv7-unknown-linux-musleabihf/release/libparsanol.so"
        ;;
      ppc64le)
        rustup target add powerpc64le-unknown-linux-gnu
        build "--target powerpc64le-unknown-linux-gnu"
        out="tmp/engine/target/powerpc64le-unknown-linux-gnu/release/libparsanol.so"
        ;;
      s390x)
        rustup target add s390x-unknown-linux-gnu
        build "--target s390x-unknown-linux-gnu"
        out="tmp/engine/target/s390x-unknown-linux-gnu/release/libparsanol.so"
        ;;
      riscv64)
        # the riscv64 tier ships musl-only today (the glibc images left
        # quay entirely) - PARSANOL_MUSL=1 selects the musl triple
        if [ "${PARSANOL_MUSL:-}" = "1" ]; then
          rustup target add riscv64gc-unknown-linux-musl
          build "--target riscv64gc-unknown-linux-musl"
          out="tmp/engine/target/riscv64gc-unknown-linux-musl/release/libparsanol.so"
        else
          rustup target add riscv64gc-unknown-linux-gnu
          build "--target riscv64gc-unknown-linux-gnu"
          out="tmp/engine/target/riscv64gc-unknown-linux-gnu/release/libparsanol.so"
        fi
        ;;
      *)
        echo "unsupported linux arch $(uname -m)" >&2
        exit 1
        ;;
    esac
    fi
    cp "$out" "src/parsanol/lib/$lib"
    ;;

  Darwin)
    # universal2: both slices built, lipo'd into one engine
    rustup target add x86_64-apple-darwin aarch64-apple-darwin
    build "--target x86_64-apple-darwin"
    build "--target aarch64-apple-darwin"
    lipo -create \
      tmp/engine/target/x86_64-apple-darwin/release/libparsanol.dylib \
      tmp/engine/target/aarch64-apple-darwin/release/libparsanol.dylib \
      -output src/parsanol/lib/libparsanol.dylib
    ;;

  MINGW* | MSYS* | CYGWIN*)
    target="${PARSANOL_RUST_TARGET:-}"
    if [ -n "$target" ]; then
      rustup target add "$target"
      build "--target $target"
      out="tmp/engine/target/$target/release/parsanol.dll"
    else
      build
      out="tmp/engine/target/release/parsanol.dll"
    fi
    cp "$out" "src/parsanol/lib/parsanol.dll"
    ;;

  *)
    echo "unsupported OS $os" >&2
    exit 1
    ;;
esac

echo "vendored from parsanol-rs @${commit:0,12}: $(ls src/parsanol/lib)"
