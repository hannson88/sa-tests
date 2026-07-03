# Diagnostics Framework Architecture

## Boundaries

The framework is independently installed under `/opt/sentryalert-diagnostics`.
Its persistent state is under `/mutable/diagnostics`. It reads SentryAlert version
and Telegram configuration, but never writes into `/opt/SentryAlert` and never
changes storage, gadget, mount, partition, recording, encoding, or alert behavior.

## Layers

1. The command layer creates sessions, reports state, requests stop, exports, and
   retries delivery.
2. The runner accounts for powered-on time, schedules collection, checkpoints
   state, and finalizes sessions.
3. Diagnostic modules implement periodic samples, event detection, and snapshots.
4. The exporter produces a human-readable summary, structured inventory, evidence,
   and a SHA-256 manifest.
5. The delivery adapter reads the existing SentryAlert Telegram configuration only
   inside a short-lived helper process.

Future modules implement the `DiagnosticModule` interface and receive their own
persistent module directory. They do not require changes to state durability,
export, delivery, installation, or service lifecycle.

## Powered-on runtime

Runtime is accumulated from Python's monotonic clock while the runner is alive.
Wall time is recorded only for operator context. Consequently:

- fake-hwclock corrections do not affect duration;
- time while power is absent does not count;
- time after a process or service restart begins a new monotonic interval;
- at most one checkpoint interval is normally lost during sudden power removal.

The Linux boot ID is recorded at every checkpoint to make reboot boundaries
explicit in support evidence.

## State durability

`state.json` is serialized to a temporary file in the same directory, flushed,
`fsync`ed, renamed atomically, and followed by a directory `fsync`. Before replacement,
the last valid state is copied to `state.previous.json` using the same procedure.

Readers validate the current JSON and fall back to the previous copy. A filesystem
lock serializes runner checkpoints and operator mutations such as stop requests.

Logs use JSON Lines and are `fsync`ed after each record. They rotate at a configured
size. Snapshots are individual atomic JSON files, rate-limited, deduplicated by
kernel-message fingerprint, and capped by count.

## Completion and delivery

Collection completion is committed before export or network delivery. Export and
Telegram status are then checkpointed separately. A network failure therefore
cannot return a completed session to a running state or destroy its ZIP.

Completion first enters a persistent `finalizing` state. If power disappears while
the ZIP is being created, boot recovery retries finalization. A power loss in the
small interval after Telegram accepts an upload but before delivery state is
checkpointed can cause a duplicate upload; avoiding that would require transaction
support from Telegram that its Bot API does not provide.

The delivery helper loads the bot token and chat ID from
`/opt/SentryAlert/config.js`, uploads the ZIP, sends a forwarding instruction, and
exits. Credentials are not returned to Python or included in evidence.

## Installation and update

GitHub Releases contain a standalone bootstrap installer, a versioned archive, and
checksums. The installer verifies the archive, stages an immutable release directory,
and atomically switches `/opt/sentryalert-diagnostics/current`.

An active session is restarted after an update and resumes from persistent state.
Installation enables the service for reboot recovery but does not start diagnostics.

Default uninstall preserves `/mutable/diagnostics`. `--purge` removes it.

## Service security

The runner needs read access to kernel logs, sysfs, configfs, mounts, and block
devices. The systemd service nevertheless uses a read-only system filesystem,
private temporary directory, protected home directories, protected control groups
and kernel modules, no-new-privileges, and a single writable diagnostics path.

`PrivateDevices` and `ProtectKernelLogs` are intentionally not enabled because they
would hide the evidence this module exists to collect.

## Known constraints

- Some kernels restrict `dmesg`; the collector falls back to the current boot's
  kernel journal and records command failures.
- Existing kernel messages form an event baseline after service start. They remain
  in periodic evidence, but do not create a burst of stale snapshots.
- Telegram availability and file-size limits are external. Failed bundles remain
  local for manual resend.
- USB serial numbers and filesystem identifiers can be diagnostically valuable and
  may appear in the bundle. Tokens and chat IDs do not.
- Some deployed SentryAlert images omit both `package.json` and `package-lock.json`.
  The collector then reads the explicit first-line version banner from the bundled
  `app.js`; if neither source exists, the version is reported as unavailable.
