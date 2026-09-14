# JQE observation daemon

The daemon is read-only and watches `JQE_OBSERVATION_SYMBOLS` independently of
the dashboard's default timeframe. It handles its own durable logging; Task
Scheduler stdout/stderr capture is not required. The existing Loguru file sink
writes to `D:\JQE\logs\jqe.log` with the current defaults, rotates at 10 MB,
and retains rotated files for 14 days. These values come from `JQE_LOG_DIR`,
`JQE_LOG_FILE`, `JQE_LOG_ROTATION`, and `JQE_LOG_RETENTION`. Connection failures,
cycle failures, retry/backoff, disconnect failures, fatal exits, and every
heartbeat are written to that file. Console logging is optional and is not the
durable sink.

Before installation, edit the `<UserId>` in `deploy/jqe-observation-daemon.xml`
if the Windows account name differs. The principal uses `S4U`, so Task Scheduler
does not store the account password and the task has no interactive desktop or
network-logon dependency. The account must have **Log on as a batch job**.

To check that right without changing it, run `secpol.msc`, open **Local Policies
→ User Rights Assignment → Log on as a batch job**, and verify the account (or
a group containing it) is listed. Also verify it is not covered by **Deny log on
as a batch job**. If the right is missing, an administrator can add the account
through that same policy editor and apply local policy; this repository does not
grant or modify the right. On editions without `secpol.msc`, the equivalent must
be assigned through Local Security Policy/Group Policy by an administrator.

Import the task manually from an elevated PowerShell prompt:

```powershell
schtasks /Create /TN "JQE Observation Daemon" /XML "D:\JQE\deploy\jqe-observation-daemon.xml"
```

Inspect it without starting it:

```powershell
schtasks /Query /TN "JQE Observation Daemon" /V /FO LIST
```

Start only after reviewing configuration and the XML:

```powershell
schtasks /Run /TN "JQE Observation Daemon"
```

The XML starts at boot, runs without an interactive login, ignores overlapping
starts, retries five times at one-minute intervals after a nonzero exit, never
times out a healthy long-running process, and uses `D:\JQE` as its working
directory. The five-retry ceiling is intentional: ordinary MT5 disconnects,
authentication failures, and market/API errors are handled inside the daemon
with capped backoff and do not consume Task Scheduler restart attempts. A
nonzero process exit represents an unexpected defect, so five crashes in close
succession should remain stopped and visible for investigation until the next
boot or an explicit manual `/Run`. The task is deliberately not installed by
repository code.

After the daemon runs, check `D:\JQE\logs\jqe.log` and its Loguru-rotated sibling
files for `OBSERVATION_` events. The SQLite heartbeat and cursor are stored in
`D:\JQE\state\live_paper_operational\observation_daemon.evidence.sqlite3`.
