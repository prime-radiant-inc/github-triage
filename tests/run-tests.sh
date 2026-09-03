#!/bin/sh
# Run the github-triage plugin test suite. Python stdlib only; no network, no real gh.
# Usage: tests/run-tests.sh [unittest args...]   e.g. tests/run-tests.sh -k labels
set -e
cd "$(dirname "$0")"
exec python3 -m unittest discover -s . -t . -p 'test_*.py' -v "$@"
