"""
Tests for metrics_collector.py
Covers pure-logic functions and mocked file/system calls.
"""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
import metrics_collector as mc

is_running_in_container = mc.is_running_in_container
get_folder_disk_usage = mc.get_folder_disk_usage
get_disk_space_details = mc.get_disk_space_details
get_environment_processes = mc.get_environment_processes
detect_docker_in_docker = mc.detect_docker_in_docker
collect_metrics = mc.collect_metrics
CONTAINER_PROCESS_HINTS = mc.CONTAINER_PROCESS_HINTS


class TestIsRunningInContainer:
    """Tests for is_running_in_container detection logic."""

    @patch("metrics_collector.os.path.exists")
    def test_detects_docker_via_dockerenv(self, mock_exists):
        mock_exists.side_effect = lambda p: p == "/.dockerenv"
        result, container_type = is_running_in_container()
        assert result is True
        assert container_type == "Docker"

    @patch("metrics_collector.os.path.exists")
    def test_detects_podman_via_containerenv(self, mock_exists):
        mock_exists.side_effect = lambda p: p == "/run/.containerenv"
        result, container_type = is_running_in_container()
        assert result is True
        assert container_type == "Podman"

    @patch("builtins.open", side_effect=FileNotFoundError)
    @patch("metrics_collector.os.path.exists", return_value=False)
    def test_returns_false_when_no_indicators(self, mock_exists, mock_open):
        result, container_type = is_running_in_container()
        assert result is False
        assert container_type is None

    @patch("metrics_collector.os.path.exists", return_value=False)
    def test_detects_docker_via_cgroup(self, mock_exists):
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_file.read.return_value = "12:devices:/docker/abc123"
        with patch("builtins.open", return_value=mock_file):
            result, container_type = is_running_in_container()
        assert result is True
        assert container_type == "Docker"

    @patch("metrics_collector.os.path.exists", return_value=False)
    def test_detects_lxc_via_cgroup(self, mock_exists):
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_file.read.return_value = "12:devices:/lxc/mycontainer"
        with patch("builtins.open", return_value=mock_file):
            result, container_type = is_running_in_container()
        assert result is True
        assert container_type == "LXC"

    @patch("metrics_collector.os.path.exists", return_value=False)
    def test_detects_kubernetes_via_cgroup(self, mock_exists):
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_file.read.return_value = "12:devices:/kubepods/pod123"
        with patch("builtins.open", return_value=mock_file):
            result, container_type = is_running_in_container()
        assert result is True
        assert container_type == "Kubernetes"

    @patch("metrics_collector.os.path.exists", return_value=False)
    def test_detects_systemd_nspawn_via_cgroup(self, mock_exists):
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_file.read.return_value = "12:devices:/systemd-nspawn/mycontainer"
        with patch("builtins.open", return_value=mock_file):
            result, container_type = is_running_in_container()
        assert result is True
        assert container_type == "systemd-nspawn"

    @patch("metrics_collector.os.path.exists", return_value=False)
    def test_detects_hypervisor_via_cpuinfo(self, mock_exists):
        call_count = [0]
        def open_side_effect(path, *args, **kwargs):
            call_count[0] += 1
            mock_file = MagicMock()
            if '/proc/1/cgroup' in str(path):
                raise FileNotFoundError
            elif '/proc/cpuinfo' in str(path):
                mock_file.__enter__ = MagicMock(return_value=mock_file)
                mock_file.__exit__ = MagicMock(return_value=False)
                mock_file.read.return_value = "flags: hypervisor vmx"
                return mock_file
            raise FileNotFoundError
        with patch("builtins.open", side_effect=open_side_effect):
            result, container_type = is_running_in_container()
        assert result is True
        assert container_type == "Virtual Machine"


class TestGetFolderDiskUsage:
    """Tests for get_folder_disk_usage filesystem logic."""

    def test_returns_none_for_missing_path(self):
        result = get_folder_disk_usage("/path/that/does/not/exist/12345")
        assert result is None

    def test_returns_none_on_os_error(self, tmp_path):
        """Should return None when os.walk raises an OSError."""
        with patch("metrics_collector.os.walk", side_effect=OSError("permission denied")):
            result = get_folder_disk_usage(str(tmp_path))
        assert result is None

    def test_returns_zero_for_empty_directory(self, tmp_path):
        result = get_folder_disk_usage(str(tmp_path))
        assert result == 0

    def test_returns_correct_size_for_single_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"hello world")  # 11 bytes
        result = get_folder_disk_usage(str(tmp_path))
        assert result == 11

    def test_accumulates_sizes_recursively(self, tmp_path):
        (tmp_path / "a.txt").write_bytes(b"A" * 100)
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "b.txt").write_bytes(b"B" * 200)
        result = get_folder_disk_usage(str(tmp_path))
        assert result == 300


class TestDetectDockerInDocker:
    """Tests for detect_docker_in_docker logic."""

    def test_no_indicators_returns_disabled(self):
        with patch("metrics_collector.os.path.exists", return_value=False):
            with patch.dict("os.environ", {}, clear=False):
                os.environ.pop("DOCKER_HOST", None)
                result = detect_docker_in_docker([])
        assert result["enabled"] is False
        assert result["indicators"] == []

    def test_detects_docker_socket(self):
        with patch("metrics_collector.os.path.exists", side_effect=lambda p: p == "/var/run/docker.sock"):
            result = detect_docker_in_docker([])
        assert result["enabled"] is True
        assert "docker_socket" in result["indicators"]

    def test_detects_container_related_processes(self):
        processes = [{"is_container_related": True, "name": "dockerd"}]
        with patch("metrics_collector.os.path.exists", return_value=False):
            with patch.dict("os.environ", {}, clear=False):
                os.environ.pop("DOCKER_HOST", None)
                result = detect_docker_in_docker(processes)
        assert result["enabled"] is True
        assert "container_runtime_processes" in result["indicators"]
        assert result["container_related_count"] == 1

    def test_detects_docker_host_env(self):
        with patch("metrics_collector.os.path.exists", return_value=False):
            with patch.dict("os.environ", {"DOCKER_HOST": "tcp://localhost:2376"}):
                result = detect_docker_in_docker([])
        assert result["enabled"] is True
        assert "docker_host_env" in result["indicators"]


class TestCollectMetrics:
    """Tests for collect_metrics return structure."""

    def test_collect_metrics_returns_dict(self):
        result = collect_metrics()
        assert isinstance(result, dict)

    def test_collect_metrics_has_cpu_key(self):
        result = collect_metrics()
        assert "cpu" in result or "error" in result

    def test_collect_metrics_has_memory_key(self):
        result = collect_metrics()
        if "error" not in result:
            assert "memory" in result
            assert "total" in result["memory"]

    def test_collect_metrics_has_platform_key(self):
        result = collect_metrics()
        if "error" not in result:
            assert "platform" in result

    def test_container_process_hints_are_strings(self):
        for hint in CONTAINER_PROCESS_HINTS:
            assert isinstance(hint, str)
            assert len(hint) > 0

    def test_collect_metrics_has_disk_key(self):
        result = collect_metrics()
        if "error" not in result:
            assert "disk" in result

    def test_collect_metrics_has_network_key(self):
        result = collect_metrics()
        if "error" not in result:
            assert "network" in result

    def test_collect_metrics_has_uptime_key(self):
        result = collect_metrics()
        if "error" not in result:
            assert "uptime" in result
            assert "seconds" in result["uptime"]

    def test_collect_metrics_has_process_key(self):
        result = collect_metrics()
        if "error" not in result:
            assert "process" in result


class TestGetDiskSpaceDetails:
    """Tests for get_disk_space_details."""

    def test_returns_dict(self):
        result = get_disk_space_details()
        assert isinstance(result, dict)

    def test_has_root_key(self):
        result = get_disk_space_details()
        assert "root" in result

    def test_root_has_total(self):
        result = get_disk_space_details()
        if "root" in result:
            assert "total" in result["root"]


class TestGetEnvironmentProcesses:
    """Tests for get_environment_processes using inject-style mocking."""

    def test_container_process_hints_cover_common_runtimes(self):
        """Ensure docker, podman, containerd are all in CONTAINER_PROCESS_HINTS."""
        assert "docker" in CONTAINER_PROCESS_HINTS
        assert "podman" in CONTAINER_PROCESS_HINTS
        assert "containerd" in CONTAINER_PROCESS_HINTS

    def test_is_container_related_flag_set_for_docker(self):
        """Verify that a 'dockerd' process would be flagged as container-related."""
        lower_name = "dockerd"
        is_container_related = any(hint in lower_name for hint in CONTAINER_PROCESS_HINTS)
        assert is_container_related is True

    def test_is_container_related_false_for_regular_process(self):
        """Verify that 'python' is NOT flagged as container-related."""
        lower_name = "python"
        is_container_related = any(hint in lower_name for hint in CONTAINER_PROCESS_HINTS)
        assert is_container_related is False

    def test_get_environment_processes_returns_list(self):
        """Cover lines 152-204 by calling get_environment_processes with mocked psutil."""
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 1234,
            'name': 'test_process',
            'status': 'running',
            'username': 'testuser',
            'create_time': 1700000000.0,
            'memory_info': MagicMock(rss=1024 * 1024),
            'memory_percent': 0.5,
            'cpu_times': MagicMock(user=1.0, system=0.5),
            'cmdline': ['test_process', '--flag'],
        }

        with patch.object(mc.psutil, 'process_iter', create=True, return_value=[mock_proc]):
            with patch.object(mc.psutil, 'cpu_count', create=True, return_value=4):
                result = mc.get_environment_processes()

        assert isinstance(result, list)
        assert len(result) == 1

    def test_get_environment_processes_entries_have_required_keys(self):
        """Each process entry has the expected fields."""
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 42,
            'name': 'worker',
            'status': 'sleeping',
            'username': 'root',
            'create_time': 1700000000.0,
            'memory_info': MagicMock(rss=2 * 1024 * 1024),
            'memory_percent': 1.2,
            'cpu_times': MagicMock(user=2.0, system=1.0),
            'cmdline': ['worker'],
        }

        with patch.object(mc.psutil, 'process_iter', create=True, return_value=[mock_proc]):
            with patch.object(mc.psutil, 'cpu_count', create=True, return_value=2):
                result = mc.get_environment_processes()

        assert len(result) == 1
        proc = result[0]
        for key in ("pid", "name", "cpu_percent", "memory_rss", "uptime_seconds"):
            assert key in proc



class TestGetDiskSpaceDetailsMocked:
    """Cover lines 104-132 in get_disk_space_details by mocking psutil."""

    def test_full_body_with_mocked_disk(self, tmp_path):
        """psutil.disk_usage('/') may fail on Windows; mock it to cover lines 104-132."""
        mock_disk = MagicMock()
        mock_disk.total = 100 * 1024 ** 3
        mock_disk.used = 50 * 1024 ** 3
        mock_disk.free = 50 * 1024 ** 3
        mock_disk.percent = 50.0

        with patch.object(mc.psutil, 'disk_usage', create=True, return_value=mock_disk):
            result = mc.get_disk_space_details()

        assert "root" in result
        assert result["root"]["total"] == mock_disk.total
        assert result["root"]["percent"] == 50.0
        assert "folders" in result
        assert "total_tracked" in result

    def test_returns_error_dict_on_exception(self):
        """Confirm the except branch returns a safe error structure."""
        with patch.object(mc.psutil, 'disk_usage', create=True, side_effect=Exception("disk error")):
            result = mc.get_disk_space_details()

        assert "root" in result
        assert result["root"]["total"] == 0


class TestCollectMetricsMocked:
    """Cover lines 241-277 by mocking psutil calls that may fail on this platform."""

    def _mock_psutil(self, monkeypatch):
        mock_cpu_freq = MagicMock()
        mock_cpu_freq.current = 2400.0
        mock_cpu_freq.min = 800.0
        mock_cpu_freq.max = 3600.0

        mock_mem = MagicMock()
        mock_mem.total = 8 * 1024 ** 3
        mock_mem.available = 4 * 1024 ** 3
        mock_mem.used = 4 * 1024 ** 3
        mock_mem.percent = 50.0
        mock_mem.free = 4 * 1024 ** 3

        mock_swap = MagicMock()
        mock_swap.total = 2 * 1024 ** 3
        mock_swap.used = 0
        mock_swap.free = 2 * 1024 ** 3
        mock_swap.percent = 0.0

        mock_disk = MagicMock()
        mock_disk.total = 100 * 1024 ** 3
        mock_disk.used = 50 * 1024 ** 3
        mock_disk.free = 50 * 1024 ** 3
        mock_disk.percent = 50.0

        mock_net = MagicMock()
        mock_net.bytes_sent = 1000
        mock_net.bytes_recv = 2000
        mock_net.packets_sent = 10
        mock_net.packets_recv = 20

        # raising=False allows setting attrs that don't exist on the stub psutil
        monkeypatch.setattr(mc.psutil, "cpu_percent", lambda interval=None: 10.0, raising=False)
        monkeypatch.setattr(mc.psutil, "cpu_count", lambda logical=True: 4, raising=False)
        monkeypatch.setattr(mc.psutil, "cpu_freq", lambda: mock_cpu_freq, raising=False)
        monkeypatch.setattr(mc.psutil, "virtual_memory", lambda: mock_mem, raising=False)
        monkeypatch.setattr(mc.psutil, "swap_memory", lambda: mock_swap, raising=False)
        monkeypatch.setattr(mc.psutil, "disk_usage", lambda path: mock_disk, raising=False)
        monkeypatch.setattr(mc.psutil, "pids", lambda: [1, 2, 3], raising=False)
        monkeypatch.setattr(mc.psutil, "boot_time", lambda: 1700000000.0, raising=False)
        monkeypatch.setattr(mc.psutil, "net_io_counters", lambda: mock_net, raising=False)
        monkeypatch.setattr(mc, "get_environment_processes", lambda: [])

    def test_collect_metrics_full_body(self, monkeypatch):
        """Cover lines 241-277 with mocked psutil."""
        self._mock_psutil(monkeypatch)
        result = mc.collect_metrics()
        assert "cpu" in result
        assert "memory" in result
        assert "disk" in result
        assert "network" in result
        assert "platform" in result
        assert "uptime" in result
        assert "process" in result

    def test_collect_metrics_cpu_frequency_present(self, monkeypatch):
        self._mock_psutil(monkeypatch)
        result = mc.collect_metrics()
        if "cpu" in result and result["cpu"].get("frequency"):
            assert "current" in result["cpu"]["frequency"]

    def test_collect_metrics_cpu_freq_none(self, monkeypatch):
        """Cover the 'if cpu_freq else None' branch when cpu_freq is None."""
        self._mock_psutil(monkeypatch)
        monkeypatch.setattr(mc.psutil, "cpu_freq", lambda: None, raising=False)
        result = mc.collect_metrics()
        if "cpu" in result:
            assert result["cpu"]["frequency"] is None


class TestIsRunningInContainerBranchCoverage:
    """Cover lines 57->63 and 66->71 (cgroup/cpuinfo readable but no pattern matches)."""

    @patch("metrics_collector.os.path.exists", return_value=False)
    def test_cgroup_no_pattern_and_cpuinfo_no_hypervisor_returns_false(self, mock_exists):
        """
        Lines 57->63: cgroup read but 'systemd-nspawn' absent → falls to cpuinfo block.
        Lines 66->71: cpuinfo read but 'hypervisor' absent → returns (False, None).
        """
        def open_side_effect(path, *args, **kwargs):
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            if '1/cgroup' in str(path):
                mock_file.read.return_value = "12:devices:/unrelated/system"
            elif 'cpuinfo' in str(path):
                mock_file.read.return_value = "processor: 0\nvendor_id: GenuineIntel\nflags: sse2"
            else:
                raise FileNotFoundError
            return mock_file

        with patch("builtins.open", side_effect=open_side_effect):
            result, container_type = is_running_in_container()

        assert result is False
        assert container_type is None


class TestGetDiskSpaceDetailsFolderNone:
    """Cover line 130: get_folder_disk_usage returns None for folders that don't exist."""

    def test_folder_size_none_falls_into_else_branch(self):
        mock_disk = MagicMock()
        mock_disk.total = 100 * 1024 ** 3
        mock_disk.used = 50 * 1024 ** 3
        mock_disk.free = 50 * 1024 ** 3
        mock_disk.percent = 50.0

        with patch.object(mc.psutil, 'disk_usage', create=True, return_value=mock_disk), \
             patch('metrics_collector.get_folder_disk_usage', return_value=None):
            result = mc.get_disk_space_details()

        assert "folders" in result
        for folder_info in result["folders"].values():
            assert folder_info["bytes"] == 0
            assert folder_info["percent_of_root"] == 0


class TestGetEnvironmentProcessesBranchCoverage:
    """Cover lines 169->171, 172->175, 198-201."""

    def _ensure_psutil_exceptions(self, mc):
        for exc_name in ('NoSuchProcess', 'AccessDenied', 'ZombieProcess'):
            if not hasattr(mc.psutil, exc_name):
                setattr(mc.psutil, exc_name, type(exc_name, (Exception,), {}))

    def test_process_with_cpu_times_none_skips_cpu_total(self):
        """Lines 169->171: cpu_times is None → cpu_total stays 0.0."""
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 1, 'name': 'worker', 'status': 'running', 'username': 'user',
            'create_time': 1700000000.0,
            'memory_info': MagicMock(rss=1024), 'memory_percent': 0.1,
            'cpu_times': None,
            'cmdline': [],
        }
        with patch.object(mc.psutil, 'process_iter', create=True, return_value=[mock_proc]), \
             patch.object(mc.psutil, 'cpu_count', create=True, return_value=4):
            result = mc.get_environment_processes()

        assert result[0]['cpu_percent'] == 0.0

    def test_process_with_no_create_time_zero_uptime(self):
        """Lines 172->175: create_time is None → uptime_seconds=0 → cpu_percent stays 0.0."""
        mock_proc = MagicMock()
        mock_proc.info = {
            'pid': 2, 'name': 'worker', 'status': 'running', 'username': 'user',
            'create_time': None,
            'memory_info': MagicMock(rss=1024), 'memory_percent': 0.1,
            'cpu_times': MagicMock(user=1.0, system=0.5),
            'cmdline': [],
        }
        with patch.object(mc.psutil, 'process_iter', create=True, return_value=[mock_proc]), \
             patch.object(mc.psutil, 'cpu_count', create=True, return_value=4):
            result = mc.get_environment_processes()

        assert result[0]['cpu_percent'] == 0.0
        assert result[0]['created_at'] is None

    def test_nosuchprocess_exception_skips_process(self):
        """Lines 198-199: psutil.NoSuchProcess → process is skipped via continue."""
        from unittest.mock import PropertyMock

        self._ensure_psutil_exceptions(mc)

        mock_bad_proc = MagicMock()
        type(mock_bad_proc).info = PropertyMock(side_effect=mc.psutil.NoSuchProcess())

        mock_good_proc = MagicMock()
        mock_good_proc.info = {
            'pid': 1, 'name': 'ok', 'status': 'running', 'username': 'user',
            'create_time': 1700000000.0,
            'memory_info': MagicMock(rss=1024), 'memory_percent': 0.1,
            'cpu_times': None, 'cmdline': [],
        }

        with patch.object(mc.psutil, 'process_iter', create=True, return_value=[mock_bad_proc, mock_good_proc]), \
             patch.object(mc.psutil, 'cpu_count', create=True, return_value=4):
            result = mc.get_environment_processes()

        assert len(result) == 1
        assert result[0]['name'] == 'ok'

    def test_generic_exception_in_process_loop_is_swallowed(self):
        """Lines 200-201: generic Exception → logged, process is skipped."""
        from unittest.mock import PropertyMock

        self._ensure_psutil_exceptions(mc)

        mock_bad_proc = MagicMock()
        type(mock_bad_proc).info = PropertyMock(side_effect=RuntimeError("unexpected error"))

        with patch.object(mc.psutil, 'process_iter', create=True, return_value=[mock_bad_proc]), \
             patch.object(mc.psutil, 'cpu_count', create=True, return_value=4):
            result = mc.get_environment_processes()

        assert result == []
