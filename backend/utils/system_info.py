"""Host summary written to the log at startup, to diagnose installs that run short on resources.

A self-hosted instance runs on anything from a desktop to a 512 MB board, and an issue
report rarely says which. Each worker logs one line with what it can actually use: the
container's CPU and memory limits (cgroup), not only the host's, plus the file system
holding the data directory. Whether SQLite got its WAL mode there is logged by db/engine.py,
which tests it for real: a file system type alone gives false alarms (Docker Desktop
bind mounts show as 9p and work).

Nothing personal is logged: no host name, address, user name or coordinates.
"""

import os
import platform
import sys

import psutil

from utils.logging_config import get_logger

logger = get_logger(__name__)

# Measured on the 1.8.2 image (two gunicorn workers): about 560 MB at rest and 620 MB
# during the first SkyTonight calculation; a 512 MB limit gets a worker OOM-killed.
RECOMMENDED_MEMORY_MB = 1024

# cgroup v1 reports "no limit" as a huge number (the page-aligned max int64)
_CGROUP_V1_UNLIMITED = 1 << 60


def _read_text(path):
    """A small text file's content, stripped, or None when it cannot be read."""
    try:
        with open(path, encoding='ascii', errors='replace') as fh:
            return fh.read().strip()
    except OSError:
        return None


def cgroup_memory_limit_bytes(root='/sys/fs/cgroup'):
    """The container's memory limit in bytes, or None when it has none (or no cgroup is visible)."""
    value = _read_text(os.path.join(root, 'memory.max'))  # cgroup v2
    if value is None:
        value = _read_text(os.path.join(root, 'memory', 'memory.limit_in_bytes'))  # cgroup v1
    if not value or value == 'max':
        return None
    try:
        limit = int(value)
    except ValueError:
        return None
    return None if limit >= _CGROUP_V1_UNLIMITED else limit


def cgroup_cpu_limit(root='/sys/fs/cgroup'):
    """The container's CPU quota as a number of CPUs (0.5, 2.0...), or None when it has none."""
    value = _read_text(os.path.join(root, 'cpu.max'))  # cgroup v2: "<quota> <period>" or "max <period>"
    if value is not None:
        parts = value.split()
        if len(parts) != 2 or parts[0] == 'max':
            return None
        quota, period = parts
    else:  # cgroup v1
        quota = _read_text(os.path.join(root, 'cpu', 'cpu.cfs_quota_us'))
        period = _read_text(os.path.join(root, 'cpu', 'cpu.cfs_period_us'))
    try:
        quota_value, period_value = int(quota or ''), int(period or '')
    except ValueError:
        return None
    if quota_value <= 0 or period_value <= 0:
        return None
    return round(quota_value / period_value, 2)


def file_system_type(path, mounts_file='/proc/mounts'):
    """The type of the file system holding ``path`` ('ext4', 'nfs4'...), or None when unknown."""
    try:
        with open(mounts_file, encoding='utf-8', errors='replace') as fh:
            mounts = [line.split() for line in fh]
    except OSError:
        return None
    # Follow symlinks when the path exists (a bind-mounted data dir may be one)
    target = os.path.realpath(path) if os.path.exists(path) else path
    best_point, best_type = '', None
    for fields in mounts:
        if len(fields) < 3:
            continue
        point, fs_type = fields[1], fields[2]
        inside = target == point or target.startswith(point.rstrip('/') + '/')
        if inside and len(point) > len(best_point):
            best_point, best_type = point, fs_type
    return best_type


def gunicorn_worker_count(argv=None):
    """The ``-w`` / ``--workers`` value gunicorn was started with, or None outside gunicorn."""
    argv = sys.argv if argv is None else argv
    if not argv or 'gunicorn' not in os.path.basename(argv[0]):
        return None
    for index, arg in enumerate(argv):
        if arg in ('-w', '--workers') and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith('--workers='):
            return arg.split('=', 1)[1]
    return os.environ.get('WEB_CONCURRENCY', '1')


def _megabytes(value):
    return f'{value / (1024 * 1024):.0f} MB'


def collect_host_summary(data_dir):
    """The figures logged at startup, as a dict (None where a value is unknown)."""
    # Lazy: metrics_collector imports this module for resource_status()
    from utils.metrics_collector import is_running_in_container

    memory = psutil.virtual_memory()
    in_container, container_type = is_running_in_container()
    try:
        disk_free = psutil.disk_usage(data_dir).free
    except OSError:
        disk_free = None
    return {
        'python': platform.python_version(),
        'machine': platform.machine() or None,
        'os': f'{platform.system()} {platform.release()}',
        'container': container_type if in_container else None,
        'cpus': os.cpu_count(),
        'cpu_limit': cgroup_cpu_limit(),
        'memory_total': memory.total,
        'memory_limit': cgroup_memory_limit_bytes(),
        'swap_total': psutil.swap_memory().total,
        'workers': gunicorn_worker_count(),
        'data_fs': file_system_type(data_dir),
        'data_free': disk_free,
    }


def effective_memory_bytes(summary):
    """The memory the app can really use: the container limit when lower than the host's RAM."""
    limit = summary.get('memory_limit')
    total = summary.get('memory_total')
    if limit and total:
        return min(limit, total)
    return limit or total


def resource_status(memory_total):
    """Container limits and the low-memory flag, for Parameters -> Metrics.

    ``memory_total`` is the host RAM psutil reports; inside a container the cgroup limit
    may be far lower, and that limit is what gets a worker killed.
    """
    summary = {'memory_total': memory_total, 'memory_limit': cgroup_memory_limit_bytes()}
    effective = effective_memory_bytes(summary)
    recommended = RECOMMENDED_MEMORY_MB * 1024 * 1024
    return {
        'memory_limit': summary['memory_limit'],
        'cpu_limit': cgroup_cpu_limit(),
        'effective_memory': effective,
        'recommended_memory': recommended,
        'low_memory': bool(effective and effective < recommended),
    }


def format_host_summary(summary, version):
    """One log line describing the host."""
    cpus = f"{summary['cpus']} CPUs"
    if summary.get('cpu_limit'):
        cpus += f" (limited to {summary['cpu_limit']})"
    memory = f"{_megabytes(summary['memory_total'])} RAM" if summary.get('memory_total') else 'RAM unknown'
    if summary.get('memory_limit'):
        memory += f" (limited to {_megabytes(summary['memory_limit'])})"
    parts = [
        f"MyAstroBoard {version}",
        f"Python {summary['python']}",
        f"{summary['os']} {summary.get('machine') or ''}".strip(),
        f"container: {summary.get('container') or 'no'}",
        cpus,
        memory,
        f"host swap {_megabytes(summary['swap_total'])}" if summary.get('swap_total') is not None else 'swap unknown',
        f"gunicorn workers: {summary.get('workers') or 'n/a'}",
        f"data on {summary.get('data_fs') or 'unknown fs'}",
    ]
    if summary.get('data_free') is not None:
        parts.append(f"{_megabytes(summary['data_free'])} free")
    return 'Host: ' + ', '.join(parts)


def log_host_summary(data_dir, version):
    """Log the host summary (INFO), plus a warning for each resource known to cause trouble."""
    try:
        summary = collect_host_summary(data_dir)
        logger.info(f"{format_host_summary(summary, version)} (pid {os.getpid()})")
        memory = effective_memory_bytes(summary)
        if memory and memory < RECOMMENDED_MEMORY_MB * 1024 * 1024:
            logger.warning(
                f"Only {_megabytes(memory)} of memory available, below the recommended {RECOMMENDED_MEMORY_MB} MB: "
                "workers may be killed during calculations, which shows in the browser as failed requests "
                "or the offline page (see docs/1.INSTALLATION.md#system-requirements)"
            )
    except Exception as exc:  # Diagnostics only: never stop the startup
        logger.warning(f"Could not collect the host summary: {exc}")
