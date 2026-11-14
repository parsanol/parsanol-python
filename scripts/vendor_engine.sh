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
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal || true
  export PATH="$HOME/.cargo/bin:$PATH"
fi
if ! command -v cargo >/dev/null 2>&1; then
  # rustup ships no standalone installer for armv7-musl (rustup-init
  # detected an armv7 host and 404'd): retry with an explicit x86_64
  # host toolchain — the runner is x86_64, so rustc runs native and
  # only the link tools cross qemu. The emulated target is added by the
  # arch case below.
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-host x86_64-unknown-linux-musl
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

os="$(uname -s)"
case "$os" in
  Linux)
    lib="libparsanol.so"
    out="tmp/engine/target/release/libparsanol.so"
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
