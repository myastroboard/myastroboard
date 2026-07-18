"""
System metrics collection module.
Provides container/VM-aware metrics with detailed disk space tracking and process monitoring.
"""

import os
import threading
import time
from typing import TypedDict
import psutil
import platform
from datetime import datetime
from utils.logging_config import get_logger
from utils.constants import (
    DATA_DIR,
    SKYTONIGHT_DIR,
    SKYTONIGHT_CATALOGUES_DIR,
    SKYTONIGHT_CALCULATIONS_DIR,
    SKYTONIGHT_LOGS_DIR,
    SKYTONIGHT_RUNTIME_DIR,
    SKYTONIGHT_OUTPUT_DIR,
)

logger = get_logger(__name__)


class _MetricsCache(TypedDict):
    data: dict | None
    ts: float


_metrics_cache_lock = threading.Lock()
_metrics_cache: _MetricsCache = {'data': None, 'ts': 0.0}
_METRICS_CACHE_TTL = 30.0  # 30s balances near-real-time metrics visibility with lower collection overhead.

CONTAINER_PROCESS_HINTS = {
    'dockerd',
    'docker',
    'docker-proxy',
    'containerd',
    'containerd-shim',
    'runc',
    'buildkitd',
    'podman',
}


def is_running_in_container():
    """
    Detect if running in Docker/LXC container or virtual machine.
    Returns tuple: (is_container, container_type)
    """
    # Check for Docker
    if os.path.exists('/.dockerenv'):
        return True, 'Docker'

    if os.path.exists('/run/.containerenv'):
        return True, 'Podman'

    # Check cgroup for container detection
    try:
        with open('/proc/1/cgroup', 'r') as f:
            cgroup = f.read()
            if 'docker' in cgroup:
                return True, 'Docker'
            if 'lxc' in cgroup:
                return True, 'LXC'
            if 'kubepods' in cgroup:
                return True, 'Kubernetes'
            if 'systemd-nspawn' in cgroup:
                return True, 'systemd-nspawn'
    except (FileNotFoundError, IOError):
        pass  # /proc/1/cgroup not present (non-Linux or restricted environment)

    # Check for hypervisor (VM detection)
    try:
        with open('/proc/cpuinfo', 'r') as f:
            cpuinfo = f.read()
            if 'hypervisor' in cpuinfo:
                return True, 'Virtual Machine'
    except (FileNotFoundError, IOError):
        pass  # /proc/cpuinfo not present (non-Linux or restricted environment)

    return False, None


def get_folder_disk_usage(folder_path):
    """
    Calculate total disk usage for a folder and its subfolders.
    Returns size in bytes or None if folder doesn't exist.
    """
    if not os.path.exists(folder_path):
        return None

    total_size = 0
    stack = [folder_path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            total_size += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                    except (OSError, IOError):
                        pass  # skip inaccessible files (permissions, broken symlinks)
        except (OSError, IOError):
            pass  # skip inaccessible directories (permissions, deleted mid-scan)
    return total_size


def _compute_disk_space_details():
    """
    Get detailed disk space information for important folders.
    Returns dict with folder paths, sizes, and percentages of root filesystem.
    """
    try:
        # Get root filesystem info
        root_disk = psutil.disk_usage('/')

        folders = {
            'data': DATA_DIR,
            'data/cache': os.path.join(DATA_DIR, 'cache'),
            'data/astrodex': os.path.join(DATA_DIR, 'astrodex'),
            'data/equipments': os.path.join(DATA_DIR, 'equipments'),
            'data/projects': os.path.join(DATA_DIR, 'projects'),
            'data/skytonight': SKYTONIGHT_DIR,
            'data/skytonight/calculations': SKYTONIGHT_CALCULATIONS_DIR,
            'data/skytonight/catalogues': SKYTONIGHT_CATALOGUES_DIR,
            'data/skytonight/logs': SKYTONIGHT_LOGS_DIR,
            'data/skytonight/outputs': SKYTONIGHT_OUTPUT_DIR,
            'data/skytonight/runtime': SKYTONIGHT_RUNTIME_DIR,
        }

        folder_usage = {}
        total_tracked = 0

        for folder_name, folder_path in folders.items():
            size = get_folder_disk_usage(folder_path)
            if size is not None:
                folder_usage[folder_name] = {
                    'bytes': size,
                    'percent_of_root': round((size / root_disk.total * 100), 2) if root_disk.total > 0 else 0,
                }
                total_tracked += size
            else:
                folder_usage[folder_name] = {'bytes': 0, 'percent_of_root': 0}

        return {
            'root': {
                'total': root_disk.total,
                'used': root_disk.used,
                'free': root_disk.free,
                'percent': root_disk.percent,
            },
            'folders': folder_usage,
            'total_tracked': total_tracked,
        }
    except Exception as e:
        logger.error(f"Error getting disk space details: {e}")
        return {'root': {'total': 0, 'used': 0, 'free': 0, 'percent': 0}, 'folders': {}, 'total_tracked': 0}


_disk_details_cache_lock = threading.Lock()
_disk_details_cache: _MetricsCache = {'data': None, 'ts': 0.0}
_disk_details_refreshing = False
# Recursively sizing every tracked folder is the slow part of /api/metrics -
# on a Docker-Desktop-on-Windows bind mount, walking many-small-file
# directories (skyfield ephemeris, cached images) can take several seconds
# to tens of seconds, far more than CPU/memory collection. Disk usage also
# doesn't need per-30s freshness, so it gets its own longer-lived cache.
_DISK_DETAILS_CACHE_TTL = 300.0


def get_disk_space_details():
    """
    Disk space details, served from a background-refreshed cache so a slow
    recursive scan never blocks the /api/metrics request. Returns the last
    computed value immediately and kicks off a background refresh once it
    goes stale - except on the very first call, which has no cached value to
    fall back on and must compute synchronously once.
    """
    global _disk_details_refreshing

    with _disk_details_cache_lock:
        cached = _disk_details_cache['data']
        is_stale = (time.monotonic() - _disk_details_cache['ts']) >= _DISK_DETAILS_CACHE_TTL
        start_refresh = cached is not None and is_stale and not _disk_details_refreshing
        if start_refresh:
            _disk_details_refreshing = True

    if cached is None:
        result = _compute_disk_space_details()
        with _disk_details_cache_lock:
            _disk_details_cache['data'] = result
            _disk_details_cache['ts'] = time.monotonic()
        return result

    if start_refresh:
        threading.Thread(target=_refresh_disk_details_cache, daemon=True).start()

    return cached


def _refresh_disk_details_cache():
    global _disk_details_refreshing
    try:
        result = _compute_disk_space_details()
        with _disk_details_cache_lock:
            _disk_details_cache['data'] = result
            _disk_details_cache['ts'] = time.monotonic()
    finally:
        with _disk_details_cache_lock:
            _disk_details_refreshing = False


def get_environment_processes():
    """
    Collect all visible processes with useful details for diagnostics.
    Returns a list sorted by CPU usage, then memory usage.
    """
    processes = []
    now_ts = datetime.now().timestamp()
    cpu_count = psutil.cpu_count(logical=True) or 1

    for proc in psutil.process_iter(
        ['pid', 'name', 'status', 'create_time', 'memory_info', 'memory_percent', 'cpu_times']
    ):
        try:
            info = proc.info
            pid = info.get('pid')
            name = info.get('name') or 'unknown'
            status = info.get('status') or 'unknown'
            created_at = info.get('create_time')
            uptime_seconds = max(0, now_ts - created_at) if created_at else 0

            cpu_times = info.get('cpu_times')
            cpu_total = 0.0
            if cpu_times:
                cpu_total = float(getattr(cpu_times, 'user', 0.0)) + float(getattr(cpu_times, 'system', 0.0))
            cpu_percent = 0.0
            if uptime_seconds > 0:
                cpu_percent = min(100.0, max(0.0, (cpu_total / uptime_seconds) * (100.0 / cpu_count)))

            mem_info = info.get('memory_info')
            memory_rss = int(getattr(mem_info, 'rss', 0) or 0)
            memory_percent = float(info.get('memory_percent') or 0.0)

            lower_name = name.lower()
            is_container_related = any(hint in lower_name for hint in CONTAINER_PROCESS_HINTS)

            processes.append(
                {
                    'pid': pid,
                    'name': name,
                    'status': status,
                    'cpu_percent': round(cpu_percent, 2),
                    'memory_rss': memory_rss,
                    'memory_percent': round(memory_percent, 2),
                    'uptime_seconds': int(uptime_seconds),
                    'created_at': datetime.fromtimestamp(created_at).isoformat() if created_at else None,
                    'is_container_related': is_container_related,
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception as e:
            logger.debug(f"Unable to read process info for PID {getattr(proc, 'pid', 'unknown')}: {e}")

    processes.sort(key=lambda p: (p['cpu_percent'], p['memory_rss']), reverse=True)
    return processes


def detect_docker_in_docker(processes):
    """
    Best-effort Docker-in-Docker detection using process and socket hints.
    """
    indicators = []
    if os.path.exists('/var/run/docker.sock'):
        indicators.append('docker_socket')

    if os.environ.get('DOCKER_HOST'):
        indicators.append('docker_host_env')

    container_related = [p for p in processes if p.get('is_container_related')]
    if container_related:
        indicators.append('container_runtime_processes')

    enabled = len(indicators) > 0
    return {
        'enabled': enabled,
        'indicators': indicators,
        'container_related_count': len(container_related),
    }


def collect_metrics():
    """
    Collect all system metrics with container/VM detection.
    Returns comprehensive metrics dictionary. Result is cached for 30 seconds
    so rapid or concurrent calls (e.g. from the auto-refresh poll) are cheap.
    """
    now = time.monotonic()
    with _metrics_cache_lock:
        if _metrics_cache['data'] is not None and now - _metrics_cache['ts'] < _METRICS_CACHE_TTL:
            return _metrics_cache['data']
    try:
        # Detect environment
        is_container, container_type = is_running_in_container()

        # CPU Information
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_count_physical = psutil.cpu_count(logical=False)
        cpu_freq = psutil.cpu_freq()

        # Memory Information
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # Disk Information
        disk = psutil.disk_usage('/')

        # Process Information
        process_count = len(psutil.pids())
        processes = get_environment_processes()
        dind = detect_docker_in_docker(processes)

        # Main process info
        boot_time = psutil.boot_time()
        uptime_seconds = datetime.now().timestamp() - boot_time

        # Network stats
        net_io = psutil.net_io_counters()

        # Platform info
        platform_info = {
            'system': platform.system(),
            'release': platform.release(),
            'version': platform.version(),
            'machine': platform.machine(),
            'processor': platform.processor(),
            'python_version': platform.python_version(),
        }

        # Disk space details
        disk_details = get_disk_space_details()

        result = {
            'environment': {'is_container': is_container, 'container_type': container_type},
            'cpu': {
                'percent': cpu_percent,
                'count_logical': cpu_count_logical,
                'count_physical': cpu_count_physical,
                'frequency': (
                    {
                        'current': cpu_freq.current if cpu_freq else None,
                        'min': cpu_freq.min if cpu_freq else None,
                        'max': cpu_freq.max if cpu_freq else None,
                    }
                    if cpu_freq
                    else None
                ),
            },
            'memory': {
                'total': memory.total,
                'available': memory.available,
                'used': memory.used,
                'percent': memory.percent,
                'free': memory.free,
            },
            'swap': {'total': swap.total, 'used': swap.used, 'free': swap.free, 'percent': swap.percent},
            'disk': {
                'root': {'total': disk.total, 'used': disk.used, 'free': disk.free, 'percent': disk.percent},
                'details': disk_details,
            },
            'process': {
                'system_count': process_count,
                'visible_count': len(processes),
                'docker_in_docker': dind,
                'processes': processes,
            },
            'uptime': {'seconds': uptime_seconds, 'boot_time': boot_time},
            'network': {
                'bytes_sent': net_io.bytes_sent,
                'bytes_recv': net_io.bytes_recv,
                'packets_sent': net_io.packets_sent,
                'packets_recv': net_io.packets_recv,
            },
            'platform': platform_info,
        }
        with _metrics_cache_lock:
            _metrics_cache['data'] = result
            _metrics_cache['ts'] = time.monotonic()
        return result
    except Exception as e:
        logger.error(f"Error collecting metrics: {e}", exc_info=True)
        return {'error': str(e), 'timestamp': datetime.now().isoformat()}
