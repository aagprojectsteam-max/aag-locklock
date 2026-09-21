import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const DEFAULT_TIMEOUT_SECONDS = 60;
const MAX_TIMEOUT_SECONDS = 86399;
const POINTER_POLL_INTERVAL_MS = 100;
const POINTER_BUTTON_MASK =
    Clutter.ModifierType.BUTTON1_MASK |
    Clutter.ModifierType.BUTTON2_MASK |
    Clutter.ModifierType.BUTTON3_MASK |
    Clutter.ModifierType.BUTTON4_MASK |
    Clutter.ModifierType.BUTTON5_MASK;

export default class InputLockCursorHider extends Extension {
    enable() {
        this._cursorTracker = global.backend.get_cursor_tracker();
        this._pollSource = 0;
        this._reloadSource = 0;
        this._cursorHidden = false;
        this._timeoutSeconds = DEFAULT_TIMEOUT_SECONDS;
        this._lastPointer = null;
        this._leaseChecked = 0;
        this._leaseValid = false;
        this._runtimeState = Gio.File.new_for_path(
            "/run/input-lock/state.json");
        this._lastPointerActivity = GLib.get_monotonic_time();

        this._settingsDirectory = Gio.File.new_for_path(
            `${GLib.get_user_config_dir()}/input-lock`);
        this._settingsFile = this._settingsDirectory.get_child('cursor-settings.json');
        GLib.mkdir_with_parents(this._settingsDirectory.get_path(), 0o700);
        this._settingsMonitor = this._settingsDirectory.monitor_directory(
            Gio.FileMonitorFlags.NONE, null);
        this._settingsChangedId = this._settingsMonitor.connect(
            'changed', (_monitor, file) => {
                if (file?.get_basename() === 'cursor-settings.json')
                    this._queueReload();
            });
        this._reloadSettings();
    }

    disable() {
        this._stopPolling();
        if (this._reloadSource)
            GLib.Source.remove(this._reloadSource);
        this._reloadSource = 0;
        this._showCursor();
        if (this._settingsMonitor && this._settingsChangedId)
            this._settingsMonitor.disconnect(this._settingsChangedId);
        this._settingsMonitor?.cancel();
        this._settingsChangedId = 0;
        this._settingsMonitor = null;
        this._settingsFile = null;
        this._settingsDirectory = null;
        this._cursorTracker = null;
    }

    _readSettings() {
        try {
            const [ok, contents] = this._settingsFile.load_contents(null);
            if (!ok)
                throw new Error('settings file could not be read');
            const parsed = JSON.parse(new TextDecoder().decode(contents));
            const enabled = parsed.enabled === true;
            const seconds = Number.isInteger(parsed.seconds)
                ? Math.min(MAX_TIMEOUT_SECONDS, Math.max(1, parsed.seconds))
                : DEFAULT_TIMEOUT_SECONDS;
            return {enabled, seconds};
        } catch (_error) {
            return {enabled: false, seconds: DEFAULT_TIMEOUT_SECONDS};
        }
    }

    _reloadSettings() {
        const settings = this._readSettings();
        this._stopPolling();
        this._showCursor();
        if (!settings.enabled)
            return;
        this._timeoutSeconds = settings.seconds;
        this._lastPointer = global.get_pointer();
        this._lastPointerActivity = GLib.get_monotonic_time();
        this._pollSource = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT,
            POINTER_POLL_INTERVAL_MS,
            () => this._pollPointer());
    }

    _queueReload() {
        if (this._reloadSource)
            return;
        this._reloadSource = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._reloadSource = 0;
            if (this._cursorTracker)
                this._reloadSettings();
            return GLib.SOURCE_REMOVE;
        });
    }

    _pollPointer() {
        // Restore visibility after daemon/tray loss; no persistent hidden
        // cursor survives an expired runtime observation.
        const now = GLib.get_monotonic_time();
        if (now - this._leaseChecked >= 1_000_000) {
            this._leaseChecked = now;
            this._leaseValid = false;
            try {
                const [ok, contents] = this._runtimeState.load_contents(null);
                const state = ok ? JSON.parse(new TextDecoder().decode(contents)) : {};
                const age = Date.now() / 1000 - state.timestamp;
                this._leaseValid = state.lid_controller_connected === true &&
                    state.authorized_session_active === true && age >= 0 && age <= 5;
            } catch (_error) {
                this._leaseValid = false;
            }
        }
        if (!this._leaseValid) {
            this._showCursor();
            this._lastPointerActivity = now;
            return GLib.SOURCE_CONTINUE;
        }
        const pointer = global.get_pointer();
        const previous = this._lastPointer;
        const changed = !previous ||
            pointer[0] !== previous[0] ||
            pointer[1] !== previous[1] ||
            (pointer[2] & POINTER_BUTTON_MASK) !==
                (previous[2] & POINTER_BUTTON_MASK);
        if (changed) {
            this._lastPointer = pointer;
            this._lastPointerActivity = GLib.get_monotonic_time();
            this._showCursor();
        } else if (!this._cursorHidden) {
            const elapsedSeconds =
                (GLib.get_monotonic_time() - this._lastPointerActivity) / 1_000_000;
            if (elapsedSeconds >= this._timeoutSeconds)
                this._hideCursor();
        }
        return GLib.SOURCE_CONTINUE;
    }

    _stopPolling() {
        if (this._pollSource)
            GLib.Source.remove(this._pollSource);
        this._pollSource = 0;
        this._lastPointer = null;
    }

    _hideCursor() {
        if (!this._cursorHidden) {
            this._cursorTracker.inhibit_cursor_visibility();
            this._cursorHidden = true;
        }
    }

    _showCursor() {
        if (this._cursorHidden) {
            this._cursorTracker?.uninhibit_cursor_visibility();
            this._cursorHidden = false;
        }
    }
}
