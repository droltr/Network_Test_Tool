#!/bin/bash
# Start the test guide server if it is not running, then open the guide in the browser.
# Usage: launch.sh [session]   (default: the newest folder in tests/user/)
set -euo pipefail
DIR=$(cd "$(dirname "$0")" && pwd)
PORT=$(python3 -I -c "import json,sys; print(json.load(open(sys.argv[1])).get('port', 8765))" "$DIR/config.json")
URL=http://127.0.0.1:$PORT/
[ $# -ge 1 ] && URL="$URL?session=$1"
if ! curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then
    nohup python3 -I "$DIR/serve.py" >"${XDG_RUNTIME_DIR:-/tmp}/test-guide-$PORT.log" 2>&1 &
    for _ in $(seq 20); do curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 0.2; done
fi
xdg-open "$URL"
