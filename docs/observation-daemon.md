# JQE observation daemon

The daemon is read-only and watches `JQE_OBSERVATION_SYMBOLS` independently of
the dashboard's default timeframe. Application logs use JQE's existing rotating
Loguru file sink (`JQE_LOG_DIR`, `JQE_LOG_FILE`, `JQE_LOG_ROTATION`, and
`JQE_LOG_RETENTION`); console output is optional.

Before installation, edit the `<UserId>` in `deploy/jqe-observation-daemon.xml`
if the Windows account name differs. Import the task manually from an elevated
PowerShell prompt; Windows will request the account password so it can run when
the user is logged off:

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
directory. Structured failures and fatal exits are written to the rotating JQE
log. The task is deliberately not installed by repository code.
