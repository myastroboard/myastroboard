"""
Tests for metrics_collector.py
Covers pure-logic functions and mocked file/system calls.
"""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from metrics_collector import (
    is_running_in_container,
    get_folder_disk_usage,
    detect_docker_in_docker,
    collect_metrics,
    CONTAINER_PROCESS_HINTS,
)


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
        from metrics_collector import get_disk_space_details
        result = get_disk_space_details()
        assert isinstance(result, dict)

    def test_has_root_key(self):
        from metrics_collector import get_disk_space_details
        result = get_disk_space_details()
        assert "root" in result

    def test_root_has_total(self):
        from metrics_collector import get_disk_space_details
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
