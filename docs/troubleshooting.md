> Beta.2 power/lid behavior is documented in [the safety remediation](SAFETY-REMEDIATION-20260911.md). Persistent GNOME/UPower suppression is removed; do not recreate it.

# Troubleshooting

Start every investigation while input is released:

```bash
sudo input-lock emergency-unlock
input-lock doctor
input-lock status --json
journalctl -u input-lock.service -b --no-pager -n 200
```

Each section gives diagnosis, expected meaning, repair, and rollback.

## Shortcut does not act

Diagnosis:

```bash
python3 /usr/lib/input-lock/input_lock_gnome.py status
input-lock logs -n 100
```

Expected: both paths and bindings are printed; the journal shows `reason=primary-hotkey` or `reason=gnome-primary-hotkey`. If the raw listener missed the node, the GNOME fallback should still call IPC.

Repair:

```bash
python3 /usr/lib/input-lock/input_lock_gnome.py check
python3 /usr/lib/input-lock/input_lock_gnome.py install
sudo systemctl restart input-lock.service
```

Rollback:

```bash
python3 /usr/lib/input-lock/input_lock_gnome.py remove
sudo systemctl restart input-lock.service
```

## Keyboard locks but mouse does not, or Touchpad is absent

Diagnosis:

```bash
input-lock list-devices
sudo libinput list-devices
udevadm info --query=property --name=/dev/input/eventX | grep '^ID_INPUT'
```

Expected: the relevant event node has class `mouse`/`touchpad`. A node absent from the daemon list lacks a safe udev tag/capability match.

Repair: update the device's normal Ubuntu/libinput/udev support; do not change the daemon to grab every `event*`. As a temporary investigation, record the complete `udevadm` and `evtest` identification and report it before changing classification code.

Rollback: remove any locally-added udev rule and run:

```bash
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=input
sudo systemctl restart input-lock.service
```

## Bluetooth device is not locked

Diagnosis:

```bash
sudo udevadm monitor --udev --property --subsystem-match=input
input-lock logs -n 100
```

Expected: reconnect creates one or more `event` nodes and journal logs `Input device detected`. A grab failure intentionally leaves the new device usable.

Repair:

```bash
sudo systemctl restart systemd-udevd.service
sudo systemctl restart input-lock.service
```

Rollback: restart is reversible; no persistent setting changed.

## Notification is not displayed

Diagnosis:

```bash
systemctl --user status input-lock-notifier.service --no-pager
journalctl --user -u input-lock-notifier.service -b --no-pager -n 100
echo "$DBUS_SESSION_BUS_ADDRESS"
notify-send 'Input Lock test'
```

Expected: user service active and direct notification visible.

The unit must show `After=... gnome-session-initialized.target`. Older units
that start only after `graphical-session-pre.target` can run before GNOME has
published `DISPLAY`/`WAYLAND_DISPLAY`, producing `Can't create a
GtkStyleContext without a display connection` and repeated core dumps.

Repair:

```bash
systemctl --user daemon-reload
systemctl --user enable --now input-lock-notifier.service
```

Rollback:

```bash
systemctl --user disable --now input-lock-notifier.service
```

The lock mechanism continues without notifications.

## Cursor does not hide or return

Diagnosis:

```bash
gnome-extensions info input-lock-cursor@aag-projects-team
cat ~/.config/input-lock/cursor-settings.json
journalctl --user -b --no-pager | grep -F input-lock-cursor
```

Expected: the extension is enabled, the JSON contains an enabled boolean and a timeout from 1 through 86399 seconds, and moving the pointer or changing a pointer button restores the cursor immediately.

Repair:

```bash
gnome-extensions enable input-lock-cursor@aag-projects-team
sudo ./update.sh
```

Rollback always restores the pointer:

```bash
gnome-extensions disable input-lock-cursor@aag-projects-team
```

## Permission denied on `/dev/input`

Diagnosis:

```bash
id input-lockd
ls -l /dev/input/event*
systemctl show input-lock.service -p SupplementaryGroups -p DevicePolicy -p DeviceAllow
```

Expected: `input-lockd` includes group `input`; event nodes normally belong to `root:input`; unit allows `char-input rw`.

Repair:

```bash
sudo usermod -a -G input input-lockd
sudo systemctl restart input-lock.service
```

If the journal proves that this systemd version does not recognize `char-input`, create a unit override only after keeping SSH open:

```bash
sudo systemctl edit input-lock.service
```

Enter:

```ini
[Service]
DevicePolicy=auto
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart input-lock.service
```

Rollback:

```bash
sudo systemctl revert input-lock.service
sudo systemctl daemon-reload
sudo systemctl restart input-lock.service
```

## Daemon/service fails to start

Diagnosis:

```bash
systemctl status input-lock.service --no-pager
journalctl -u input-lock.service -b --no-pager -n 200
python3 -m py_compile /usr/lib/input-lock/*.py
```

Expected: an invalid configuration is named explicitly and no input is grabbed.

Repair:

```bash
sudoedit /etc/input-lock/input-lock.conf
sudo systemctl restart input-lock.service
input-lock doctor
```

Rollback: restore the dated copy under `/var/backups/input-lock/` or rerun the package's `update.sh`.

## GNOME binding is not created or collides

Diagnosis:

```bash
python3 /usr/lib/input-lock/input_lock_gnome.py check
gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings
```

Expected: `check` exits 0. On collision it prints the exact existing path and binding.

Repair: change or remove the conflicting shortcut in GNOME Settings, then run `install`. The helper never overwrites a foreign binding.

Rollback: run the helper's `remove` action; it preserves all foreign paths.

## New device is detected but remains usable while locked

Diagnosis:

```bash
input-lock list-devices
input-lock logs -n 100
```

Expected: journal identifies either `excluded=...`, a pressed button, permission error or `EVIOCGRAB` failure. The safe policy is to leave that new device usable.

Repair: release its buttons, verify exclusions, then unlock/relock. Do not broaden permissions to `chmod 666 /dev/input/event*`.

Rollback: restore the previous exclusion line and reload; reload itself unlocks first.

## Service does not work after Resume

Diagnosis:

```bash
input-lock status
journalctl -u input-lock.service -b --since '-10 min' --no-pager
```

Expected: a `system-suspend` or `system-sleep-hook` unlock, followed by device rediscovery. State remains unlocked by design.

Repair:

```bash
sudo systemctl restart input-lock.service
```

Rollback: no persistent change. Do not configure automatic re-lock on Resume; that would weaken recovery safety.

## Ctrl, Alt, Shift, mouse button, or drag appears stuck

First recovery:

```bash
sudo input-lock emergency-unlock
sudo systemctl restart input-lock.service
```

Expected: normal code waits for release and rejects a direct lock while a target key/button is down. A stuck state suggests an event overflow, external remapper, or compositor issue.

Repair: disconnect/reconnect the affected external device or log out after input is released. Inspect for other grabbers:

```bash
sudo fuser -v /dev/input/eventX
```

Rollback: stop Input Lock and verify the symptom without it:

```bash
sudo systemctl stop input-lock.service
```

## Cannot switch to TTY

While locked: press and fully release `Ctrl+Alt+F3`; this first unlocks. Press it a second time to switch. Diagnose:

```bash
grep '^UNLOCK_ON_VT_HOTKEY=' /etc/input-lock/input-lock.conf
```

Expected: `yes`. Repair it with `sudoedit`, then reload. Rollback by setting `no`, but doing so removes this recovery path.

## SSH is inaccessible

Input Lock cannot filter SSH. Diagnose the independent service/network:

```bash
systemctl status ssh --no-pager
ss -ltn | grep ':22 '
```

Expected: ssh active and listening. Repair with the normal OpenSSH configuration. No Input Lock rollback is relevant; stopping Input Lock can confirm this:

```bash
sudo systemctl stop input-lock.service
```

## Neither unlock chord is recognized

Use SSH, then:

```bash
sudo input-lock emergency-unlock
sudo systemctl stop input-lock.service
```

Expected: stopping closes every daemon fd and the kernel releases every grab. Keep the service stopped and collect:

```bash
journalctl -u input-lock.service -b --no-pager -n 300
sudo evtest
```

Do not restart or relock until the relevant keyboard node is present in `input-lock list-devices`. Rollback of the entire installation is `sudo ./uninstall.sh` from the package directory.

## Tray icon is missing

Diagnosis:

```bash
systemctl --user status input-lock-notifier.service --no-pager
journalctl --user -u input-lock-notifier.service -b --no-pager -n 100
gnome-extensions info ubuntu-appindicators@ubuntu.com
```

Expected: the user service is active, Ayatana AppIndicator is installed, and Ubuntu AppIndicators is enabled. Repair:

```bash
sudo apt install gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
gnome-extensions enable ubuntu-appindicators@ubuntu.com
systemctl --user restart input-lock-notifier.service
```

Rollback: `systemctl --user disable --now input-lock-notifier.service`. The core keyboard unlock chords remain available without the tray.

## Lid-close option is unavailable or does not change state

Diagnosis:

```bash
input-lock status
input-lock list-devices
input-lock logs -n 100
```

Expected: at least one node named `Lid Switch` with class `lid-switch`. If none exists, the menu item stays disabled and the daemon safely refuses `input-lock lid-ignore on`. Do not substitute an arbitrary power-button or tablet-mode node.

When enabled, status must report an active lid inhibitor, a connected controller and a supervised safety state with fresh telemetry. `input-lock doctor` checks the installed AAG adapter and dependencies. There is no tray policy-repair writer. If monitoring is unavailable, reopen the lid and inspect the journals. Return to normal OS behavior with:

```bash
input-lock lid-ignore off
```

If IPC is unavailable, stopping the daemon closes the descriptor and releases the lid switch:

```bash
sudo systemctl stop input-lock.service
```
