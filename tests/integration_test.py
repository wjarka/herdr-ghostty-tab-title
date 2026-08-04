#!/usr/bin/env python3
"""End-to-end test: does the title actually reach the terminal?

Spins up a throwaway herdr session inside a pty, runs the watcher against that
session's socket, synthesises agent states with `pane.report_agent`, and asserts
on the OSC 0 title sequences herdr writes to the pty. That pty stands in for the
Ghostty tab, so a pass here means Ghostty gets the same bytes.

Requires: herdr on PATH, and no HERDR_* env (the script strips it for the child;
nested herdr is refused otherwise).

Run: python3 tests/integration_test.py
"""

import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHER = os.path.join(ROOT, "bin", "herdr-ghostty-title")
SESSION = "hgt-itest"
SESSION_DIR = os.path.expanduser(f"~/.config/herdr/sessions/{SESSION}")
SOCK = os.path.join(SESSION_DIR, "herdr.sock")
LABEL = "itest"

OSC_TITLE = re.compile(rb"\x1b\][012];(.*?)(?:\x07|\x1b\\)", re.S)

BLOCKED, DONE, WORKING, IDLE = "\U0001F534", "\U0001F7E2", "\U0001F7E1", "⚪"


class Fail(AssertionError):
    pass


# --------------------------------------------------------------------------- #


def call(method, params=None, sock=SOCK, timeout=5.0):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(sock)
    try:
        s.sendall(
            (json.dumps({"id": "it", "method": method, "params": params or {}}) + "\n").encode()
        )
        line = s.makefile("r", encoding="utf-8").readline()
    finally:
        s.close()
    reply = json.loads(line)
    if "error" in reply:
        raise Fail(f"{method} failed: {reply['error']}")
    return reply.get("result", {})


class Session:
    """A herdr session running under a pty we can read titles from."""

    def __init__(self):
        self.pid = None
        self.fd = None
        self.titles = []
        self.buf = bytearray()

    def start(self, wipe=True):
        if wipe and os.path.exists(SESSION_DIR):
            shutil.rmtree(SESSION_DIR, ignore_errors=True)
        pid, fd = pty.fork()
        if pid == 0:
            os.environ["TERM"] = "xterm-256color"
            for key in list(os.environ):
                if key.startswith("HERDR_"):
                    del os.environ[key]
            os.environ.pop("TMUX", None)
            os.execvp("herdr", ["herdr", "--session", SESSION])
            os._exit(127)
        self.pid, self.fd = pid, fd
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))

        deadline = time.time() + 25
        while time.time() < deadline:
            self.pump(0.3)
            if os.path.exists(SOCK):
                try:
                    call("ping")
                    self.pump(1.5)  # let the UI finish its first paint
                    return
                except (OSError, json.JSONDecodeError):
                    pass
        raise Fail(f"session {SESSION} did not come up; saw: {bytes(self.buf)[:400]!r}")

    def pump(self, duration):
        end = time.time() + duration
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if self.fd not in r:
                continue
            try:
                data = os.read(self.fd, 65536)
            except OSError:
                return
            if not data:
                return
            self.buf.extend(data)
            for match in OSC_TITLE.finditer(data):
                self.titles.append(match.group(1).decode("utf-8", "replace"))

    def wait_for_title(self, predicate, timeout=8.0, what=""):
        end = time.time() + timeout
        while time.time() < end:
            self.pump(0.2)
            for title in reversed(self.titles):
                if predicate(title):
                    return title
        raise Fail(f"timed out waiting for {what}; titles seen: {self.titles[-8:]}")

    def stop(self, remove_dir=True):
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        time.sleep(0.5)
        if os.path.exists(SOCK):
            try:
                call("server.stop")
            except (OSError, Fail, json.JSONDecodeError):
                pass
        time.sleep(0.5)
        if remove_dir:
            shutil.rmtree(SESSION_DIR, ignore_errors=True)


_SEQ = [0]


def report(pane_id, state):
    """Report a synthetic agent state.

    herdr needs a monotonically increasing `seq` from a given source before it
    will accept a de-escalation (e.g. blocked -> idle), so always send one.
    """
    _SEQ[0] += 1
    return call("pane.report_agent", {
        "pane_id": pane_id,
        "source": "itest",
        "agent": "claude",
        "state": state,
        "seq": _SEQ[0],
    })


def watcher(state_dir, *args):
    env = dict(os.environ)
    env.update(
        {
            "HERDR_SOCKET_PATH": SOCK,
            "HERDR_PLUGIN_STATE_DIR": state_dir,
            "HERDR_GHOSTTY_TITLE_LABEL": LABEL,
            "HERDR_GHOSTTY_TITLE_DEBUG": "1",
            "HERDR_GHOSTTY_TITLE_CONFIG": os.path.join(state_dir, "nonexistent.toml"),
        }
    )
    return subprocess.run(
        [sys.executable, WATCHER, *args],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


# --------------------------------------------------------------------------- #


def load_watcher_module():
    """Import the watcher so the test renders titles with the same code."""
    import importlib.machinery
    import importlib.util

    spec = importlib.util.spec_from_loader(
        "hgt", importlib.machinery.SourceFileLoader("hgt", WATCHER)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HGT = load_watcher_module()


def counts_now():
    return HGT.count_statuses(call("agent.list").get("agents"))


def expected_title():
    cfg = HGT.load_config()
    cfg["label"] = LABEL
    return HGT.render_title(counts_now(), cfg)


def sync(session, note, timeout=10.0):
    """Wait until the terminal title matches what agent.list currently says.

    Asserting against live herdr state rather than the state we asked for keeps
    the test honest: herdr arbitrates reported states (detection can outrank a
    synthetic report), and the plugin's job is only to mirror the outcome.
    """
    want = expected_title()
    return session.wait_for_title(lambda t: t == want, timeout=timeout,
                                  what=f"{note} -> {want!r}")


def main() -> int:
    state_dir = tempfile.mkdtemp(prefix="hgt-itest-")
    # Same view of config/label/socket as the watcher subprocess, so the titles
    # this test renders for comparison match the ones the watcher pushes. In
    # particular: ignore any real user config.
    os.environ.update(
        {
            "HERDR_SOCKET_PATH": SOCK,
            "HERDR_PLUGIN_STATE_DIR": state_dir,
            "HERDR_GHOSTTY_TITLE_LABEL": LABEL,
            "HERDR_GHOSTTY_TITLE_DEBUG": "1",
            "HERDR_GHOSTTY_TITLE_CONFIG": os.path.join(state_dir, "nonexistent.toml"),
        }
    )
    session = Session()
    checks = []

    def ok(name):
        checks.append((True, name))
        print(f"  ok    {name}")

    try:
        print("starting throwaway herdr session...")
        session.start()
        ok("session up")

        panes = call("pane.list").get("panes", [])
        if not panes:
            raise Fail("session has no panes")
        pane_a = panes[0]["pane_id"]

        started = watcher(state_dir, "start")
        if started.returncode != 0:
            raise Fail(f"watcher start failed: {started.stdout}{started.stderr}")
        ok(f"watcher started ({started.stdout.strip()})")

        # No agents yet -> label only.
        session.wait_for_title(lambda t: t == LABEL, what="label-only title")
        ok("empty session renders label only")

        report(pane_a, "working")
        title = sync(session, "one working agent")
        if f"{WORKING} 1" not in title:
            raise Fail(f"expected a working agent in {title!r}")
        ok(f"working agent renders as {title!r}")

        report(pane_a, "blocked")
        title = sync(session, "escalated to blocked")
        ok(f"escalation reflected as {title!r}")

        # Second pane, second agent.
        split = call("pane.split", {"pane_id": pane_a, "direction": "right"})
        pane_b = split.get("pane", {}).get("pane_id") or split.get("pane_id")
        if not pane_b:
            raise Fail(f"could not determine new pane id from {split}")
        session.pump(0.5)
        report(pane_b, "idle")
        title = sync(session, "two agents")
        if sum(counts_now().values()) != 2:
            raise Fail(f"expected 2 agents, got {counts_now()}")
        ok(f"two agents render as {title!r}")

        # herdr holds an attention state (blocked/done) on an unfocused pane
        # until you look at it, so focus pane_a before de-escalating.
        call("pane.focus", {"pane_id": pane_a})
        session.pump(0.5)
        report(pane_a, "idle")
        title = sync(session, "de-escalated to idle")
        ok(f"de-escalation reflected as {title!r}")

        status = watcher(state_dir, "status")
        if "running" not in status.stdout:
            raise Fail(f"status did not report running: {status.stdout}")
        ok("status reports a running watcher")

        second = watcher(state_dir, "start")
        if "already running" not in second.stdout:
            raise Fail(f"second start was not deduped: {second.stdout}")
        ok("single-instance lock holds")

        before = len(session.titles)
        stopped = watcher(state_dir, "stop")
        if stopped.returncode != 0:
            raise Fail(f"stop failed: {stopped.stdout}{stopped.stderr}")
        session.pump(1.5)
        after = session.titles[before:]
        if not after or LABEL in after[-1]:
            raise Fail(f"title was not restored on exit: {after}")
        ok(f"title restored on exit (-> {after[-1]!r})")

    except Fail as exc:
        print(f"\nFAIL: {exc}")
        checks.append((False, str(exc)))
    finally:
        watcher(state_dir, "stop")
        session.stop()
        shutil.rmtree(state_dir, ignore_errors=True)

    failed = [name for good, name in checks if not good]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
