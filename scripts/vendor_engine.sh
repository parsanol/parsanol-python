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
set -eu
cd "$(dirname "$0")/.."

if ! command -v cargo >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
  export PATH="$HOME/.cargo/bin:$PATH"
fi

mkdir -p src/parsanol/lib

os="$(uname -s)"
case "$os" in
  Linux)
    lib="libparsanol.so"
    out="parsanol-rs/target/release/libparsanol.so"
    case "$(uname -m)" in
      x86_64 | aarch64)
        # the emulated container is the target: a plain host build
        cargo build -p parsanol-ffi --release
        ;;
      i686)
        rustup target add i686-unknown-linux-gnu
        cargo build -p parsanol-ffi --release --target i686-unknown-linux-gnu
        out="parsanol-rs/target/i686-unknown-linux-gnu/release/libparsanol.so"
        ;;
      armv7l | armv8l)
        rustup target add armv7-unknown-linux-musleabihf
        cargo build -p parsanol-ffi --release --target armv7-unknown-linux-musleabihf
        out="parsanol-rs/target/armv7-unknown-linux-musleabihf/release/libparsanol.so"
        ;;
      ppc64le)
        rustup target add powerpc64le-unknown-linux-gnu
        cargo build -p parsanol-ffi --release --target powerpc64le-unknown-linux-gnu
        out="parsanol-rs/target/powerpc64le-unknown-linux-gnu/release/libparsanol.so"
        ;;
      s390x)
        rustup target add s390x-unknown-linux-gnu
        cargo build -p parsanol-ffi --release --target s390x-unknown-linux-gnu
        out="parsanol-rs/target/s390x-unknown-linux-gnu/release/libparsanol.so"
        ;;
      riscv64)
        rustup target add riscv64gc-unknown-linux-gnu
        cargo build -p parsanol-ffi --release --target riscv64gc-unknown-linux-gnu
        out="parsanol-rs/target/riscv64gc-unknown-linux-gnu/release/libparsanol.so"
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
    cargo build -p parsanol-ffi --release --target x86_64-apple-darwin
    cargo build -p parsanol-ffi --release --target aarch64-apple-darwin
    lipo -create \
      parsanol-rs/target/x86_64-apple-darwin/release/libparsanol.dylib \
      parsanol-rs/target/aarch64-apple-darwin/release/libparsanol.dylib \
      -output src/parsanol/lib/libparsanol.dylib
    ;;

  MINGW* | MSYS* | CYGWIN*)
    target="${PARSANOL_RUST_TARGET:-}"
    if [ -n "$target" ]; then
      rustup target add "$target"
      cargo build -p parsanol-ffi --release --target "$target"
      out="parsanol-rs/target/$target/release/parsanol.dll"
    else
      cargo build -p parsanol-ffi --release
      out="parsanol-rs/target/release/parsanol.dll"
    fi
    cp "$out" "src/parsanol/lib/parsanol.dll"
    ;;

  *)
    echo "unsupported OS $os" >&2
    exit 1
    ;;
esac

echo "vendored $(ls src/parsanol/lib)"
