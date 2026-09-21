"""Windows regression logic with no native hooks or actual power changes."""
import ctypes
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock
from ctypes import wintypes

from locklock_core import UserSettings
from locklock_windows.state import AgentController
from locklock_windows.input_hooks import HookDecisionState, configure_kernel32, WindowsInputHooks
from locklock_windows.ipc import Deadline, read_message, write_message
from locklock_windows.dispatch import UiQueue, PowerWorker
from locklock_windows.power import PowerPolicyManager, PowerPolicyLease, PowerPolicyError
from test_windows_state import FakeBackend
from test_windows_power import FakePowerApi


class ControllerRegressionTests(unittest.TestCase):
    def controller(self, **kwargs):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return AgentController(FakeBackend(), UserSettings(default_locked_kinds=("keyboard",), idle_lock_enabled=True, idle_lock_seconds=60), Path(directory.name)/'settings.json', **kwargs)

    def test_callback_runs_outside_lock_including_nested_idle_action(self):
        acquired = []
        controller = self.controller(clock=lambda:100)
        controller.session_changed(True)
        def changed(state):
            done = threading.Event()
            def read():
                controller.status()
                done.set()
            thread = threading.Thread(target=read)
            thread.start()
            acquired.append(done.wait(.5))
            thread.join(.5)
        controller.state_changed = changed
        controller.policy.last_activity = 0
        controller.tick()
        self.assertEqual(acquired, [True])

    def test_inactive_session_never_idle_relocks(self):
        controller = self.controller(clock=lambda:100)
        controller.policy.last_activity = 0
        controller.tick()
        self.assertFalse(controller.backend.locked_kinds)
        controller.session_changed(True)
        controller.lock(frozenset({'keyboard'}))
        controller.session_changed(False)
        self.assertFalse(controller.backend.locked_kinds)
        controller.policy.last_activity = 0
        controller.tick()
        self.assertFalse(controller.backend.locked_kinds)
        with self.assertRaises(RuntimeError):
            controller.lock(frozenset({'keyboard'}))

    def test_emergency_chord_ignores_unrelated_held_key(self):
        state = HookDecisionState('CTRL+ALT+Z', 'CTRL+ALT+SHIFT+F12')
        state.lock(frozenset({'keyboard'}))
        for vk in (65, 0xA2, 0xA4, 0xA0, 0x7B):
            state.keyboard_event(vk, 0x100)
        actions = [state.keyboard_event(vk, 0x101)[1] for vk in (0x7B, 0xA0, 0xA4, 0xA2)]
        self.assertEqual(actions[-1], 'emergency')
        self.assertIn(65, state._pressed_keys)

    def test_native_pointer_return_declarations(self):
        kernel = Mock()
        configure_kernel32(kernel)
        self.assertIs(kernel.GetModuleHandleW.restype, wintypes.HMODULE)
        self.assertIs(kernel.CreateMutexW.restype, wintypes.HANDLE)
        self.assertEqual(ctypes.sizeof(kernel.GetModuleHandleW.restype), ctypes.sizeof(ctypes.c_void_p))

    def test_cursor_capability_is_honest_and_cannot_be_enabled(self):
        self.assertEqual(WindowsInputHooks.capabilities.cursor_hiding.value, 'unsupported')
        with self.assertRaises(ValueError):
            self.controller().set_settings(UserSettings(hide_cursor_enabled=True))

    def test_ui_queue_only_invokes_on_draining_thread(self):
        queue = UiQueue()
        called = []
        thread = threading.Thread(target=lambda:queue.post(lambda:called.append(threading.get_ident())))
        thread.start(); thread.join()
        self.assertEqual(called, [])
        queue.drain()
        self.assertEqual(called, [threading.get_ident()])

    def test_power_worker_coalesces_and_serializes_late_disable(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        class Client:
            def sync(self, settings, **kwargs):
                calls.append(settings.ignore_lid_close)
                if settings.ignore_lid_close:
                    entered.set(); release.wait(2)
            def restore_and_stop(self):
                calls.append('restore')
        worker = PowerWorker(Client())
        worker.submit(UserSettings(ignore_lid_close=True), True)
        self.assertTrue(entered.wait(1))
        worker.submit(UserSettings(ignore_lid_close=True), False)
        release.set()
        # close waits only briefly; worker must still process cleanup after the
        # in-flight apply and cannot execute a queued apply after final restore.
        worker.close()
        worker.thread.join(1)
        self.assertFalse(worker.thread.is_alive())
        self.assertEqual(calls[-1], 'restore')


class PipeBudgetTests(unittest.TestCase):
    def budget(self):
        now = [0.]
        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.side_effect = lambda seconds: now.__setitem__(0, now[0] + seconds)
        return Deadline(.1, stop, clock=lambda:now[0])

    def test_silent_client_read_times_out(self):
        error = OSError('no data'); error.winerror = 232
        api = Mock(); api.ReadFile.side_effect = error
        with self.assertRaises(TimeoutError):
            read_message(None, self.budget(), api)

    def test_nonreading_client_write_times_out(self):
        api = Mock(); api.WriteFile.return_value = (0, 0)
        with self.assertRaises(TimeoutError):
            write_message(None, {'ok':True}, self.budget(), api)
        api.FlushFileBuffers.assert_not_called()

    def test_stop_interrupts_io(self):
        stop = threading.Event(); stop.set()
        api = Mock()
        with self.assertRaises(InterruptedError):
            read_message(None, Deadline(10, stop), api)
        api.ReadFile.assert_not_called()

    def test_fragmented_message_and_size_limit(self):
        api = Mock(); api.ReadFile.side_effect = [(0,b'{"ok":'), (0,b'true}\n')]
        self.assertEqual(read_message(None, self.budget(), api), {'ok':True})
        api.ReadFile.side_effect = None
        api.ReadFile.return_value = (234, b'x')
        with self.assertRaises(ValueError):
            read_message(None, self.budget(), api)


class SchemeRegressionTests(unittest.TestCase):
    def test_plan_change_restores_without_reactivating_original_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            api = FakePowerApi()
            manager = PowerPolicyManager(api, Path(directory)/'journal.json')
            lease = PowerPolicyLease(manager)
            lease.apply(45)
            api.active_scheme = lambda:'other-plan'
            self.assertTrue(lease.tick())
            self.assertEqual(api.values, (1,2))
            self.assertFalse(manager.pending_restore)
            self.assertTrue(manager.rearm_required)
            with self.assertRaises(PowerPolicyError):
                lease.apply(45)

    def test_unverified_restore_keeps_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            api = FakePowerApi()
            manager = PowerPolicyManager(api, Path(directory)/'journal.json')
            manager.apply_do_nothing()
            api.write_lid_values = Mock()  # API returns success without change.
            with self.assertRaises(PowerPolicyError):
                manager.restore()
            self.assertTrue(manager.pending_restore)

class PartialPowerFailureTests(unittest.TestCase):
    def test_first_failed_apply_with_failed_rollback_is_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            api = FakePowerApi()
            api.fail_writes = 2
            manager = PowerPolicyManager(api, Path(directory)/'journal.json')
            lease = PowerPolicyLease(manager, clock=lambda:100.)
            with self.assertRaises(RuntimeError):
                lease.apply(45)
            self.assertTrue(manager.pending_restore)
            self.assertEqual(lease.deadline, 100.)
            self.assertTrue(lease.tick())
            self.assertFalse(manager.pending_restore)

    def test_rejected_renewal_does_not_clear_plan_change_rearm_latch(self):
        with tempfile.TemporaryDirectory() as directory:
            api = FakePowerApi()
            manager = PowerPolicyManager(api, Path(directory)/'journal.json')
            lease = PowerPolicyLease(manager)
            lease.apply(45)
            api.active_scheme = lambda:'other-plan'
            with self.assertRaises(PowerPolicyError):
                lease.apply(45)
            self.assertIsNone(lease.deadline)
            lease.tick()
            self.assertTrue(manager.rearm_required)
