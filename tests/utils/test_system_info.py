"""Tests for the startup host summary (utils/system_info.py)."""

import pytest

from utils import system_info


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='ascii')


class TestCgroupMemoryLimit:
    def test_cgroup_v2_limit_is_read(self, tmp_path):
        """A cgroup v2 memory.max in bytes is the limit."""
        _write(tmp_path / 'memory.max', '536870912\n')
        assert system_info.cgroup_memory_limit_bytes(str(tmp_path)) == 536870912

    def test_cgroup_v2_max_means_no_limit(self, tmp_path):
        """'max' in memory.max means the container has no memory limit."""
        _write(tmp_path / 'memory.max', 'max\n')
        assert system_info.cgroup_memory_limit_bytes(str(tmp_path)) is None

    def test_cgroup_v1_limit_is_read(self, tmp_path):
        """Without cgroup v2 files, the v1 memory.limit_in_bytes is used."""
        _write(tmp_path / 'memory' / 'memory.limit_in_bytes', '1073741824')
        assert system_info.cgroup_memory_limit_bytes(str(tmp_path)) == 1073741824

    def test_cgroup_v1_huge_value_means_no_limit(self, tmp_path):
        """cgroup v1 reports an unlimited container as a near-int64-max value."""
        _write(tmp_path / 'memory' / 'memory.limit_in_bytes', '9223372036854771712')
        assert system_info.cgroup_memory_limit_bytes(str(tmp_path)) is None

    def test_no_cgroup_files(self, tmp_path):
        """Outside a cgroup (Windows, macOS) there is no limit to report."""
        assert system_info.cgroup_memory_limit_bytes(str(tmp_path)) is None

    def test_garbage_value_is_ignored(self, tmp_path):
        """An unparsable value is treated as unknown, not as a crash."""
        _write(tmp_path / 'memory.max', 'not-a-number')
        assert system_info.cgroup_memory_limit_bytes(str(tmp_path)) is None


class TestCgroupCpuLimit:
    def test_cgroup_v2_quota(self, tmp_path):
        """'25000 100000' in cpu.max is a quarter of a CPU."""
        _write(tmp_path / 'cpu.max', '25000 100000')
        assert system_info.cgroup_cpu_limit(str(tmp_path)) == 0.25

    def test_cgroup_v2_unlimited(self, tmp_path):
        """'max 100000' means no CPU quota."""
        _write(tmp_path / 'cpu.max', 'max 100000')
        assert system_info.cgroup_cpu_limit(str(tmp_path)) is None

    def test_cgroup_v1_quota(self, tmp_path):
        """cgroup v1 quota and period give the number of CPUs."""
        _write(tmp_path / 'cpu' / 'cpu.cfs_quota_us', '200000')
        _write(tmp_path / 'cpu' / 'cpu.cfs_period_us', '100000')
        assert system_info.cgroup_cpu_limit(str(tmp_path)) == 2.0

    def test_cgroup_v1_negative_quota_means_unlimited(self, tmp_path):
        """cgroup v1 writes -1 when there is no quota."""
        _write(tmp_path / 'cpu' / 'cpu.cfs_quota_us', '-1')
        _write(tmp_path / 'cpu' / 'cpu.cfs_period_us', '100000')
        assert system_info.cgroup_cpu_limit(str(tmp_path)) is None

    def test_no_cgroup_files(self, tmp_path):
        """No cgroup files: no CPU limit to report."""
        assert system_info.cgroup_cpu_limit(str(tmp_path)) is None


class TestFileSystemType:
    def test_deepest_mount_point_wins(self, tmp_path):
        """The data directory's own mount is reported, not the root file system."""
        mounts = tmp_path / 'mounts'
        _write(mounts, 'overlay / overlay rw 0 0\nserver:/share /app/data nfs4 rw 0 0\n')
        assert system_info.file_system_type('/app/data/cache', str(mounts)) == 'nfs4'

    def test_sibling_with_same_prefix_is_not_a_match(self, tmp_path):
        """/app/database is not inside a mount on /app/data."""
        mounts = tmp_path / 'mounts'
        _write(mounts, 'overlay / overlay rw 0 0\nserver:/share /app/data nfs4 rw 0 0\n')
        assert system_info.file_system_type('/app/database', str(mounts)) == 'overlay'

    def test_unreadable_mounts_file(self, tmp_path):
        """Without /proc/mounts the type is unknown."""
        assert system_info.file_system_type('/app/data', str(tmp_path / 'missing')) is None


class TestGunicornWorkerCount:
    def test_short_flag(self):
        """`gunicorn -w 2 app` reports 2 workers."""
        assert system_info.gunicorn_worker_count(['/usr/local/bin/gunicorn', '-w', '2', 'app']) == '2'

    def test_long_flag_with_equals(self):
        """`--workers=3` is read too."""
        assert system_info.gunicorn_worker_count(['gunicorn', '--workers=3', 'app']) == '3'

    def test_default_comes_from_web_concurrency(self, monkeypatch):
        """Without a flag gunicorn uses WEB_CONCURRENCY, else 1."""
        monkeypatch.setenv('WEB_CONCURRENCY', '4')
        assert system_info.gunicorn_worker_count(['gunicorn', 'app']) == '4'
        monkeypatch.delenv('WEB_CONCURRENCY')
        assert system_info.gunicorn_worker_count(['gunicorn', 'app']) == '1'

    def test_not_under_gunicorn(self):
        """The Flask development server has no gunicorn workers."""
        assert system_info.gunicorn_worker_count(['python', 'backend/app.py']) is None


def _summary(**overrides):
    summary = {
        'python': '3.15.2',
        'machine': 'aarch64',
        'os': 'Linux 6.1',
        'container': 'Docker',
        'cpus': 4,
        'cpu_limit': None,
        'memory_total': 4096 * 1024 * 1024,
        'memory_limit': None,
        'swap_total': 0,
        'workers': '2',
        'data_fs': 'ext4',
        'data_free': 10240 * 1024 * 1024,
    }
    summary.update(overrides)
    return summary


class TestFormatHostSummary:
    def test_line_lists_the_resources(self):
        """The line names version, architecture, CPUs, memory, workers and data file system."""
        line = system_info.format_host_summary(_summary(), '1.8.2')
        assert line.startswith('Host: MyAstroBoard 1.8.2')
        for fragment in ('aarch64', 'container: Docker', '4 CPUs', '4096 MB RAM', 'gunicorn workers: 2', 'ext4'):
            assert fragment in line

    def test_container_limits_are_shown(self):
        """CPU and memory limits appear next to the host figures."""
        line = system_info.format_host_summary(_summary(cpu_limit=0.5, memory_limit=512 * 1024 * 1024), '1.8.2')
        assert '(limited to 0.5)' in line
        assert '(limited to 512 MB)' in line

    def test_unknown_values_do_not_crash(self):
        """Missing figures are written as unknown."""
        line = system_info.format_host_summary(
            _summary(memory_total=None, swap_total=None, data_fs=None, data_free=None, workers=None), '1.8.2'
        )
        assert 'RAM unknown' in line and 'unknown fs' in line and 'gunicorn workers: n/a' in line


class TestEffectiveMemory:
    @pytest.mark.parametrize(
        ('limit', 'total', 'expected'),
        [(None, 4096, 4096), (512, 4096, 512), (8192, 4096, 4096), (512, None, 512), (None, None, None)],
    )
    def test_lowest_known_value(self, limit, total, expected):
        """The container limit counts only when lower than the host RAM."""
        assert system_info.effective_memory_bytes({'memory_limit': limit, 'memory_total': total}) == expected


class TestLogHostSummary:
    def test_low_memory_is_warned(self, monkeypatch):
        """A 512 MB limit produces a warning; the data file system type alone does not."""
        monkeypatch.setattr(
            system_info,
            'collect_host_summary',
            lambda data_dir: _summary(memory_limit=512 * 1024 * 1024, data_fs='nfs4'),
        )
        infos, warnings = [], []
        monkeypatch.setattr(system_info.logger, 'info', infos.append)
        monkeypatch.setattr(system_info.logger, 'warning', warnings.append)

        system_info.log_host_summary('/app/data', '1.8.2')

        assert len(infos) == 1 and infos[0].startswith('Host: ')
        assert any('512 MB of memory' in w for w in warnings)
        assert len(warnings) == 1

    def test_comfortable_host_logs_no_warning(self, monkeypatch):
        """Enough memory on a local disk: one INFO line, no warning."""
        monkeypatch.setattr(system_info, 'collect_host_summary', lambda data_dir: _summary())
        warnings = []
        monkeypatch.setattr(system_info.logger, 'warning', warnings.append)

        system_info.log_host_summary('/app/data', '1.8.2')

        assert warnings == []

    def test_collection_failure_never_stops_startup(self, monkeypatch):
        """An error while collecting is logged as a warning, not raised."""

        def broken(data_dir):
            raise RuntimeError('no /proc')

        monkeypatch.setattr(system_info, 'collect_host_summary', broken)
        warnings = []
        monkeypatch.setattr(system_info.logger, 'warning', warnings.append)

        system_info.log_host_summary('/app/data', '1.8.2')

        assert warnings == ['Could not collect the host summary: no /proc']

    def test_collection_combines_psutil_and_cgroup_figures(self, tmp_path, monkeypatch):
        """collect_host_summary reports psutil's RAM / swap / free disk next to the cgroup limits."""
        from types import SimpleNamespace

        psutil = system_info.psutil
        monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(total=2048), raising=False)
        monkeypatch.setattr(psutil, 'swap_memory', lambda: SimpleNamespace(total=0), raising=False)
        monkeypatch.setattr(psutil, 'disk_usage', lambda path: SimpleNamespace(free=99), raising=False)
        monkeypatch.setattr(system_info, 'cgroup_memory_limit_bytes', lambda: 1024)
        monkeypatch.setattr(system_info, 'cgroup_cpu_limit', lambda: 0.5)
        from utils import metrics_collector

        monkeypatch.setattr(metrics_collector, 'is_running_in_container', lambda: (True, 'Docker'))

        summary = system_info.collect_host_summary(str(tmp_path))

        assert summary['memory_total'] == 2048 and summary['memory_limit'] == 1024
        assert summary['swap_total'] == 0 and summary['data_free'] == 99
        assert summary['cpu_limit'] == 0.5 and summary['container'] == 'Docker'
        assert summary['cpus']


class TestResourceStatus:
    """The block /api/metrics returns for the low-memory banner in Parameters -> Metrics."""

    def test_container_limit_below_recommendation_is_low(self, monkeypatch):
        """A 512 MB container on a 16 GB host is low on memory: the limit is what counts."""
        monkeypatch.setattr(system_info, 'cgroup_memory_limit_bytes', lambda: 512 * 1024 * 1024)
        monkeypatch.setattr(system_info, 'cgroup_cpu_limit', lambda: 0.5)

        status = system_info.resource_status(16 * 1024 * 1024 * 1024)

        assert status['low_memory'] is True
        assert status['effective_memory'] == 512 * 1024 * 1024
        assert status['recommended_memory'] == system_info.RECOMMENDED_MEMORY_MB * 1024 * 1024
        assert status['cpu_limit'] == 0.5

    def test_enough_memory_is_not_low(self, monkeypatch):
        """Without a container limit, 4 GB of host RAM is enough."""
        monkeypatch.setattr(system_info, 'cgroup_memory_limit_bytes', lambda: None)
        monkeypatch.setattr(system_info, 'cgroup_cpu_limit', lambda: None)

        status = system_info.resource_status(4 * 1024 * 1024 * 1024)

        assert status['low_memory'] is False
        assert status['memory_limit'] is None and status['cpu_limit'] is None

    def test_small_host_without_limit_is_low(self, monkeypatch):
        """A 512 MB board without any container limit is low too."""
        monkeypatch.setattr(system_info, 'cgroup_memory_limit_bytes', lambda: None)
        monkeypatch.setattr(system_info, 'cgroup_cpu_limit', lambda: None)

        assert system_info.resource_status(512 * 1024 * 1024)['low_memory'] is True

    def test_unknown_memory_is_not_flagged(self, monkeypatch):
        """No figure at all: no banner rather than a false alarm."""
        monkeypatch.setattr(system_info, 'cgroup_memory_limit_bytes', lambda: None)
        monkeypatch.setattr(system_info, 'cgroup_cpu_limit', lambda: None)

        assert system_info.resource_status(None)['low_memory'] is False
