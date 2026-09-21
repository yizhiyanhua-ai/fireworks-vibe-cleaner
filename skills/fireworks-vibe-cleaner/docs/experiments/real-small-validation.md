See the [current README](../../README.md) for the latest results.

## Earlier 214 MiB real local validation

**Real data, 2026-09-21 · macOS 26.5.1 · arm64 · Python 3.14.6. Actual cleanup reclaimed 0 bytes.** This result does not demonstrate that v0.1 solves large session storage growth. No fixtures or mocked service responses were used for the measurements below.

| Measurement | Before | After / observed result |
| --- | ---: | --- |
| Real inventory | 49,064 files; 21,165,470,439 logical bytes (19.71 GiB) | Metadata-only scan; 225 symlink/dependency boundaries skipped; not a complete disk total |
| Session footprint | 2,615 files; 15,038,397,937 bytes (14.01 GiB) | Originals retained; session deletion and harness resume remain unsupported |
| Cleanup policy correction, identical snapshot | 8 custom-service logs incorrectly eligible; 196,608 allocated bytes | All 8 protected after narrowing the Codex filename allowlist; **0 eligible files** |
| Real Codex session backup (2 files) | 126,384,858 bytes (120.53 MiB) | ZIP 37,856,051 bytes (36.10 MiB), 70.05% smaller; 1978 ms |
| Real Claude session backup (2 files) | 98,252,538 bytes (93.70 MiB) | ZIP 21,852,674 bytes (20.84 MiB), 77.76% smaller; 1214 ms |
| Byte recovery | SHA-256 of each real source recorded privately | All 4 extracted copies matched; all 4 source hashes unchanged |
| Actual disk benefit | No approved eligible cleanup target after correction | **0 source bytes deleted; 0 cleanup bytes reclaimed**; retained ZIPs/manifests added 59,712,330 logical bytes (56.95 MiB) |
| Live Jev comparison in this earlier run | No inference request made at that time | Superseded by the real 10 GiB / live-provider results in the current README |

The four sessions were selected from stable files at least one day old, at most 64 MiB each, with no open handle at selection. Compression ratios apply to these samples only. Backup durations measure the backup operation, including its readback, and exclude initial hashing/extraction. Originals remain in place; smaller ZIPs are **not** reclaimed space. Observed volume free-space deltas were −38,461,440 bytes (Codex volume) and −21,991,424 bytes (Claude volume), including concurrent background writes; neither is attributed solely to the experiment. The extracted verification copies were removed; private archives and manifests remain local.

The real scan exposed a safety bug: arbitrary custom-service `.log` files in a Codex log directory were treated as harness logs. Current `main` restricts Codex cleanup to `log/codex-tui.log` and `logs/codex-tui.log`. Old plans are reclassified at execution and rejected when outside this allowlist. This result establishes a protection fix and byte-preserving backups; **real quarantine/purge and session resumption were not validated**.

[Sanitized real results](real-local-2026-09-21.json) · [Real-data validation script](../../tools/real_validation.py). Public results contain aggregate sizes/counts/timings only; no usernames, paths, filenames, IDs, content hashes, transcripts or credentials. Raw inventories and backups must stay private.

```sh
python3 scripts/fireworks-vibe-cleaner.py scan --output artifacts/private-inventory.json
python3 tools/real_validation.py --inventory artifacts/private-inventory.json --output artifacts/real-results.json
```

Use a new output filename. The script creates private same-volume backups and temporary extraction copies; it never removes original sessions. This is a local opt-in operation, **not a CI job**. [Historical synthetic regression results](synthetic-regression.md) remain available for safety mechanics and are not effectiveness evidence. CI continues to exercise fixtures without accessing personal data.

