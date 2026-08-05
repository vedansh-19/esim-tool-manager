#!/usr/bin/env bash
# End-to-end verification of the apt backend on real Ubuntu, via Docker.
#
# Runs the test suite, then performs a genuine install of Ngspice and re-checks
# it, inside a throwaway Ubuntu 24.04 container. The repository is mounted
# read-only so the container cannot modify the working tree.
#
# Usage:  ./scripts/verify-linux.sh [ubuntu-tag]
# Example: ./scripts/verify-linux.sh 22.04

set -euo pipefail

TAG="${1:-24.04}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v docker >/dev/null 2>&1; then
    echo "docker not found on PATH." >&2
    echo "On macOS the Docker Desktop CLI lives in" >&2
    echo "  /Applications/Docker.app/Contents/Resources/bin" >&2
    exit 1
fi

echo "Verifying against ubuntu:${TAG}"
echo

docker run --rm \
    -v "${REPO_ROOT}":/app:ro \
    -w /app \
    -e NO_COLOR=1 \
    "ubuntu:${TAG}" bash -lc '
set -e

echo "=== Environment ==="
. /etc/os-release && echo "${PRETTY_NAME}"
apt-get update -qq >/dev/null 2>&1
apt-get install -y -qq python3 >/dev/null 2>&1
python3 --version
echo "running as: $(whoami)"

echo
echo "=== Test suite ==="
python3 -m unittest discover -s tests 2>&1 | tail -4

echo
echo "=== Dependency check (before) ==="
# Exit code 1 is the expected, correct answer here: Ngspice is genuinely
# missing at this point. `|| true` keeps `set -e` from treating the tool
# working as intended as a script failure.
python3 -m esim_toolmanager check ngspice || true

echo
echo "=== Install ==="
python3 -m esim_toolmanager install ngspice --yes

echo
echo "=== Dependency check (after) ==="
python3 -m esim_toolmanager check ngspice

echo
echo "=== Audit log ==="
python3 -m esim_toolmanager log -n 5
'
