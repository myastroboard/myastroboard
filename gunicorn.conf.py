"""Gunicorn settings for the Docker image.

Gunicorn loads ./gunicorn.conf.py from its working directory (/app) automatically;
options given in GUNICORN_CMD_ARGS or on the command line still win.

Workers and threads (see docs/1.INSTALLATION.md, "Workers and threads"): each worker process
imports Astropy, NumPy and the catalogues (about 215 MB). On a small host one process with
request threads serves a household well; with CPUs and memory to spare, a second process keeps
pages fast for a group browsing while SkyTonight calculates. The count is chosen from the
resources the container sees; WEB_CONCURRENCY=1 or 2 sets it explicitly.
"""

import os
import sys

# A second worker process needs both: another CPU to run on while the first one calculates,
# and memory for a second copy of everything (the host's total when the container has no
# limit, which other services share - hence the margin).
SECOND_WORKER_MIN_CPUS = 2.0
SECOND_WORKER_MIN_MEMORY_BYTES = 4 * 1024**3


def _read(path):
    try:
        with open(path, encoding="ascii") as fh:
            return fh.read().strip()
    except OSError:
        return None


# Listen on IPv6 as well as IPv4: Home Assistant's "Open web UI" link uses the name the
# browser reached Home Assistant with, and homeassistant.local often resolves to an
# IPv6 address. "[::]" also accepts IPv4 unless the kernel is set to IPv6-only sockets
# (bindv6only=1), in which case both addresses are bound. With IPv6 disabled in the
# kernel, binding "[::]" would fail, so fall back to IPv4 only.
def choose_bind(if_inet6="/proc/net/if_inet6", bindv6only="/proc/sys/net/ipv6/bindv6only"):
    """The addresses to listen on, from the kernel's IPv6 support and settings."""
    if not os.path.exists(if_inet6):
        return ["0.0.0.0:5000"]
    if _read(bindv6only) == "1":
        return ["0.0.0.0:5000", "[::]:5000"]
    return ["[::]:5000"]


bind = choose_bind()


def available_cpus(cgroup_root="/sys/fs/cgroup"):
    """CPUs this container may use: its CFS quota (cgroup v2 cpu.max), else the CPU count."""
    value = _read(os.path.join(cgroup_root, "cpu.max"))
    if value:
        parts = value.split()
        if len(parts) == 2 and parts[0] != "max":
            try:
                return int(parts[0]) / int(parts[1])
            except ValueError, ZeroDivisionError:
                pass
    return float(os.cpu_count() or 1)


def available_memory_bytes(cgroup_root="/sys/fs/cgroup", meminfo="/proc/meminfo"):
    """Memory this container may use: its cgroup v2 limit, else the host's total (None if unknown)."""
    value = _read(os.path.join(cgroup_root, "memory.max"))
    if value and value.isdigit():
        return int(value)
    for line in (_read(meminfo) or "").splitlines():
        if line.startswith("MemTotal:"):
            fields = line.split()
            if len(fields) >= 2 and fields[1].isdigit():
                return int(fields[1]) * 1024
    return None


def choose_workers(environ=None, cpus=None, memory=None):
    """WEB_CONCURRENCY when set (1 or more), else 2 on a host with room for it, else 1."""
    environ = os.environ if environ is None else environ
    explicit = str(environ.get("WEB_CONCURRENCY") or "").strip()
    if explicit.isdigit() and int(explicit) >= 1:
        return int(explicit)
    cpus = available_cpus() if cpus is None else cpus
    memory = available_memory_bytes() if memory is None else memory
    if cpus >= SECOND_WORKER_MIN_CPUS and memory is not None and memory >= SECOND_WORKER_MIN_MEMORY_BYTES:
        return 2
    return 1


workers = choose_workers()

# Concurrent requests per worker. A browser opens about six connections per page; the threads
# share one interpreter, so more of them adds queueing, not throughput - but a request waiting
# on a slow upstream service (survey images) holds a thread, and eight leave room for that.
worker_class = "gthread"
threads = 8

# Told to the application, which logs them in its "Host:" line at startup.
os.environ["MAB_GUNICORN_WORKERS"] = str(workers)
os.environ["MAB_GUNICORN_THREADS"] = str(threads)

# The background calculations (SkyTonight, cache jobs) run as threads of the same process and
# hold the GIL in long stretches. A request thread that gives the GIL up for I/O has to wait up
# to this interval to get it back, once per I/O call; Python's default is 5 ms. Measured on
# 1 CPU during a SkyTonight run: a page took 1.7 s at 5 ms, 0.95 s at 1 ms and 0.79 s at
# 0.5 ms (two sync workers: 0.75 s), for a calculation about 10 % longer.
GIL_SWITCH_INTERVAL_S = 0.0005


def post_worker_init(worker):
    sys.setswitchinterval(GIL_SWITCH_INTERVAL_S)
