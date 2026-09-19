"""Exercise Blender's restricted addon loader in an isolated fresh process."""
from pathlib import Path
import subprocess
import unittest

import bpy


class AddonRegistrationTests(unittest.TestCase):
    def test_normal_enable_disable_and_deferred_initialization(self):
        probe = Path(__file__).with_name('_addon_registration_probe.py')
        command = [bpy.app.binary_path, '--factory-startup', '-b', '--python-exit-code', '1',
                   '--python', str(probe)]
        result = subprocess.run(command, cwd=str(probe.parents[2]), capture_output=True,
                                text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('REGISTRATION_PROBE_OK', result.stdout)
