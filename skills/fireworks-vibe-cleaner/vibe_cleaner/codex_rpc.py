"""Narrow, offline Codex app-server client. Never starts or resumes a turn."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import shutil
import stat
import subprocess
import threading
import time
from typing import Any

from . import __version__
from .common import Json, Refused, identity

SOURCE_KINDS = ["cli", "vscode", "exec", "appServer", "subAgent", "subAgentReview",
                "subAgentCompact", "subAgentThreadSpawn", "subAgentOther", "unknown"]
SUPPORTED_VERSION = "codex-cli 0.154.0"
ALLOWED = {"initialize", "thread/list", "thread/read", "thread/loaded/list",
           "thread/archive", "thread/unarchive"}
MAX_FRAME = 16 * 1024**2


def sandbox_prefix(binary: Path, root: Path, home: Path) -> list[str]:
    if platform.system() != "Darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        raise Refused("Native history writes require the verified macOS network-denied runtime")
    for path in (binary, root, home):
        if path != path.resolve():
            raise Refused("Native sandbox paths must be canonical")
    def quote(path: Path) -> str:
        return json.dumps(str(path), ensure_ascii=False)
    profile = ("(version 1)(allow default)(deny network*)(deny process-exec)(deny file-write*)"
               f"(allow process-exec (literal {quote(binary)}))"
               f"(allow file-write* (subpath {quote(root)}) (subpath {quote(home)}) (literal \"/dev/null\"))")
    return ["/usr/bin/sandbox-exec", "-p", profile]


def private_home(path: Path) -> None:
    if path.absolute() != path.resolve() or path.is_symlink():
        raise Refused("Native runtime HOME must be canonical and private")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    s = path.stat()
    if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o700:
        raise Refused("Native runtime HOME must be owned and mode 0700")
    (path / "tmp").mkdir(exist_ok=True, mode=0o700)


def environment(root: Path, home: Path) -> dict[str, str]:
    # No provider credentials, proxies, existing CODEX_THREAD_ID, or user PATH.
    return {"HOME": str(home), "CODEX_HOME": str(root), "TMPDIR": str(home / "tmp"),
            "PATH": "/usr/bin:/bin:/opt/homebrew/bin", "LANG": "en_US.UTF-8"}


def executable_record(codex: Path | str, root: Path, home: Path) -> Json:
    supplied = str(codex)
    found = shutil.which(supplied) if not Path(supplied).is_absolute() else supplied
    if not found:
        raise Refused("Codex executable is unavailable")
    path = Path(found).resolve(strict=True)
    # Bind the native binary, not the npm launcher whose vendor dependency can change.
    if path.name == "codex.js":
        if platform.system() != "Darwin":
            raise Refused("Unsupported native Codex package platform")
        arm = platform.machine() == "arm64"
        package = "codex-darwin-arm64" if arm else "codex-darwin-x64"
        triple = "aarch64-apple-darwin" if arm else "x86_64-apple-darwin"
        path = (path.parent.parent / "node_modules" / "@openai" / package / "vendor" /
                triple / "bin" / "codex").resolve(strict=True)
    s = path.stat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or not os.access(path, os.X_OK):
        raise Refused("Codex must resolve to a regular executable")
    with path.open("rb") as stream:
        magic = stream.read(4)
    if magic not in {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
                     b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}:
        raise Refused("Supply --codex with the native Mach-O executable; unrecognized launchers are refused")
    private_home(home)
    result = subprocess.run([*sandbox_prefix(path, root, home), str(path), "--version"], env=environment(root, home),
                            cwd=home, capture_output=True, timeout=10)
    if result.returncode != 0 or result.stdout.strip() != SUPPORTED_VERSION.encode():
        raise Refused("Native archival is verified only for codex-cli 0.154.0")
    with path.open("rb") as stream:
        sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    if identity(path.stat()) != identity(s):
        raise Refused("Codex executable changed during capability inspection")
    return {"path": str(path), "identity": identity(s),
            "sha256": sha256, "version": SUPPORTED_VERSION,
            "codex_home": str(root), "home": str(home), "network": "denied-macos-sandbox",
            "sandbox_profile": sandbox_prefix(path, root, home)[2]}


def check_runtime(record: Json) -> None:
    fresh = executable_record(record["path"], Path(record["codex_home"]), Path(record["home"]))
    if fresh != record:
        raise Refused("Codex executable or runtime binding changed since review")


class CodexRPC:
    def __init__(self, runtime: Json):
        self.runtime = runtime
        self.proc: subprocess.Popen | None = None
        self.messages: queue.Queue = queue.Queue(maxsize=256)
        self.number = 0

    def __enter__(self) -> "CodexRPC":
        check_runtime(self.runtime)
        home, root = Path(self.runtime["home"]), Path(self.runtime["codex_home"])
        self.proc = subprocess.Popen(
            [*sandbox_prefix(Path(self.runtime["path"]), root, home), self.runtime["path"], "app-server", "--stdio",
             "-c", "analytics.enabled=false", "-c", "check_for_update_on_startup=false",
             "-c", 'cli_auth_credentials_store="file"'],
            cwd=home, env=environment(root, home), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.request("initialize", {"clientInfo": {"name": "fireworks_vibe_cleaner",
                         "title": None, "version": __version__},
                         "capabilities": {"experimentalApi": True, "requestAttestation": False}})
            self._send({"method": "initialized", "params": {}})
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _read(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        try:
            while True:
                raw = self.proc.stdout.readline(MAX_FRAME + 1)
                if not raw:
                    raise EOFError
                if len(raw) > MAX_FRAME:
                    raise ValueError
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError
                self.messages.put(value, timeout=10)
        except (ValueError, OSError, EOFError, queue.Full):
            try:
                self.messages.put(None, timeout=1)
            except queue.Full:
                pass

    def _send(self, value: Json) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write((json.dumps(value) + "\n").encode())
        self.proc.stdin.flush()

    def request(self, method: str, params: Json) -> Json:
        if method not in ALLOWED:
            raise Refused("Method is outside the native history maintenance allowlist")
        self.number += 1
        self._send({"id": self.number, "method": method, "params": params})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                reply = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                raise Refused("Native history RPC timed out; inspect this run before retrying") from None
            if reply is None:
                raise Refused("Native history RPC closed or returned invalid protocol data")
            if reply.get("id") != self.number:
                if "id" in reply:
                    raise Refused("Unexpected native history RPC response")
                continue  # Never persist notifications or their potentially private payloads.
            if "error" in reply or not isinstance(reply.get("result"), dict):
                raise Refused("Native history RPC refused the request; no server payload was logged")
            return reply["result"]
        raise Refused("Native history RPC deadline exceeded")

    def descendants(self, ident: str, *, archived: bool, cap: int) -> set[str]:
        seen: set[str] = set()
        cursors: set[str] = set()
        cursor = None
        while True:
            result = self.request("thread/list", {"ancestorThreadId": ident, "archived": archived,
                                  "sourceKinds": SOURCE_KINDS, "modelProviders": [],
                                  "useStateDbOnly": True,
                                  "limit": min(cap + 1, 1000), "cursor": cursor})
            for row in result["data"]:
                value = row["id"]
                if not isinstance(value, str) or value in seen:
                    raise Refused("Native descendant listing contains duplicates or invalid IDs")
                seen.add(value)
            if len(seen) > cap:
                raise Refused("Native descendant list exceeds the reviewed bound")
            cursor = result.get("nextCursor")
            if cursor is None:
                return seen
            if not isinstance(cursor, str) or cursor in cursors:
                raise Refused("Native descendant pagination did not advance")
            cursors.add(cursor)

    def __exit__(self, *args: Any) -> None:
        if self.proc is None:
            return
        if self.proc.stdin:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()  # Only the private child process created above.
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        if self.proc.stdout:
            self.proc.stdout.close()
