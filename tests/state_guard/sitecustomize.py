"""Inherit the pytest state-write guard in Python fixture subprocesses."""
import json
import os

from state_write_guard import install_write_guard

if os.environ.get('HIPPOCAMPUS_TEST_PROTECTED_STATE'):
    install_write_guard(json.loads(os.environ['HIPPOCAMPUS_TEST_PROTECTED_STATE']))
