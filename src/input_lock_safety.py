"""Supervised lid suppression, not a replacement machine power controller.

Pure decisions are separate from telemetry and the fixed AAG service adapter.
No incident-time thermal evidence established the cause of the 2026-09-11 stop.
"""
from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

LOG = logging.getLogger("input-lock-safety")
BREADCRUMB = Path("/var/lib/input-lock/safety.json")
PROTECT_UNIT = "input-lock-protect.service"
FAILSAFE_UNIT = "aag-suspend-failure-failsafe.service"
AAG_TRANSACTION_CONFIG = Path("/etc/aag-sleep-transaction/config.json")
THERMAL_MEASUREMENTS = ("NORMAL", "WARNING", "HIGH_RISK", "EMERGENCY")
THERMAL_STATES = ("NORMAL", "WARNING", "HIGH_RISK", "EMERGENCY_SOFTWARE_PROTECTION")


def atomic_json(path: Path, value: dict) -> None:
    """Keep the previous complete record on write failure; sync its directory."""
    fd, temporary = tempfile.mkstemp(prefix=".safety-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(temporary).unlink(missing_ok=True)


@dataclass(frozen=True)
class Sensor:
    identity: str
    kind: str
    celsius: float
    warning: float
    high: float
    emergency: float

    def risk(self, hysteresis: float = 0) -> int:
        for level, threshold in ((3, self.emergency), (2, self.high), (1, self.warning)):
            if self.celsius >= threshold - hysteresis:
                return level
        return 0


@dataclass
class Sample:
    at: float
    lid_closed: bool | None
    sensors: list[Sensor] = field(default_factory=list)
    ac: bool | None = None
    battery: float | None = None
    discharging: bool | None = None
    warning_level: int | None = None
    cpu_busy: float | None = None
    dependencies_ok: bool = False
    stack_ready: bool = False
    errors: list[str] = field(default_factory=list)

    def healthy(self, now: float) -> bool:
        kinds = {sensor.kind for sensor in self.sensors}
        return (0 <= now - self.at <= 12 and self.lid_closed is not None
                and {"cpu", "chassis"} <= kinds and self.ac is not None
                and self.battery is not None and self.discharging is not None
                and self.dependencies_ok and self.stack_ready and not self.errors)


class SafetyPolicy:
    """Monotonic, bounded, deterministic policy. It never performs power actions."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.state = "SAFE_NORMAL"
        self.armed = False
        self.closed_since = None
        self.deadline = None
        self.missing_since = None
        self.thermal_level = 0
        self.thermal_candidate = 0
        self.thermal_since = None
        self.critical_since = None
        self.sample: Sample | None = None
        self.reason = "SAFE_STATE_RESTORED"
        self.events: list[str] = []
        self.required_sensors: set[str] = set()
        self.previous_ac = None
        self.busy_since = None

    def event(self, reason: str) -> None:
        self.events.append(reason)
        LOG.info("event=%s state=%s", reason, self.state)

    def transition(self, state: str, reason: str) -> None:
        if self.state != state or self.reason != reason:
            self.state, self.reason = state, reason
            self.event(reason)

    def arm(self, sample: Sample) -> None:
        if not sample.healthy(self.clock()) or sample.lid_closed is not False:
            raise ValueError("Open the lid and restore safety telemetry/AAG services before arming")
        if any(sensor.risk() >= 2 for sensor in sample.sensors):
            raise ValueError("Temperature is already too high to arm lid-ignore")
        # A prior protection attempt can retain its forensic timer after
        # disarming. Explicit re-arm with a freshly observed open lid starts
        # a new episode even if no periodic open-lid update ran in between.
        self.release()
        self.previous_ac = sample.ac
        self.required_sensors = {s.identity for s in sample.sensors}
        self.armed = True
        self.sample = sample
        self.transition("LID_IGNORE_ARMED", "LID_IGNORE_ARMED")

    def release(self, reason: str = "SAFE_STATE_RESTORED") -> None:
        self.armed = False
        self.closed_since = self.deadline = self.missing_since = None
        self.thermal_since = self.critical_since = self.busy_since = None
        self.thermal_level = self.thermal_candidate = 0
        self.transition("SAFE_NORMAL", reason)

    def update(self, sample: Sample) -> str | None:
        now = self.clock()
        self.sample = sample
        if not self.armed:
            return None
        if sample.lid_closed is False:
            if self.closed_since is not None:
                self.event("LID_OPENED")
                self.event("SAFETY_TIMER_CANCELLED")
            self.closed_since = self.deadline = self.missing_since = None
            self.thermal_since = self.critical_since = self.busy_since = None
            self.thermal_level = self.thermal_candidate = 0
            self.transition("LID_IGNORE_ARMED", "LID_IGNORE_ARMED")
            return None
        if self.closed_since is None:
            self.closed_since = now
            self.deadline = now + 240
            self.transition("LID_CLOSED_MONITORED", "LID_CLOSED")
            self.event("SAFETY_TIMER_STARTED")
        # Unknown lid state is conservatively supervised as closed. Recovery of
        # a dependency must never restart the closed-lid deadline.
        ids = {s.identity for s in sample.sensors}
        healthy = sample.healthy(now) and self.required_sensors <= ids
        if not healthy:
            if self.missing_since is None:
                self.missing_since = now
                self.event("TELEMETRY_LOST")
            if now - self.missing_since >= 15:
                return self.decide("TELEMETRY_LOST")
        else:
            if self.missing_since is not None:
                self.event("TELEMETRY_RESTORED")
            self.missing_since = None
        if self.previous_ac is not None and self.previous_ac != sample.ac:
            self.event("AC_CONNECTED" if sample.ac else "AC_LOST")
        self.previous_ac = sample.ac
        # Load shortens an already finite, non-destructive suspend deadline.
        if sample.cpu_busy is not None and sample.cpu_busy >= .75:
            if self.busy_since is None:
                self.busy_since = now
        else:
            self.busy_since = None
        if sample.ac is False or (self.busy_since is not None and now - self.busy_since >= 10):
            self.deadline = min(self.deadline, self.closed_since + 120)
        raw = max((s.risk() for s in sample.sensors), default=0)
        if raw < self.thermal_level and any(s.risk(3) >= self.thermal_level for s in sample.sensors):
            raw = self.thermal_level
        if raw != self.thermal_candidate:
            self.thermal_candidate, self.thermal_since = raw, now
        if self.thermal_since is None:
            self.thermal_since = now
        dwell = {0: 15, 1: 10, 2: 6, 3: 2}[raw]
        if raw != self.thermal_level and now - self.thermal_since >= dwell:
            self.thermal_level = raw
            self.event(("THERMAL_NORMAL", "THERMAL_WARNING", "THERMAL_HIGH_RISK", "THERMAL_EMERGENCY")[raw])
        critical = ((sample.battery is not None and sample.battery <= 10)
                    or (sample.warning_level is not None and sample.warning_level >= 4))
        if critical:
            if self.critical_since is None:
                self.critical_since = now
                self.event("BATTERY_CRITICAL")
            if now - self.critical_since >= 2:
                return self.decide("BATTERY_CRITICAL")
        else:
            self.critical_since = None
        if self.thermal_level >= 2:
            return self.decide("THERMAL_HIGH_RISK" if self.thermal_level == 2 else "THERMAL_EMERGENCY")
        if now >= self.deadline:
            return self.decide("CLOSED_LID_DEADLINE")
        elapsed = now - self.closed_since
        duration = self.deadline - self.closed_since
        if elapsed >= duration * .75:
            self.transition("LID_CLOSED_HIGH_RISK", "SAFETY_DEADLINE_NEAR")
        elif (elapsed >= duration * .5 or self.thermal_level >= 1 or not healthy
              or (sample.battery is not None and sample.battery <= 20)):
            self.transition("LID_CLOSED_WARNING", "BATTERY_WARNING" if sample.battery is not None and sample.battery <= 20 else "SAFETY_WARNING")
        else:
            self.transition("LID_CLOSED_MONITORED", "MONITORING")
        return None

    def decide(self, reason: str) -> str:
        self.armed = False  # One dispatch per explicit arm.
        self.transition("PROTECTIVE_ACTION_PENDING", "PROTECTIVE_ACTION_DECIDED")
        self.reason = reason
        return reason

    def measured_thermal(self) -> dict:
        """Describe the sample, independently of intervention arming/dwell."""
        sample = self.sample
        fresh = sample is not None and 0 <= self.clock() - sample.at <= 12
        sensors = sample.sensors if sample is not None else []
        valid = [s for s in sensors if math.isfinite(s.celsius)]
        complete = (fresh and {"cpu", "chassis"} <= {s.kind for s in valid}
                    and self.required_sensors <= {s.identity for s in valid}
                    and len(valid) == len(sensors) and not sample.errors)
        risk = max((s.risk() for s in valid), default=0)
        # A missing sensor must not hide a known hot reading. An incomplete
        # normal sample, however, cannot certify a normal thermal condition.
        state = (THERMAL_MEASUREMENTS[risk] if fresh and valid and (complete or risk > 0)
                 else "UNKNOWN")
        return {"state": state, "fresh": bool(fresh), "complete": bool(complete)}

    def snapshot(self) -> dict:
        measured = self.measured_thermal()
        return {"state": self.state, "reason": self.reason, "closed_since": self.closed_since,
                "deadline": self.deadline, "thermal": measured["state"],
                "thermal_measurement": measured,
                "protection_armed": self.armed,
                "thermal_protection": "ARMED" if self.armed else "DISARMED",
                "thermal_intervention": THERMAL_STATES[self.thermal_level] if self.armed else "DISARMED",
                "sample": asdict(self.sample) if self.sample else None}


class Telemetry:
    """Kernel drivers/types identify sensors; numbering and display labels do not."""
    def __init__(self, sys_root=Path("/sys"), proc_root=Path("/proc")):
        self.sys, self.proc = sys_root, proc_root
        self.previous_cpu = None

    @staticmethod
    def number(path: Path) -> float | None:
        try:
            value = float(path.read_text().strip())
            return value if math.isfinite(value) else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def temperature(path: Path) -> float | None:
        value = Telemetry.number(path)
        return value / 1000 if value is not None and 1000 <= value <= 150000 else None

    def read(self, *, dependencies_ok=False, stack_ready=False, warning_level=None) -> Sample:
        observed_at = time.monotonic()
        sensors = []
        errors = []
        for zone in (self.sys / "class/thermal").glob("thermal_zone*"):
            try:
                kind = (zone / "type").read_text().strip()
            except OSError:
                continue
            category = "cpu" if kind in {"TCPU", "x86_pkg_temp"} else "chassis" if kind in {"SEN1", "SEN2"} else None
            if category is None:
                continue
            value = self.temperature(zone / "temp")
            trips = {}
            for p in zone.glob("trip_point_*_type"):
                try:
                    trip_kind = p.read_text().strip()
                    temperature = self.temperature(p.with_name(p.name.replace("_type", "_temp")))
                    if temperature is not None:
                        trips[trip_kind] = min(trips.get(trip_kind, 150), temperature)
                except OSError:
                    continue
            if value is None:
                errors.append(f"unreadable:{kind}")
                continue
            crit = trips.get("critical", 110 if category == "cpu" else 80)
            limits = ((min(85, crit - 25), min(95, crit - 15), min(100, crit - 10))
                      if category == "cpu" else (min(65, crit - 20), min(70, crit - 12), min(73, crit - 7)))
            sensors.append(Sensor(f"thermal:{kind}", category, value, *limits))
        for hwmon in (self.sys / "class/hwmon").glob("hwmon*"):
            try:
                driver = (hwmon / "name").read_text().strip()
            except OSError:
                continue
            if driver not in {"coretemp", "k10temp", "nvme"}:
                continue
            # NVMe composite temp1 has specified critical limits; secondary
            # controller sensors may have invalid firmware max values.
            inputs = [hwmon / "temp1_input"] if driver == "nvme" else list(hwmon.glob("temp*_input"))
            readings, criticals = [], []
            for p in inputs:
                value = self.temperature(p)
                if value is None:
                    errors.append(f"unreadable:{driver}:{p.stem}")
                    continue
                readings.append(value)
                critical = self.temperature(p.with_name(p.name.replace("_input", "_crit")))
                if critical is not None:
                    criticals.append(critical)
            if readings:
                # Summarize per driver/device using the hottest valid channel
                # and lowest valid trip. Identity survives channel reordering.
                identity = f"hwmon:{driver}:{hwmon.resolve().parent}"
                category = "storage" if driver == "nvme" else "cpu"
                crit = min(criticals, default=85 if category == "storage" else 100)
                limits = ((min(70, crit - 15), min(77, crit - 10), min(80, crit - 5))
                          if category == "storage" else (min(85, crit - 25), min(95, crit - 15), min(100, crit - 10)))
                sensors.append(Sensor(identity, category, max(readings), *limits))
        if not {"thermal:SEN1", "thermal:SEN2"} <= {sensor.identity for sensor in sensors}:
            errors.append("required-firmware-chassis-zones-unavailable")
        ac_values, batteries, discharging = [], [], []
        for p in (self.sys / "class/power_supply").glob("*"):
            try:
                kind = (p / "type").read_text().strip()
                if kind == "Mains":
                    value = self.number(p / "online")
                    if value in (0, 1):
                        ac_values.append(bool(value))
                elif kind == "Battery":
                    value = self.number(p / "capacity")
                    if value is not None and 0 <= value <= 100:
                        batteries.append(value)
                    discharging.append((p / "status").read_text().strip() == "Discharging")
            except OSError:
                errors.append("power-supply-unreadable")
        lids = []
        for p in (self.proc / "acpi/button/lid").glob("*/state"):
            try:
                value = p.read_text().lower().split()[-1]
                if value in {"open", "closed"}:
                    lids.append(value == "closed")
            except (OSError, IndexError):
                pass
        cpu_busy = None
        try:
            values = [int(v) for v in (self.proc / "stat").read_text().splitlines()[0].split()[1:9]]
            total, idle = sum(values), values[3] + values[4]
            if self.previous_cpu is not None:
                delta = total - self.previous_cpu[0]
                if delta > 0:
                    cpu_busy = max(0., min(1., 1 - (idle - self.previous_cpu[1]) / delta))
            self.previous_cpu = total, idle
        except (OSError, ValueError, IndexError):
            pass  # Optional multiplier, never required for the finite deadline.
        return Sample(observed_at, any(lids) if lids else None, sensors,
                      any(ac_values) if ac_values else None,
                      min(batteries) if batteries else None,
                      any(discharging) if discharging else None, warning_level,
                      cpu_busy, dependencies_ok, stack_ready, errors)


def stack_ready(run=subprocess.run) -> bool:
    # AAG transaction adapter contract; preserve legacy fallback.
    if AAG_TRANSACTION_CONFIG.exists():
        from aag_sleep_transaction_compat import stack_ready as adapter_contract
        return adapter_contract(run)
    """Check effective systemd dependencies, including locally merged drop-ins."""
    requirements = {
        "systemd-suspend.service": ("aag-storage-sleep-v2.service", FAILSAFE_UNIT,
                                    "aag-ordinary-suspend-usbclone-gate", "aag-t700-auto"),
        "aag-storage-sleep-v2.service": ("aag-ugreen-sleep-guard-v2", "aag-sleep-recovery"),
        FAILSAFE_UNIT: ("aag-sleep-recovery failure-recover", "aag-hibernate-qualifier"),
        PROTECT_UNIT: ("input_lock_safety.py",),
    }
    try:
        for unit, tokens in requirements.items():
            result = run(["/usr/bin/systemctl", "show", unit, "--property=LoadState,Requires,OnFailure,ExecStart,ExecStartPre,ExecCondition"],
                         capture_output=True, text=True, timeout=3, check=False)
            if result.returncode or "LoadState=loaded" not in result.stdout or not all(token in result.stdout for token in tokens):
                return False
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def request_service() -> str:
    """Narrow, authorized systemd request; the daemon never prepares storage."""
    import dbus
    bus = dbus.SystemBus(private=True)
    try:
        manager = dbus.Interface(bus.get_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1"), "org.freedesktop.systemd1.Manager")
        return str(manager.StartUnit(PROTECT_UNIT, "replace", timeout=5))
    finally:
        bus.close()


def suspend_success_count() -> int:
    value = int(Path("/sys/power/suspend_stats/success").read_text().strip())
    if value < 0:
        raise ValueError("invalid kernel suspend success counter")
    return value


def aag_resume_confirmed(requested_at: float) -> bool:
    # AAG transaction adapter contract; preserve legacy fallback.
    if AAG_TRANSACTION_CONFIG.exists():
        from aag_sleep_transaction_compat import resume_confirmed as adapter_contract
        return adapter_contract(requested_at)
    try:
        receipt = json.loads(Path("/run/aag-ugreen-safety-r1/last-terminal.json").read_text())
        return (receipt.get("boot_id") == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
                and receipt.get("state") == "RESUME_COMPLETE"
                and float(receipt.get("episode_started_monotonic", -1)) >= requested_at)
    except (OSError, ValueError, TypeError):
        return False


def observe_suspend(run, requested_at: float, before_success: int, *, clock=time.monotonic,
                    sleep=time.sleep, counter=suspend_success_count, resume=aag_resume_confirmed) -> None:
    """A successful enqueue is not a completed sleep/resume operation."""
    deadline = clock() + 120
    while clock() < deadline:
        result = run(["/usr/bin/systemctl", "show", "systemd-suspend.service",
                      "--property=ActiveState,Result,ExecMainStatus,InactiveExitTimestampMonotonic,ExecMainStartTimestampMonotonic,ExecMainExitTimestampMonotonic"],
                     capture_output=True, text=True, check=False, timeout=3)
        if result.returncode:
            raise RuntimeError("cannot observe the existing suspend service")
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        activation = int(values.get("InactiveExitTimestampMonotonic", "0")) / 1_000_000
        if activation >= requested_at:
            if values.get("Result") not in {None, "success"} or values.get("ActiveState") == "failed":
                raise RuntimeError("existing suspend service failed: " + values.get("Result", "unknown"))
            start = int(values.get("ExecMainStartTimestampMonotonic", "0"))
            end = int(values.get("ExecMainExitTimestampMonotonic", "0"))
            if (start / 1_000_000 >= requested_at and end >= start
                    and values.get("ActiveState") == "inactive" and values.get("Result") == "success"
                    and values.get("ExecMainStatus") == "0" and counter() > before_success
                    and resume(requested_at)):
                return
        sleep(1)
    raise TimeoutError("suspend completion was not observed within the awake-time budget")


def protect_main(run=subprocess.run, probe=stack_ready, telemetry=None, path=BREADCRUMB, observe=observe_suspend, counter=suspend_success_count) -> int:
    """Root oneshot adapter. All dangerous transitions belong to existing AAG units.

    No direct shutdown, force flags, hardware reset, or hibernate dispatch exists
    here. Plain hibernate has separate platform acceptance, but the current AAG
    closed-lid failure owner has no automatic hibernate fallback contract.
    """
    telemetry = telemetry or Telemetry()
    state = {}
    def record(result: str, detail: str = "") -> None:
        receipt = path.with_name("safety-action-result.json")
        atomic_json(receipt, {"schema": 1, "boot_id": state.get("boot_id"),
                    "generation": state.get("generation"), "result": result,
                    "detail": detail, "observed_at": time.time(),
                    "transition_status": {"suspend-requested": "REQUESTED",
                        "suspend-request-accepted": "ACCEPTED", "suspend-transition-confirmed": "CONFIRMED",
                        "delegated-to-existing-failsafe": "RECOVERY_REQUIRED",
                        "failsafe-request-failed": "FAILED"}.get(result, "CANCELLED"),
                    "transition_confirmed": result == "suspend-transition-confirmed"})
        os.chmod(receipt, 0o644)  # Readable by the unprivileged daemon.
    try:
        state = json.loads(path.read_text())
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if (state.get("boot_id") != boot or state.get("safety", {}).get("state") != "PROTECTIVE_ACTION_PENDING"):
            LOG.warning("event=PROTECTIVE_ACTION_CANCELLED reason=stale-or-cancelled-request")
            return 0
        if telemetry.read().lid_closed is False:
            LOG.info("event=PROTECTIVE_ACTION_CANCELLED reason=lid-opened")
            record("cancelled-lid-open")
            return 0
        if not 0 <= time.time() - state.get("updated_at", 0) <= 20:
            raise RuntimeError("pending closed-lid request expired; recovery required")
        if not probe():
            raise RuntimeError("AAG suspend graph is unavailable or changed")
        current = json.loads(path.read_text())
        if (current.get("generation") != state.get("generation") or
                current.get("safety", {}).get("state") != "PROTECTIVE_ACTION_PENDING" or
                telemetry.read().lid_closed is False):
            LOG.info("event=PROTECTIVE_ACTION_CANCELLED reason=cancelled-before-dispatch")
            record("cancelled-before-dispatch")
            return 0
        LOG.warning("event=PROTECTIVE_ACTION_STARTED path=logind-and-existing-AAG-suspend")
        before_success = counter()
        requested_at = time.monotonic()
        record("suspend-requested")
        result = run(["/usr/bin/systemctl", "--check-inhibitors=yes", "suspend"], timeout=10, check=False)
        if result.returncode:
            raise RuntimeError(f"suspend request failed: {result.returncode}")
        record("suspend-request-accepted")
        observe(run, requested_at, before_success)
        LOG.info("event=PROTECTIVE_ACTION_SUCCEEDED result=suspend-transition-confirmed")
        record("suspend-transition-confirmed")
        return 0
    except Exception as exc:
        LOG.error("event=PROTECTIVE_ACTION_FAILED error=%s", exc)
        # The existing recovery owner rechecks physical lid, thermal state,
        # storage owners and immutable episode deadlines before any action.
        try:
            result = run(["/usr/bin/systemctl", "--no-block", "start", FAILSAFE_UNIT], timeout=8, check=False)
            record("delegated-to-existing-failsafe" if result.returncode == 0 else "failsafe-request-failed", str(exc))
            return 0 if result.returncode == 0 else 1
        except (OSError, subprocess.TimeoutExpired):
            return 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Request the installed AAG protective path")
    parser.add_argument("action", choices=("protect",))
    parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    if os.geteuid() != 0:
        raise SystemExit("protective adapter requires the installed root service")
    raise SystemExit(protect_main())
