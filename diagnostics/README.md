# SentryAlert Diagnostics

An optional diagnostics framework for selected SentryAlert beta systems. Version 1
collects USB compatibility evidence without changing the USB gadget, its backing
storage, mounts, partitions, recording, encoding, or SentryAlert Telegram workflow.

## Install

After a release has been published:

```sh
curl -fsSL https://github.com/hannson88/sa-tests/releases/latest/download/install.sh | sudo bash
```

Installation does not start diagnostics.

## Commands

```sh
sudo sentryalert-usb-diag-start
sudo sentryalert-usb-diag-start --duration 30m
sentryalert-usb-diag-status
sudo sentryalert-usb-diag-stop
sudo sentryalert-usb-diag-export
sudo sentryalert-usb-diag-resend
sentryalert-diag-version
sudo sentryalert-diag-update
sudo sentryalert-diag-uninstall
sudo sentryalert-diag-uninstall --purge
```

Supported duration syntax includes `30m`, `2h`, `6h`, and `24h`. The default is
30 minutes of diagnostics runner uptime. Time while the computer is off does not
count.

## Storage

Persistent state and evidence live under:

```text
/mutable/diagnostics/usb-diag/
├── state.json
├── state.previous.json
├── exports/
└── sessions/<session-id>/
    ├── logs/
    └── snapshots/
```

State checkpoints use flush, `fsync`, atomic rename, and directory `fsync`.
Completed ZIP files remain available when Telegram delivery fails.

## Configuration

The installer creates `/mutable/diagnostics/config.json` on first install. Existing
configuration is never overwritten during updates.

The diagnostics package reads `/opt/SentryAlert/config.js` only when it needs to
send a completed bundle. Bot tokens are never written to diagnostics state, logs,
summaries, or ZIP files.

## Releases

From the repository root:

```sh
diagnostics/package.sh
```

Upload these files from `dist/diagnostics/` to a GitHub release:

- `install.sh`
- `sentryalert-diagnostics-<version>.tar.gz`
- `checksums.txt`

See [`docs/architecture.md`](docs/architecture.md) for design and recovery details.
