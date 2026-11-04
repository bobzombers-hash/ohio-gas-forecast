"""Register / remove / inspect the recurring self-update job for this project.

macOS  -> LaunchAgent  ~/Library/LaunchAgents/com.ohiogas.forecast.plist
Linux  -> user crontab entry tagged '# ohio-gas-forecast'
Windows-> Task Scheduler task 'OhioGasForecast' (schtasks)

Strategy (robust to sleep / power-off / offline): the scheduler wakes the job HOURLY, and the
job itself exits immediately unless the last *successful* refresh is older than the chosen
interval (daily ~20h, weekly ~6.5 days). So a laptop that was asleep or offline at the usual
time catches up within an hour of waking/reconnecting, and failed (offline) runs simply retry
next hour while the last good data and dashboard stay in place.
"""
import json, os, platform, plistlib, shlex, subprocess, sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "forecast.py")
LOGS = os.path.join(HERE, "logs")
STATE = os.path.join(HERE, "data", "schedule_state.json")
CONFIG = os.path.join(HERE, "data", "schedule_config.json")
TAG = "# ohio-gas-forecast"
LABEL = "com.ohiogas.forecast"
WIN_TASK = "OhioGasForecast"
INTERVALS = {"daily": timedelta(hours=20), "weekly": timedelta(days=6, hours=12)}

def python_exe():
    return os.path.abspath(sys.executable)

def job_args(windowless=False):
    exe = python_exe()
    if windowless and platform.system() == "Windows":
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")   # no console window flashing every hour
        if os.path.exists(w):
            exe = w
    return [exe, SCRIPT, "--scheduled"]

def _win_task_xml(freq):
    """Task Scheduler XML for the current user, no admin needed: hourly repetition, runs on battery,
    starts ASAP after a missed run (sleep/off), only one instance at a time, 30 min limit."""
    from xml.sax.saxutils import escape
    exe, script, flag = job_args(windowless=True)
    user = os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")
    start = (datetime.now() + timedelta(minutes=2)).replace(second=0, microsecond=0).isoformat()
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Ohio gas price forecaster: hourly check, refreshes {freq}. Project: {escape(HERE)}</Description></RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition><Interval>PT1H</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals><Principal id="Author"><UserId>{escape(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{escape(exe)}</Command><Arguments>"{escape(script)}" {flag}</Arguments><WorkingDirectory>{escape(HERE)}</WorkingDirectory></Exec>
  </Actions>
</Task>
"""

def _plist_path():
    return os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")

# ---------------- state ----------------
def load_json(p, default):
    try:
        return json.load(open(p))
    except Exception:
        return default

def save_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    json.dump(obj, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, p)

def every():
    return load_json(CONFIG, {}).get("every", "daily")

def due(force=False):
    if force:
        return True, "forced"
    st = load_json(STATE, {})
    last = st.get("last_success")
    if not last:
        return True, "no successful run recorded yet"
    age = datetime.now() - datetime.fromisoformat(last)
    need = INTERVALS.get(every(), INTERVALS["daily"])
    if age >= need:
        return True, f"last success {age} ago >= {need}"
    return False, f"last success {last} ({str(age).split('.')[0]} ago) is fresh for '{every()}' schedule"

def record(success, note=""):
    st = load_json(STATE, {})
    now = datetime.now().isoformat(timespec="seconds")
    st["last_attempt"] = now
    st["last_result"] = "success" if success else f"failed: {note}"
    if success:
        st["last_success"] = now
    save_json(STATE, st)

# ---------------- install ----------------
def install(freq="daily"):
    if freq not in INTERVALS:
        raise SystemExit("--every must be daily or weekly")
    os.makedirs(LOGS, exist_ok=True)
    save_json(CONFIG, {"every": freq, "python": python_exe(), "project": HERE,
                       "installed": datetime.now().isoformat(timespec="seconds")})
    system = platform.system()
    if system == "Darwin":
        p = _plist_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        plist = {
            "Label": LABEL,
            "ProgramArguments": job_args(),
            "WorkingDirectory": HERE,
            "StartCalendarInterval": [{"Minute": 17}],   # hourly wake-up; missed slots during sleep coalesce into one run on wake
            "RunAtLoad": True,                            # also check at login / after reboot
            "StandardOutPath": os.path.join(LOGS, "launchd.out.log"),
            "StandardErrorPath": os.path.join(LOGS, "launchd.err.log"),
            "EnvironmentVariables": {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "MPLBACKEND": "Agg"},
            "ProcessType": "Background",
        }
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", p], capture_output=True)
        with open(p, "wb") as fh:
            plistlib.dump(plist, fh)
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", p], capture_output=True, text=True)
        if r.returncode != 0:  # older macOS
            r = subprocess.run(["launchctl", "load", "-w", p], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"launchctl failed: {r.stderr.strip()}")
        print(f"Installed LaunchAgent {p} (checks hourly, refreshes {freq}).")
    elif system == "Linux":
        cmd = f"cd {shlex.quote(HERE)} && MPLBACKEND=Agg {' '.join(shlex.quote(a) for a in job_args())} >> {shlex.quote(os.path.join(LOGS, 'cron.log'))} 2>&1"
        lines = [l for l in _crontab_lines() if TAG not in l]
        lines += [f"17 * * * * {cmd} {TAG}", f"@reboot sleep 120 && {cmd} {TAG}"]
        _write_crontab(lines)
        print(f"Installed crontab entries (checks hourly + at boot, refreshes {freq}):")
        for l in lines:
            if TAG in l:
                print("  " + l)
        if not _cron_running():
            print("WARNING: no cron daemon appears to be running on this machine; the entry will not fire until cron runs.")
    elif system == "Windows":
        xml_path = os.path.join(HERE, "data", "task.xml")
        with open(xml_path, "w", encoding="utf-16") as fh:
            fh.write(_win_task_xml(freq))
        r = subprocess.run(["schtasks", "/Create", "/F", "/TN", WIN_TASK, "/XML", xml_path], capture_output=True, text=True)
        how = "XML (hourly, runs on battery, catches up after sleep)"
        if r.returncode != 0:   # fallback: plain hourly task
            print(f"XML registration failed ({(r.stderr or r.stdout).strip()}); falling back to basic hourly task.")
            tr = subprocess.list2cmdline(job_args(windowless=True))
            r = subprocess.run(["schtasks", "/Create", "/F", "/SC", "HOURLY", "/MO", "1", "/TN", WIN_TASK, "/TR", tr],
                               capture_output=True, text=True)
            how = "basic hourly (note: Windows default may skip runs on battery)"
        if r.returncode != 0:
            raise SystemExit(f"schtasks failed: {r.stderr.strip() or r.stdout.strip()}")
        print(f"Installed Task Scheduler task '{WIN_TASK}' via {how}; refreshes {freq}.")
        print("  Runs: " + subprocess.list2cmdline(job_args(windowless=True)))
    else:
        raise SystemExit(f"Unsupported OS: {system}")

def uninstall():
    system = platform.system()
    if system == "Darwin":
        p = _plist_path()
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", p], capture_output=True)
        subprocess.run(["launchctl", "unload", "-w", p], capture_output=True)
        if os.path.exists(p):
            os.remove(p)
        print("Removed LaunchAgent.")
    elif system == "Linux":
        lines = _crontab_lines()
        _write_crontab([l for l in lines if TAG not in l])
        print(f"Removed {sum(TAG in l for l in lines)} crontab entr(ies).")
    elif system == "Windows":
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", WIN_TASK], capture_output=True)
        print(f"Removed task '{WIN_TASK}'.")

def status():
    system = platform.system()
    print(f"OS: {system}   project: {HERE}   python: {python_exe()}")
    cfg = load_json(CONFIG, {})
    print(f"Configured frequency: {cfg.get('every', '(not installed)')}")
    if system == "Darwin":
        p = _plist_path()
        r = subprocess.run(["launchctl", "list", LABEL], capture_output=True, text=True)
        print(f"LaunchAgent file: {'present' if os.path.exists(p) else 'missing'} ({p}); loaded: {'yes' if r.returncode == 0 else 'no'}")
    elif system == "Linux":
        entries = [l for l in _crontab_lines() if TAG in l]
        print(f"Crontab entries: {len(entries)}")
        for l in entries:
            print("  " + l)
        print(f"cron daemon running: {'yes' if _cron_running() else 'NO - entries will not fire'}")
    elif system == "Windows":
        r = subprocess.run(["schtasks", "/Query", "/TN", WIN_TASK, "/V", "/FO", "LIST"], capture_output=True, text=True)
        print(f"Task '{WIN_TASK}': {'present' if r.returncode == 0 else 'missing'}")
        for line in r.stdout.splitlines():
            if any(k in line for k in ("Status:", "Next Run Time:", "Last Run Time:", "Last Result:", "Task To Run:")):
                print("  " + line.strip())
    st = load_json(STATE, {})
    print(f"Last attempt: {st.get('last_attempt', '-')}  result: {st.get('last_result', '-')}")
    print(f"Last success: {st.get('last_success', '-')}")
    print(f"Next refresh due: {due()[1]}")
    dash = os.path.join(HERE, "output", "dashboard.html")
    if os.path.exists(dash):
        print(f"Dashboard: {dash} (modified {datetime.fromtimestamp(os.path.getmtime(dash)).isoformat(timespec='seconds')})")
    log = os.path.join(LOGS, "run.log")
    if os.path.exists(log):
        print("Last log lines:")
        print("".join(open(log, encoding="utf-8", errors="replace").readlines()[-8:]), end="")

# ---------------- helpers ----------------
def _crontab_lines():
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit("`crontab` command not found. Install cron (e.g. `sudo apt-get install cron`) and retry.")
    return [l for l in r.stdout.splitlines()] if r.returncode == 0 else []

def _write_crontab(lines):
    text = "\n".join(lines).strip() + "\n" if lines else ""
    r = subprocess.run(["crontab", "-"], input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"crontab write failed: {r.stderr.strip()}")

def _cron_running():
    r = subprocess.run(["sh", "-c", "pgrep -x cron || pgrep -x crond || pgrep -f cronie"], capture_output=True)
    return r.returncode == 0
