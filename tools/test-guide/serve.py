#!/usr/bin/env python3
"""Serve the interactive user-test guide on localhost and save submitted reports to the project.

Layout (relative to the project root):
  tools/test-guide/      this engine (index.html, serve.py, launch.sh, config.json: project, port)
  tests/user/<NNN-date-slug>/tests.json    one numbered folder per tested change (kept in git)
  .private/test-reports/<session>/<project>__<session>__runNN.{json,md}    reports (never published)

Safety rules enforced here:
  * The project name in config.json must equal the project folder name; otherwise the engine was
    copied to another project without being set up and the server refuses to start.
  * Pre-flight checks (the "preflight" list in tests.json) are run before testing: right project,
    right version installed, running version equals the tested version. A report for a failed
    pre-flight is accepted only with an explicit acknowledgement, and the results are stored in it.
  * A report is accepted only if it names this project and its path, this session, and the SHA-256 of
    the tests.json the page loaded (edited procedures are never mixed with old results).
  * Report files are created exclusively and numbered run01, run02, ...; nothing is overwritten.
  * The server listens on 127.0.0.1 only, rejects requests from other web pages and exits after
    IDLE_TIMEOUT seconds without requests.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
IDLE_TIMEOUT = 3 * 60 * 60
MAX_BODY = 1024 * 1024
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

# Pre-flight checks run these programs without a shell, from the project folder, read-only by
# convention. Privilege escalation and anything not listed here is refused.
PREFLIGHT_PROGRAMS = {
    "cat",
    "diff",
    "grep",
    "head",
    "id",
    "journalctl",
    "ls",
    "pgrep",
    "ps",
    "python3",
    "readlink",
    "sha256sum",
    "ss",
    "stat",
    "tail",
    "test",
    "uname",
    "git",
    "systemctl",
}
PREFLIGHT_SUBCOMMANDS = {
    "git": {"describe", "diff", "log", "rev-parse", "status"},
    "systemctl": {"is-active", "is-enabled", "show", "status"},
}
PREFLIGHT_TIMEOUT = 10
PREFLIGHT_OUTPUT = 400

GUIDE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = GUIDE_DIR.parent.parent
SESSIONS_DIR = PROJECT_DIR / "tests" / "user"
REPORT_ROOT = PROJECT_DIR / ".private" / "test-reports"
CONFIG = json.loads((GUIDE_DIR / "config.json").read_text(encoding="utf-8"))
PORT = int(CONFIG.get("port", 8765))
PROJECT = str(CONFIG.get("project", ""))
ORIGIN = f"http://{HOST}:{PORT}"

last_request = time.monotonic()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def list_sessions():
    """Session folders that contain a tests.json, newest (highest sequence number) first."""
    found = []
    for path in sorted(SESSIONS_DIR.glob("*/tests.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            count = sum(len(s["tests"]) for s in data["sections"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        found.append(
            {
                "name": path.parent.name,
                "title": data.get("title", path.parent.name),
                "change": data.get("change", ""),
                "target": data.get("target", ""),
                "project": data.get("project", ""),
                "tests": count,
            }
        )
    return found


def session_file(name):
    if not name or not SESSION_RE.match(name):
        return None
    path = SESSIONS_DIR / name / "tests.json"
    return path if path.is_file() else None


def project_info():
    return {"project": PROJECT, "path": str(PROJECT_DIR), "report_dir": str(REPORT_ROOT)}


def argv_problem(argv):
    """Why a pre-flight command is refused, or None when it may run."""
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        return "argv must be a non-empty list of strings"
    program = argv[0]
    if program not in PREFLIGHT_PROGRAMS:
        return f"program {program!r} is not allowed in pre-flight checks"
    allowed = PREFLIGHT_SUBCOMMANDS.get(program)
    if allowed and (len(argv) < 2 or argv[1] not in allowed):
        return f"{program} may only be used with: {', '.join(sorted(allowed))}"
    return None


def run_check(check, target_version):
    """Run one declared check. Returns {id, title, ok, info, detail, command}."""

    def fill(text):
        return text.replace("{{target_version}}", target_version)

    result = {
        "id": str(check.get("id", "")),
        "title": fill(str(check.get("title", ""))),
        "info": bool(check.get("info", False)),
        "hint": fill(str(check.get("hint", ""))),
    }
    argv = [fill(a) for a in check.get("argv", [])] if isinstance(check.get("argv"), list) else []
    result["command"] = " ".join(argv)
    problem = argv_problem(argv)
    if problem:
        return {**result, "ok": False, "detail": problem}
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin"),
        "HOME": os.environ.get("HOME", "/"),
        "LC_ALL": "C",
    }
    try:
        done = subprocess.run(
            argv,
            cwd=PROJECT_DIR,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=int(check.get("timeout", PREFLIGHT_TIMEOUT)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {**result, "ok": False, "detail": "timed out"}
    except OSError as err:
        return {**result, "ok": False, "detail": f"could not run: {err}"}
    out = done.stdout.strip()
    reasons = []
    if done.returncode != int(check.get("expect_exit", 0)):
        reasons.append(f"exit code {done.returncode}")
    pattern = check.get("expect")
    if pattern and not re.search(fill(pattern), out, re.MULTILINE):
        reasons.append(f"output does not match /{fill(pattern)}/")
    if check.get("expect_empty") and out:
        reasons.append("output should be empty")
    shown = (out or done.stderr.strip())[:PREFLIGHT_OUTPUT] or "(no output)"
    ok = not reasons or result["info"]
    return {
        **result,
        "ok": ok,
        "detail": shown + (" [" + "; ".join(reasons) + "]" if reasons else ""),
    }


def run_preflight(session):
    """Identity checks plus the session's declared checks. 'ok' ignores info-only checks."""
    data = json.loads(session_file(session).read_text(encoding="utf-8"))
    target_version = str(data.get("target_version", ""))
    results = [
        {
            "id": "project",
            "title": "Tests belong to this project",
            "info": False,
            "hint": "Open the guide from the project folder you are testing.",
            "command": "",
            "ok": data.get("project") == PROJECT == PROJECT_DIR.name,
            "detail": f"server: {PROJECT} ({PROJECT_DIR}); tests.json: {data.get('project', '(none)')}",
        }
    ]
    results += [
        run_check(c, target_version) for c in data.get("preflight", []) if isinstance(c, dict)
    ]
    return {
        "ok": all(r["ok"] or r["info"] for r in results),
        "target_version": target_version,
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "results": results,
    }


def to_markdown(report):
    lines = [
        f"# Test report: {report['project']}, {report['session']}, run {report['run']:02d}",
        "",
    ]
    lines += [
        f"- Project: {report['project']} ({report['project_path']})",
        f"- Session: {report['session']}",
        f"- Created: {report['created']}",
    ]
    if report.get("target"):
        lines.append(f"- Target: {report['target']}")
    lines.append(f"- tests.json SHA-256: {report['tests_sha256']}")
    pre = report["preflight"]
    verdict = "all passed" if pre["ok"] else "FAILED (acknowledged by the tester)"
    lines += [f"- Pre-flight: {verdict}", "", "## Pre-flight checks", ""]
    lines += ["| Check | Result | Detail |", "|---|---|---|"]
    for r in pre["results"]:
        mark = "ok" if r["ok"] else "FAIL"
        lines.append(
            f"| {r['title']} | {mark} | {r['detail'].replace('|', '/').replace(chr(10), ' ')} |"
        )
    lines.append("")
    counts = {}
    for section in report["results"]:
        for test in section["tests"]:
            counts[test["result"]] = counts.get(test["result"], 0) + 1
    lines += ["Summary: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), ""]
    for section in report["results"]:
        lines += [
            f"## {section['section']}",
            "",
            "| ID | Test | Result | Note |",
            "|---|---|---|---|",
        ]
        for t in section["tests"]:
            note = t["note"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {t['id']} | {t['title']} | {t['result']} | {note} |")
        lines.append("")
    if report.get("general_notes"):
        lines += ["## General notes", "", report["general_notes"], ""]
    return "\n".join(lines)


def save_report(report):
    """Write the next free run number for this session; files are created exclusively."""
    out_dir = REPORT_ROOT / report["session"]
    out_dir.mkdir(parents=True, exist_ok=True)
    stem_base = f"{PROJECT}__{report['session']}__run"
    numbers = [
        int(m.group(1))
        for p in out_dir.glob(stem_base + "*.json")
        if (m := re.search(r"run(\d+)\.json$", p.name))
    ]
    run = 1 + max(numbers, default=0)
    while True:
        report["run"] = run
        stem = f"{stem_base}{run:02d}"
        try:
            with open(out_dir / f"{stem}.json", "x", encoding="utf-8") as handle:
                handle.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
            break
        except FileExistsError:
            run += 1
    with open(out_dir / f"{stem}.md", "x", encoding="utf-8") as handle:
        handle.write(to_markdown(report))
    rel = out_dir.relative_to(PROJECT_DIR)
    return [f"{rel}/{stem}.json", f"{rel}/{stem}.md"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")

    def send_bytes(self, code, content_type, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, payload):
        self.send_bytes(code, "application/json", json.dumps(payload).encode())

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY:
            self.send_json(413, {"error": "invalid body size"})
            return None
        try:
            return json.loads(self.rfile.read(length))
        except ValueError:
            self.send_json(400, {"error": "invalid JSON"})
            return None

    def do_GET(self):
        global last_request
        last_request = time.monotonic()
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self.send_bytes(
                200, "text/html; charset=utf-8", (GUIDE_DIR / "index.html").read_bytes()
            )
        elif url.path == "/api/info":
            self.send_json(200, project_info())
        elif url.path == "/api/sessions":
            self.send_json(200, list_sessions())
        elif url.path == "/tests.json":
            path = session_file(parse_qs(url.query).get("session", [""])[0])
            if path is None:
                self.send_json(404, {"error": "unknown session"})
                return
            body = path.read_bytes()  # re-read on every load
            self.send_bytes(
                200,
                "application/json",
                body,
                {"X-Tests-Sha256": sha256(body), "Access-Control-Expose-Headers": "X-Tests-Sha256"},
            )
        else:
            self.send_error(404)

    def do_POST(self):
        global last_request
        last_request = time.monotonic()
        if self.path not in ("/api/report", "/api/preflight"):
            self.send_json(404, {"error": "not found"})
            return
        if self.headers.get("Origin") != ORIGIN:  # reject requests sent by other web pages
            self.send_json(403, {"error": "origin not allowed"})
            return
        body = self.read_json()
        if body is None:
            return
        if self.path == "/api/preflight":
            self.handle_preflight(body)
        else:
            self.handle_report(body)

    def handle_preflight(self, body):
        if not isinstance(body, dict) or session_file(body.get("session")) is None:
            self.send_json(400, {"error": "unknown session"})
            return
        self.send_json(200, run_preflight(body["session"]))

    def handle_report(self, report):
        try:
            report["results"][0]["tests"][0]["result"]
            session = report["session"]
            wrong_project = report["project"] != PROJECT or report["project_path"] != str(
                PROJECT_DIR
            )
            sent_sha = report["tests_sha256"]
        except (KeyError, IndexError, TypeError):
            self.send_json(400, {"error": "invalid report"})
            return
        if wrong_project:
            self.send_json(
                409, {"error": f"report is for another project; this server belongs to {PROJECT}"}
            )
            return
        path = session_file(session)
        if path is None:
            self.send_json(400, {"error": "unknown session"})
            return
        if sent_sha != sha256(path.read_bytes()):
            self.send_json(
                409, {"error": "tests.json changed since this page was loaded; reload the page"}
            )
            return
        preflight = run_preflight(session)  # re-run now: never trust the page for this
        if not preflight["ok"] and not report.get("ack_preflight_failure"):
            self.send_json(
                409, {"error": "pre-flight checks failed; acknowledge them or fix the setup"}
            )
            return
        report["preflight"] = preflight
        report["ack_preflight_failure"] = (
            bool(report.get("ack_preflight_failure")) and not preflight["ok"]
        )
        self.send_json(200, {"files": save_report(report), "preflight_ok": preflight["ok"]})


def watchdog(server):
    while time.monotonic() - last_request < IDLE_TIMEOUT:
        time.sleep(30)
    server.shutdown()


def main():
    if not PROJECT or PROJECT != PROJECT_DIR.name:
        sys.exit(
            f"config.json names project {PROJECT!r} but this folder is {PROJECT_DIR.name!r}: "
            "set up the guide for this project with .MD/new_user_test.sh before starting it."
        )
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=watchdog, args=(server,), daemon=True).start()
    print(f"Test guide for {PROJECT}: {ORIGIN}/  reports: {REPORT_ROOT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
