"""Keep tests away from the box's own shared files when they run on a working box.

The update test run (nmb/common/updater.py) runs the whole suite on the box while it measures every minute:
a test that runs a full measurement cycle got "another measurement was running" from the box's real
scheduler holding /run/nmb/speedtest.lock, and an update was refused for it (2026-11-10).
Imported by the test modules that run a cycle; the first import picks a private lock for the whole run.
"""
import os
import tempfile

from nmb.speed import runner

if runner.MEASURE_LOCK.startswith("/run/"):
    runner.MEASURE_LOCK = os.path.join(tempfile.mkdtemp(prefix="nmb-test-lock-"), "speedtest.lock")
