#!/usr/bin/env bash
#
# Runs the ict-site-rag-guards test suite. Linux and macOS counterpart of
# run-tests.ps1, with the same two modes and the same exit codes.
#
#   --unit      Runs everything under tests/unit with the local Python
#               interpreter. Fast, no container, no core dependency: those
#               tests import nothing from `cat`. This is the loop to use while
#               writing checks.
#
#   (default)   Runs the whole suite inside the running container. Needed by
#               tests/integration, which imports the plugin module and
#               therefore needs `cat` and its dependencies importable. The
#               tests still never contact the running Cat: the container is
#               used as an interpreter, not as a server.
#
#   --detailed  Passes -v to pytest, listing every test name.
#
# Exit code is the one pytest returns, so this script can be reused in a hook
# or in CI.

set -uo pipefail

# Not using `set -e`: this script inspects the exit codes of the commands it
# runs, and an early exit would hide the diagnostics below.

service='cheshire-cat-core'

# Where the plugin folder appears inside the container: compose mounts ./core on /app.
plugin_in_container='/app/cat/plugins/ict-site-rag-guards'

plugin_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

unit_only=0
pytest_args=()

usage() {
	cat <<'EOF'
Usage: ./run-tests.sh [--unit] [--detailed]

  --unit      tests/unit only, local interpreter, no container
  --detailed  one line per test
  --help      this text

With no option, runs the whole suite inside the container.
EOF
}

while [ $# -gt 0 ]; do
	case "$1" in
		-u|--unit)     unit_only=1 ;;
		-d|--detailed) pytest_args+=('-v') ;;
		-h|--help)     usage; exit 0 ;;
		*)
			echo "Unknown option: $1" >&2
			usage >&2
			exit 2
			;;
	esac
	shift
done

# --- local mode: pure logic only ------------------------------------------------

if [ "$unit_only" -eq 1 ]; then
	echo "Unit tests (pure logic), local interpreter"

	# The first interpreter that can import pytest, not simply the first one
	# found: several systems ship a `python3` shim that has no packages, and
	# picking it would report a missing pytest that is installed elsewhere.
	python_bin=''
	first_found=''
	for candidate in python3 python py; do
		command -v "$candidate" >/dev/null 2>&1 || continue
		[ -n "$first_found" ] || first_found="$candidate"
		if "$candidate" -c 'import pytest' >/dev/null 2>&1; then
			python_bin="$candidate"
			break
		fi
	done

	if [ -z "$python_bin" ]; then
		if [ -z "$first_found" ]; then
			echo "No Python interpreter found in PATH." >&2
		else
			echo "No interpreter with pytest found (tried: python3, python, py)." >&2
			echo "Install it once with:  $first_found -m pip install pytest" >&2
		fi
		echo "Or use the suite in the container:  ./run-tests.sh" >&2
		exit 1
	fi

	cd "$plugin_dir" || exit 1
	"$python_bin" -m pytest tests/unit "${pytest_args[@]}"
	exit $?
fi

# --- container mode: whole suite ------------------------------------------------

# The compose file is not passed with -f: we change directory to it instead, so
# no host path is ever handed to docker. Under Git Bash a POSIX path like
# /c/... would reach the Windows docker binary as C:\c\..., and fail.
compose_dir="$plugin_dir/../../../.."
if [ ! -f "$compose_dir/compose.yml" ]; then
	echo "compose.yml not found where expected:" >&2
	echo "  $compose_dir/compose.yml" >&2
	echo "This script assumes the plugin lives in core/cat/plugins/ of the Stregatto project." >&2
	exit 1
fi
cd "$compose_dir" || exit 1

# Compose v2 is a docker subcommand; older installations still ship the
# standalone v1 binary.
if docker compose version >/dev/null 2>&1; then
	compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
	compose=(docker-compose)
else
	echo "Neither 'docker compose' nor 'docker-compose' is available." >&2
	echo "Run only the unit tests instead:  ./run-tests.sh --unit" >&2
	exit 1
fi

container_id="$("${compose[@]}" ps -q "$service" 2>/dev/null)"
if [ -z "$container_id" ]; then
	echo "The '$service' container is not running." >&2
	echo "Start it from $(pwd) with:  ${compose[*]} up -d" >&2
	echo "Or run only the unit tests:  ./run-tests.sh --unit" >&2
	exit 1
fi

echo "Full suite (unit + contract) in the '$service' container"

# -w is required: pytest.ini, and the pythonpath it declares, are resolved from
# the plugin folder. The core is reached through the "/app" entry of that same
# pythonpath, so no PYTHONPATH variable is needed here.
#
# MSYS_NO_PATHCONV keeps Git Bash on Windows from rewriting the -w path into a
# Windows one, which makes docker fail with "Cwd must be an absolute path". It
# is simply an unused variable on Linux and macOS.
MSYS_NO_PATHCONV=1 "${compose[@]}" exec -T \
	-w "$plugin_in_container" "$service" python -m pytest "${pytest_args[@]}"
exit $?
