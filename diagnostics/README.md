# SentryAlert Diagnostics

An optional, observational diagnostics framework for selected SentryAlert beta
systems. It collects bounded evidence without changing recording, storage, USB,
network, camera, application, or Telegram behaviour.

## Install

After a release has been published:

```sh
curl -fsSL https://github.com/hannson88/sa-tests/releases/latest/download/install.sh | sudo bash
```

Installation does not start diagnostics.

## Commands

```sh
# List available modules
sentryalert-diag modules

# Start any module (30 minutes by default)
sudo sentryalert-diag start usb
sudo sentryalert-diag start app --duration 30m
sudo sentryalert-diag start storage --duration 30m
sudo sentryalert-diag start camera --duration 30m
sudo sentryalert-diag start network --duration 30m
sudo sentryalert-diag start system --duration 30m
sudo sentryalert-diag start performance --duration 30m

# Mark the moment a user sees a problem
sudo sentryalert-diag mark "USB error appeared on screen"

# Inspect and finish
sentryalert-diag status
sudo sentryalert-diag stop
sentryalert-diag verify /path/to/diagnostic-bundle.zip

# Backward-compatible USB commands
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

## Reading a bundle

Open `REPORT.txt` first. It contains the result, source-coverage status, known
errors, suspicious unclassified messages, user markers, and a chronological
timeline. `events.jsonl` is always included, even when empty. `samples.jsonl`
contains the detailed bounded evidence used for later engineering analysis.

Patterns classify known failures, but they are not the collection boundary.
Modules retain bounded raw source output so previously unknown failures can be
investigated. A manual marker forces a snapshot even if no pattern matches.

## Storage

Persistent state and evidence live under:

```text
/mutable/diagnostics/<module>-diag/
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

## Module contracts

Each bundle contains `CONTRACT.json`, describing the module's failure modes and
required evidence sources. `REPORT.txt` says whether each source was available.
A clean event list is not presented as proof of health when a required source was
unavailable.

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
