"""Exercise run.sh's interruption cleanup: SIGTERM its process group mid-load
(as a harness or Ctrl-C would), then report what is left behind.

    python3 cleanup_test.py      # needs docker and the running stack; ~20 s; writes nothing it keeps

Prints one line: PASS|FAIL run.sh.cleanup-on-SIGTERM — <detail>.
"""

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results" / "cleanup-test"


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True)


p = subprocess.Popen(
    [str(HERE / "run.sh"), "cleanup-test"],
    start_new_session=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
t0 = time.time()
while (
    time.time() - t0 < 180
    and not docker("ps", "-q", "--filter", "name=spike-footprint-load-").stdout.strip()
):
    time.sleep(1)
time.sleep(5)
os.killpg(p.pid, signal.SIGTERM)
t1 = time.time()
try:
    rc = p.wait(timeout=240)
except subprocess.TimeoutExpired:
    print("FAIL run.sh.cleanup-on-SIGTERM — run.sh still running 240 s after SIGTERM")
    raise SystemExit(0)
waited = time.time() - t1
left = docker(
    "ps", "-a", "--filter", "name=spike-footprint-", "--format", "{{.Names}}"
).stdout.split()
pylib = (
    docker(
        "exec", "eoapi-spike-lab-1", "ls", "-d", "/tmp/spike-footprint-pylib"
    ).returncode
    == 0
)
size = (RES / "samples.csv").stat().st_size
time.sleep(6)
sampling = (RES / "samples.csv").stat().st_size != size
shutil.rmtree(RES)
ok = not left and not pylib and not sampling and waited < 30
print(
    f"{'PASS' if ok else 'FAIL'} run.sh.cleanup-on-SIGTERM — exit {rc} {waited:.0f} s after SIGTERM; "
    f"containers left: {left or 'none'}; Lab pip dir left: {pylib}; sampler still writing: {sampling}"
)
