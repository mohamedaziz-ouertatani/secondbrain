"""Stand-in for app.sync.blackboard in the runner tests. FAKE_SYNC picks the behaviour: ok, slow, login, crash."""

import json
import os
import sys
import time

args = sys.argv[1:]
behaviour = os.environ.get("FAKE_SYNC", "ok")
dry = "--dry-run" in args


def out(e):
    print(json.dumps(e), flush=True)


print("args: " + " ".join(args), flush=True)  # not JSON: becomes a log event, and shows the flags used
out({"type": "courses", "probe": "--probe" in args, "courses": [
    {"name": "Probability 2", "folder": "Probability 2"}, {"name": "Engineering Internship", "folder": None}]})
if behaviour == "login":
    out({"type": "login_required"})
    sys.exit(3)
if behaviour == "slow":
    time.sleep(30)
out({"type": "file", "folder": "Probability 2", "path": "Probability 2/a.pdf", "kb": 12,
     "action": "would_download" if dry else "downloaded"})
out({"type": "file", "folder": "Probability 2", "path": "Probability 2/b.pdf", "action": "failed",
     "error": "download -> 500"})
if behaviour == "crash":
    out({"type": "error", "message": "boom"})
    sys.exit(1)
out({"type": "done", "mode": "preview" if dry else "sync", "files": 0 if dry else 1, "bytes": 0 if dry else 12288})
