"""Offline checks for bounded recovery after successful strip release."""
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from libraries.audio import arby_audio_recovery as recovery


class RecoveryTests(unittest.TestCase):
    def test_recovery_runs_after_release(self):
        order = []
        strip = Mock()
        strip.close.side_effect = lambda: order.append('release')
        with patch.object(recovery, 'recover_headphones',
                          side_effect=lambda: order.append('recover')):
            recovery.close_strip_and_recover_audio(strip, recover=True)
        self.assertEqual(order, ['release', 'recover'])

    def test_disabled_and_failed_release_never_open_audio(self):
        strip = Mock()
        with patch.object(recovery, 'recover_headphones') as recover:
            recovery.close_strip_and_recover_audio(strip)
            recover.assert_not_called()
            strip.close.side_effect = RuntimeError('release failed')
            with self.assertRaises(RuntimeError):
                recovery.close_strip_and_recover_audio(strip, recover=True)
            recover.assert_not_called()

    @patch.object(recovery.shutil, 'which', return_value='/usr/bin/aplay')
    def test_silent_playback_is_finite_and_targets_only_headphones(self, _):
        with patch.object(recovery.subprocess, 'run',
                          return_value=SimpleNamespace(returncode=0)) as run:
            with patch('builtins.print'):
                self.assertTrue(recovery.recover_headphones())
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('-D') + 1], recovery.HEADPHONES_DEVICE)
        self.assertEqual(run.call_args.kwargs['input'], bytes(48000))
        self.assertEqual(run.call_args.kwargs['timeout'], 3)

    def test_missing_player_does_not_start_process(self):
        with patch.object(recovery.shutil, 'which', return_value=None):
            with patch.object(recovery.subprocess, 'run') as run:
                self.assertFalse(recovery.recover_headphones())
                run.assert_not_called()

    @patch.object(recovery.shutil, 'which', return_value='/usr/bin/aplay')
    def test_timeout_and_device_error_do_not_break_shutdown(self, _):
        with patch.object(recovery.subprocess, 'run',
                          side_effect=subprocess.TimeoutExpired('aplay', 3)):
            self.assertFalse(recovery.recover_headphones())
        with patch.object(recovery.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stderr=b'Device busy')):
            self.assertFalse(recovery.recover_headphones())


if __name__ == '__main__':
    unittest.main()
