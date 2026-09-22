"""Temporary-fixture engineering tests; not real-user effectiveness evidence."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from vibe_cleaner import triage_evidence as evidence
from vibe_cleaner.common import Refused, identity


class EvidenceFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.sources = self.root / 'sources'
        self.archives = self.root / 'archives'
        self.sources.mkdir(mode=0o700)
        self.archives.mkdir(mode=0o700)
        self.first = self.item('one', b'first transcript\n')
        self.second = self.item('two', b'second transcript\n')

    def item(self, name, content):
        path = self.sources / (name + '.jsonl')
        path.write_bytes(content)
        return {'id': name, 'root': str(self.sources), 'relative': path.name,
                'adapter': 'codex', 'category': 'session', 'identity': identity(path.stat())}

    def source(self, item):
        return Path(item['root']) / item['relative']

    def archive(self, items=None, *, name='backup.zip', payloads=None):
        items = items or [self.first]
        path = self.archives / name
        rows = []
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for n, item in enumerate(items):
                original = self.source(item).read_bytes()
                archive.writestr(str(n), original if payloads is None else payloads[n])
                rows.append({'member': str(n), 'sha256': hashlib.sha256(original).hexdigest(),
                             'item': copy.deepcopy(item)})
        self.write_manifest(path, {'schema': 1, 'archive': path.name, 'files': rows,
                                   'status': 'selected_bytes_verified'})
        return path

    def manifest(self, archive):
        return archive.with_suffix(archive.suffix + '.manifest.json')

    def write_manifest(self, archive, data):
        self.manifest(archive).write_text(json.dumps(data))

    def rewrite_manifest(self, archive, mutate):
        data = json.loads(self.manifest(archive).read_text())
        mutate(data)
        self.write_manifest(archive, data)

    def status(self, report, item=None):
        return report['items'][(item or self.first)['id']]['status']


class BackupEvidenceTests(EvidenceFixture):
    def test_corrupt_deflate_is_invalid_and_other_archive_still_verified(self):
        broken = self.archive()
        valid = self.archive([self.second], name='valid.zip')
        with zipfile.ZipFile(broken) as archive:
            info = archive.getinfo('0')
            offset = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
        raw = bytearray(broken.read_bytes())
        raw[offset] = (raw[offset] & ~7) | 7  # Reserved DEFLATE block type.
        broken.write_bytes(raw)
        report = evidence.backups([self.first, self.second], [broken, valid], max_verify_bytes=1024)
        self.assertEqual(self.status(report), 'invalid')
        self.assertEqual(self.status(report, self.second), 'selected_bytes_verified')

    def test_reference_is_not_byte_verification_even_with_forged_success(self):
        archive = self.archive()
        self.rewrite_manifest(archive, lambda m: m.update(
            status='bytes-verified', whole_archives_verified=True, native_resume_verified=True))
        report = evidence.backups([self.first], [archive])
        self.assertEqual(self.status(report), 'manifest_only')
        self.assertEqual(report['verification_budget_used_bytes'], 0)
        self.assertEqual(report['items']['one']['verification_deferred'], 'byte_budget')
        self.assertFalse(report['whole_archives_verified'])
        self.assertFalse(report['native_resume_verified'])

    def test_actual_source_and_member_match_and_source_is_unchanged(self):
        archive = self.archive()
        source = self.source(self.first)
        before = (source.read_bytes(), identity(source.stat()))
        cap = 2 * self.first['identity']['size']
        report = evidence.backups([self.first], [archive], max_verify_bytes=cap)
        row = report['items']['one']
        self.assertEqual(row['status'], 'selected_bytes_verified')
        self.assertEqual(row['sha256'], hashlib.sha256(before[0]).hexdigest())
        self.assertEqual(row['source_identity'], before[1])
        self.assertGreater(row['verified_at'], 0)
        self.assertEqual(report['verification_budget_used_bytes'], cap)
        self.assertEqual(row['verification_budget_bytes'], cap)
        self.assertEqual((source.read_bytes(), identity(source.stat())), before)
        self.assertFalse(report['whole_archives_verified'])

    def test_budget_requires_source_plus_expanded_member(self):
        archive = self.archive()
        cap = 2 * self.first['identity']['size']
        for insufficient in (0, self.first['identity']['size'], cap - 1):
            with self.subTest(budget=insufficient):
                report = evidence.backups([self.first], [archive], max_verify_bytes=insufficient)
                self.assertEqual(self.status(report), 'manifest_only')
                self.assertEqual(report['verification_budget_used_bytes'], 0)
        self.assertEqual(self.status(evidence.backups([self.first], [archive], max_verify_bytes=cap)),
                         'selected_bytes_verified')

    def test_success_does_not_transfer_to_unverified_second_file(self):
        archive = self.archive([self.first, self.second])
        cap = 2 * self.first['identity']['size']
        report = evidence.backups([self.first, self.second], [archive], max_verify_bytes=cap)
        self.assertEqual(self.status(report), 'selected_bytes_verified')
        self.assertEqual(self.status(report, self.second), 'manifest_only')
        self.assertNotIn('sha256', report['items']['two'])
        self.assertEqual(report['verification_budget_used_bytes'], cap)

    def test_failure_reserves_budget_and_cannot_verify_second_file(self):
        archive = self.archive([self.first, self.second], payloads=[b'x' * self.first['identity']['size'],
                                                                 self.source(self.second).read_bytes()])
        cap = 2 * self.first['identity']['size']
        report = evidence.backups([self.first, self.second], [archive], max_verify_bytes=cap)
        self.assertEqual(self.status(report), 'invalid')
        self.assertEqual(self.status(report, self.second), 'manifest_only')
        self.assertEqual(report['verification_budget_used_bytes'], cap)

    def test_corrupt_zip_does_not_inherit_manifest_success(self):
        archive = self.archive()
        archive.write_bytes(b'not a zip')
        report = evidence.backups([self.first], [archive], max_verify_bytes=1000)
        self.assertEqual(self.status(report), 'invalid')

    def test_member_bytes_must_match_not_just_size(self):
        archive = self.archive(payloads=[b'x' * self.first['identity']['size']])
        self.assertEqual(self.status(evidence.backups([self.first], [archive], max_verify_bytes=1000)), 'invalid')

    def test_declared_sha_must_match_both_real_copies(self):
        archive = self.archive()
        self.rewrite_manifest(archive, lambda m: m['files'][0].update(sha256='0' * 64))
        self.assertEqual(self.status(evidence.backups([self.first], [archive], max_verify_bytes=1000)), 'invalid')

    def test_duplicate_zip_members_refused(self):
        archive = self.archive()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(archive, 'a') as z:
                z.writestr('0', self.source(self.first).read_bytes())
        self.assertEqual(self.status(evidence.backups([self.first], [archive], max_verify_bytes=1000)), 'invalid')

    def test_duplicate_manifest_members_refused(self):
        archive = self.archive()
        self.rewrite_manifest(archive, lambda m: m['files'].append(copy.deepcopy(m['files'][0])))
        report = evidence.backups([self.first], [archive], max_verify_bytes=1000)
        self.assertEqual(self.status(report), 'unknown')
        self.assertEqual(report['manifest_errors'], 1)

    def test_duplicate_source_path_in_manifest_is_ambiguous(self):
        archive = self.archive()
        def duplicate(m):
            row = copy.deepcopy(m['files'][0])
            row['member'] = '1'
            m['files'].append(row)
        self.rewrite_manifest(archive, duplicate)
        self.assertEqual(self.status(evidence.backups([self.first], [archive], max_verify_bytes=1000)), 'ambiguous')

    def test_duplicate_archive_argument_refused(self):
        archive = self.archive()
        with self.assertRaises(Refused):
            evidence.backups([self.first], [archive, archive], max_verify_bytes=1000)

    def test_two_archives_for_same_source_are_ambiguous(self):
        one = self.archive(name='one.zip')
        two = self.archive(name='two.zip')
        self.assertEqual(self.status(evidence.backups([self.first], [one, two], max_verify_bytes=1000)), 'ambiguous')

    def test_source_change_after_inventory_refused(self):
        archive = self.archive()
        self.source(self.first).write_bytes(b'changed, longer source\n')
        self.assertEqual(self.status(evidence.backups([self.first], [archive], max_verify_bytes=1000)), 'invalid')

    def test_fresh_identity_but_stale_backup_bytes_refused(self):
        archive = self.archive()
        path = self.source(self.first)
        path.write_bytes(b'x' * self.first['identity']['size'])
        fresh = {**self.first, 'identity': identity(path.stat())}
        self.assertEqual(self.status(evidence.backups([fresh], [archive], max_verify_bytes=1000)), 'invalid')

    def test_archive_and_manifest_symlinks_refused(self):
        for target_kind in ('archive', 'manifest'):
            with self.subTest(kind=target_kind):
                archive = self.archive(name=target_kind + '.zip')
                target = archive if target_kind == 'archive' else self.manifest(archive)
                moved = target.with_name(target.name + '.real')
                target.rename(moved)
                target.symlink_to(moved)
                report = evidence.backups([self.first], [archive], max_verify_bytes=1000)
                self.assertEqual(self.status(report), 'unknown')
                self.assertEqual(report['manifest_errors'], 1)

    def test_source_symlink_refused(self):
        archive = self.archive()
        source = self.source(self.first)
        moved = source.with_suffix('.original')
        source.rename(moved)
        source.symlink_to(moved)
        self.assertEqual(self.status(evidence.backups([self.first], [archive], max_verify_bytes=1000)), 'invalid')

    def test_no_archive_and_no_matching_supplied_archive_are_distinct(self):
        self.assertEqual(self.status(evidence.backups([self.first], [])), 'not_checked')
        archive = self.archive([self.second])
        self.assertEqual(self.status(evidence.backups([self.first], [archive])), 'no_match_supplied')


class ActivityEvidenceTests(EvidenceFixture):
    def response(self, returncode=1, stdout=b'', stderr=b''):
        return subprocess.CompletedProcess(['lsof'], returncode, stdout, stderr)

    def check(self, response=None, *, effect=None, items=None):
        with patch.object(evidence.shutil, 'which', return_value='/mock/lsof'), \
             patch.object(evidence.subprocess, 'run', return_value=response, side_effect=effect) as run:
            result = evidence.activity(items or [self.first, self.second])
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs['timeout'], 10)
            return result

    def test_no_handles(self):
        self.assertEqual(self.check(self.response()), {'one': 'no_open_handles', 'two': 'no_open_handles'})

    def test_exact_open_path_does_not_mark_other_file_open(self):
        output = ('p123\nn' + str(self.source(self.first)) + '\n').encode()
        self.assertEqual(self.check(self.response(0, output)), {'one': 'open', 'two': 'no_open_handles'})

    def test_permission_stderr_and_ambiguous_output_stay_unknown(self):
        cases = [self.response(1, stderr=b'permission denied'), self.response(0, b'p123\n'),
                 self.response(0, b'p123\nn/unmapped/path\n'), self.response(0, b'\xff'),
                 self.response(0), self.response(2), self.response(1, b'p123\n')]
        for response in cases:
            with self.subTest(code=response.returncode, output=response.stdout):
                self.assertEqual(self.check(response), {'one': 'unknown', 'two': 'unknown'})

    def test_timeout_is_unknown(self):
        self.assertEqual(self.check(effect=subprocess.TimeoutExpired('lsof', 10)),
                         {'one': 'unknown', 'two': 'unknown'})

    def test_missing_lsof_does_not_invoke_subprocess(self):
        with patch.object(evidence.shutil, 'which', return_value=None), patch.object(evidence.subprocess, 'run') as run:
            self.assertEqual(evidence.activity([self.first]), {'one': 'unknown'})
            run.assert_not_called()

    def test_identity_changed_before_inspection_does_not_invoke_lsof(self):
        self.source(self.first).write_bytes(b'replaced source bytes')
        with patch.object(evidence.shutil, 'which', return_value='/mock/lsof'), patch.object(evidence.subprocess, 'run') as run:
            self.assertEqual(evidence.activity([self.first]), {'one': 'unknown'})
            run.assert_not_called()

    def test_identity_changed_during_lsof_invalidates_whole_batch(self):
        def changed(*args, **kwargs):
            self.source(self.first).write_bytes(b'new bytes during inspection')
            return self.response()
        self.assertEqual(self.check(effect=changed), {'one': 'unknown', 'two': 'unknown'})

    def test_newline_path_is_unknown_without_subprocess(self):
        item = self.item('line\nbreak', b'content')
        with patch.object(evidence.shutil, 'which', return_value='/mock/lsof'), patch.object(evidence.subprocess, 'run') as run:
            self.assertEqual(evidence.activity([item]), {item['id']: 'unknown'})
            run.assert_not_called()

    def test_duplicate_path_must_not_report_an_open_file_as_idle(self):
        alias = {**self.first, 'id': 'alias'}
        with patch.object(evidence.shutil, 'which', return_value='/mock/lsof'), patch.object(evidence.subprocess, 'run') as run:
            result = evidence.activity([self.first, alias])
            run.assert_not_called()
        # Reject ambiguity or map both IDs to open; neither may be labeled idle.
        self.assertNotIn('no_open_handles', result.values())

    def test_activity_does_not_modify_source(self):
        source = self.source(self.first)
        before = (source.read_bytes(), identity(source.stat()))
        self.check(self.response())
        self.assertEqual((source.read_bytes(), identity(source.stat())), before)


if __name__ == '__main__':
    unittest.main()
