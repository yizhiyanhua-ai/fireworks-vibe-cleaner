#!/usr/bin/env python3
"""Counts-only, network-denied native history readback. Never resumes a turn."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import time

UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
MAX_PROTOCOL_LINE = 256 * 1024 * 1024


class CheckFailure(Exception):
    pass


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise CheckFailure('private-directory-permissions')


def safe_file(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts:
        raise CheckFailure('invalid-relative-path')
    root = root.resolve(strict=True)
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise CheckFailure('symlink-not-supported')
    if not current.is_file() or not current.resolve().is_relative_to(root):
        raise CheckFailure('invalid-sample-file')
    return current


def network_command(command: list[str], read_only_root: Path | None = None) -> list[str]:
    if sys.platform != 'darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise CheckFailure('network-isolation-unavailable')
    policy = '(version 1)(allow default)(deny network*)'
    if read_only_root is not None:
        policy += '(deny file-write* (subpath ' + json.dumps(str(read_only_root)) + '))'
    return ['/usr/bin/sandbox-exec', '-p', policy, *command]


def environment(home: Path, root: Path, adapter: str) -> dict[str, str]:
    # No inherited credentials, proxies, provider configuration, or real HOME.
    result = {'HOME': str(home), 'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin',
              'TMPDIR': str(home), 'LANG': 'en_US.UTF-8'}
    result['CODEX_HOME' if adapter == 'codex' else 'CLAUDE_CONFIG_DIR'] = str(root)
    if adapter == 'claude':
        result['CLAUDE_CODE_DISABLE_PRECOMPACT_SKIP'] = '1'
    return result


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def spawn(command: list[str], env: dict[str, str], cwd: Path,
          read_only_root: Path | None = None) -> subprocess.Popen:
    # Stderr is discarded rather than risking unbounded or secret-bearing output.
    return subprocess.Popen(network_command(command, read_only_root), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env=env, cwd=cwd, bufsize=0)


class Protocol:
    def __init__(self, process: subprocess.Popen, seconds: float):
        self.process = process
        self.deadline = time.monotonic() + seconds
        self.buffer = bytearray()
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout, selectors.EVENT_READ)

    def send(self, data: dict) -> None:
        raw = json.dumps(data).encode() + b'\n'
        self.process.stdin.write(raw)
        self.process.stdin.flush()

    def response(self, wanted: int) -> dict:
        while True:
            if b'\n' in self.buffer:
                line, _, rest = self.buffer.partition(b'\n')
                self.buffer = bytearray(rest)
                try:
                    data = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(data, dict) and data.get('id') == wanted:
                    return data
                continue
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise CheckFailure('native-read-timeout')
            if not self.selector.select(min(remaining, 1)):
                if self.process.poll() is not None:
                    raise CheckFailure('native-process-exited')
                continue
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise CheckFailure('native-protocol-eof')
            self.buffer.extend(chunk)
            if len(self.buffer) > MAX_PROTOCOL_LINE:
                raise CheckFailure('native-response-limit')

    def close(self) -> None:
        self.selector.close()
        self.buffer.clear()


def codex_read(executable: str, root: Path, home: Path, session: str, timeout: float,
               original_root: Path) -> dict:
    process = spawn([executable, 'app-server', '--listen', 'stdio://'], environment(home, root, 'codex'), home, read_only_root=original_root)
    protocol = Protocol(process, timeout)
    try:
        protocol.send({'id': 1, 'method': 'initialize', 'params': {
            'clientInfo': {'name': 'fireworks_vibe_cleaner_validator', 'title': None, 'version': '0.1.1'},
            'capabilities': None}})
        if 'result' not in protocol.response(1):
            raise CheckFailure('codex-initialize-failed')
        protocol.send({'method': 'initialized'})
        request = {'id': 2, 'method': 'thread/read', 'params': {'threadId': session, 'includeTurns': True}}
        protocol.send(request)
        response = protocol.response(2)
        if 'error' in response:
            error = response.get('error')
            message = str(error.get('message', '')).lower() if isinstance(error, dict) else ''
            if not any(term in message for term in ('not found', 'notfound', 'no rollout', 'no thread found', 'does not exist')):
                raise CheckFailure('codex-thread-read-failed')
            for number, archived in ((3, False), (4, True)):
                protocol.send({'id': number, 'method': 'thread/list', 'params': {
                    'archived': archived, 'useStateDbOnly': False, 'modelProviders': [], 'limit': 100}})
                if 'result' not in protocol.response(number):
                    raise CheckFailure('codex-thread-list-failed')
            request['id'] = 5
            protocol.send(request)
            response = protocol.response(5)
        result = response.get('result')
        thread = result.get('thread') if isinstance(result, dict) else None
        turns = thread.get('turns') if isinstance(thread, dict) else None
        if isinstance(turns, list) and not turns:
            # Newer app-server versions may omit deprecated eager hydration.
            cursor, seen, turns = None, set(), []
            for request_id in range(10, 110):
                protocol.send({'id': request_id, 'method': 'thread/turns/list', 'params': {
                    'threadId': session, 'cursor': cursor, 'limit': 20,
                    'sortDirection': 'asc', 'itemsView': 'full'}})
                page = protocol.response(request_id).get('result')
                if not isinstance(page, dict) or not isinstance(page.get('data'), list):
                    raise CheckFailure('codex-paged-read-failed')
                turns.extend(page['data'])
                cursor = page.get('nextCursor')
                if cursor is None:
                    break
                if not isinstance(cursor, str) or cursor in seen:
                    raise CheckFailure('codex-repeated-cursor')
                seen.add(cursor)
            else:
                raise CheckFailure('codex-page-limit')
        if not isinstance(turns, list) or not turns:
            raise CheckFailure('codex-empty-or-invalid-turns')
        if any(not isinstance(turn, dict) or not isinstance(turn.get('items'), list) for turn in turns):
            raise CheckFailure('codex-invalid-items')
        count = sum(len(turn['items']) for turn in turns)
        if count < 1:
            raise CheckFailure('codex-empty-items')
        digest = hashlib.sha256(json.dumps(turns, sort_keys=True, separators=(',', ':'),
                                           ensure_ascii=False).encode()).hexdigest()
        return {'turns': len(turns), 'items': count, 'hash': digest}
    finally:
        protocol.close()
        stop(process)


CLAUDE_SCRIPT = r'''
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
try {
  const sdk = await import(pathToFileURL(process.argv[1]).href);
  const messages = await sdk.getSessionMessages(process.argv[2], {includeSystemMessages: true});
  if (!Array.isArray(messages) || messages.length === 0) process.exit(4);
  const hash = createHash('sha256').update(JSON.stringify(messages)).digest('hex');
  process.stdout.write(JSON.stringify({messages: messages.length, hash}));
} catch (_) { process.exit(5); }
'''


def claude_read(node: str, sdk: Path, root: Path, home: Path, session: str, timeout: float) -> dict:
    process = spawn([node, '--max-old-space-size=1536', '--input-type=module', '-e', CLAUDE_SCRIPT,
                     str(sdk), session], environment(home, root, 'claude'), home, read_only_root=root)
    protocol = Protocol(process, timeout)
    # SDK wrapper emits only counts/hash, with no transcript on stdout.
    try:
        process.stdin.close()
        received = bytearray()
        while True:
            remaining = protocol.deadline - time.monotonic()
            if remaining <= 0:
                raise CheckFailure('native-read-timeout')
            if not protocol.selector.select(min(remaining, 1)):
                if process.poll() is not None:
                    break
                continue
            chunk = os.read(process.stdout.fileno(), 4096)
            if not chunk:
                break
            received.extend(chunk)
            if len(received) > 4096:
                raise CheckFailure('claude-response-limit')
        remaining = max(0.1, protocol.deadline - time.monotonic())
        if process.wait(timeout=remaining) != 0:
            raise CheckFailure('claude-sdk-read-failed')
        data = json.loads(received)
        if (not isinstance(data, dict) or type(data.get('messages')) is not int or data['messages'] < 1
                or not isinstance(data.get('hash'), str) or not re.fullmatch('[a-f0-9]{64}', data['hash'])):
            raise CheckFailure('claude-invalid-readback')
        return data
    finally:
        protocol.close()
        stop(process)


def save_new(path: Path, data: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=Path, required=True)
    parser.add_argument('--private-output', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--claude-sdk', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=float, default=240)
    args = parser.parse_args()
    public = {'schema': 1, 'data': 'real-native-history', 'network_calls': 0,
              'real_user_data_modified': False, 'native_history_read_only': True, 'continuation_verified': False,
              'network_policy': 'deny-all-required', 'samples': [], 'ok': False,
              'comparison_scope': 'isolated copies bound to the exact source file, not global UUID lookup'}
    try:
        if not 1 <= args.timeout_seconds <= 900:
            raise CheckFailure('invalid-timeout')
        network_command(['true'])
        private = args.private_output.absolute()
        if private.resolve() != private:
            raise CheckFailure('private-output-symlink-parent')
        private_dir(private)
        samples = json.loads(args.samples.read_text())
        if not isinstance(samples, list) or not 1 <= len(samples) <= 20:
            raise CheckFailure('invalid-samples')
        executables = {'codex': shutil.which('codex'), 'claude': shutil.which('node')}
        for index, sample in enumerate(samples):
            row = {'sample_number': index + 1, 'adapter': 'unknown', 'ok': False}
            public['samples'].append(row)
            try:
                adapter = sample['adapter']
                if adapter not in executables or not executables[adapter]:
                    raise CheckFailure('native-executable-unavailable')
                row['adapter'] = adapter
                item = sample['item']
                source_root = Path(item['root']).resolve(strict=True)
                source = safe_file(source_root, item['relative'])
                expected = item['sha256']
                if not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected):
                    raise CheckFailure('invalid-sample-hash')
                restored_root = Path(sample['restored_root']).resolve(strict=True)
                restored_file = Path(sample['restored_file']).absolute()
                if not restored_file.is_relative_to(restored_root) or source_root.is_relative_to(restored_root):
                    raise CheckFailure('invalid-restored-location')
                restored = safe_file(restored_root, str(restored_file.relative_to(restored_root)))
                if source.resolve() == restored.resolve() or os.path.samefile(source, restored):
                    raise CheckFailure('restored-file-is-original')
                if sha_file(source) != expected or sha_file(restored) != expected:
                    raise CheckFailure('sample-byte-hash-mismatch')
                matches = UUID.findall(source.name)
                if len(matches) != 1:
                    raise CheckFailure('session-id-not-unique')
                session = matches[0]
                work = private / f'sample-{index + 1}'
                private_dir(work)
                source_home = work / 'source-home'
                restored_home = work / 'restored-home'
                private_dir(source_home)
                private_dir(restored_home)
                if adapter == 'codex':
                    if private.is_relative_to(source_root):
                        raise CheckFailure('native-work-directory-must-be-outside-source-root')
                    isolated = work / 'source-root'
                    private_dir(isolated)
                    destination = isolated / item['relative']
                    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with source.open('rb') as src, destination.open('xb') as dst:
                        os.chmod(destination, 0o600)
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
                    if sha_file(destination) != expected:
                        raise CheckFailure('isolated-copy-hash-mismatch')
                    isolated_restored = work / 'restored-root'
                    private_dir(isolated_restored)
                    restored_destination = isolated_restored / item['relative']
                    restored_destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with restored.open('rb') as src, restored_destination.open('xb') as dst:
                        os.chmod(restored_destination, 0o600)
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
                    if sha_file(restored_destination) != expected:
                        raise CheckFailure('isolated-restored-copy-hash-mismatch')
                    before = codex_read(executables[adapter], isolated, source_home, session, args.timeout_seconds, source_root)
                    after = codex_read(executables[adapter], isolated_restored, restored_home, session, args.timeout_seconds, source_root)
                else:
                    # Global UUID lookup can select a different duplicate session.
                    # Bind the baseline to an isolated copy of this exact source file.
                    isolated = work / 'source-root'
                    private_dir(isolated)
                    destination = isolated / item['relative']
                    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with source.open('rb') as src, destination.open('xb') as dst:
                        os.chmod(destination, 0o600)
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
                    if sha_file(destination) != expected:
                        raise CheckFailure('isolated-copy-hash-mismatch')
                    before = claude_read(executables[adapter], args.claude_sdk.resolve(strict=True), isolated,
                                         source_home, session, args.timeout_seconds)
                    after = claude_read(executables[adapter], args.claude_sdk.resolve(strict=True), restored_root,
                                        restored_home, session, args.timeout_seconds)
                equal = before == after
                save_new(work / 'private-readback.json', {'source': before, 'restored': after})
                row.update({'counts_source': {k: v for k, v in before.items() if k != 'hash'},
                            'counts_restored': {k: v for k, v in after.items() if k != 'hash'},
                            'canonical_history_equal': equal, 'source_bytes_unchanged': sha_file(source) == expected,
                            'restored_bytes_unchanged': sha_file(restored) == expected})
                row['ok'] = equal and row['source_bytes_unchanged'] and row['restored_bytes_unchanged']
            except CheckFailure as exc:
                row['failure'] = str(exc)
            except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
                row['failure'] = 'native-check-error'
        public['ok'] = bool(public['samples']) and all(row['ok'] for row in public['samples'])
    except CheckFailure as exc:
        public['failure'] = str(exc)
    except (OSError, ValueError, TypeError, KeyError):
        public['failure'] = 'validation-setup-error'
    try:
        save_new(args.output, public)
    except OSError:
        print(json.dumps({'ok': False, 'failure': 'public-output-write-failed'}))
        return 2
    print(json.dumps(public))
    return 0 if public['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
