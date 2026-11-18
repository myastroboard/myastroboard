"""Tests for gunicorn.conf.py, the server settings baked into the Docker image."""

import os
import runpy
import sys

import pytest

CONF_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'gunicorn.conf.py')
GIB = 1024**3


@pytest.fixture
def conf(monkeypatch):
    # The file exports its choice to the environment: let monkeypatch put it back afterwards.
    for name in ('WEB_CONCURRENCY', 'MAB_GUNICORN_WORKERS', 'MAB_GUNICORN_THREADS'):
        monkeypatch.delenv(name, raising=False)
    return runpy.run_path(CONF_PATH)


def test_threaded_workers(conf):
    """Workers serve requests from threads, and tell the application what was chosen."""
    assert conf['worker_class'] == 'gthread'
    assert conf['threads'] >= 4
    assert conf['workers'] in (1, 2)
    assert os.environ['MAB_GUNICORN_WORKERS'] == str(conf['workers'])
    assert os.environ['MAB_GUNICORN_THREADS'] == str(conf['threads'])


class TestChooseWorkers:
    def test_small_host_runs_one_process(self, conf):
        """One CPU, or less than 4 GB: a second copy of everything is not worth its memory."""
        choose = conf['choose_workers']
        assert choose(environ={}, cpus=1.0, memory=8 * GIB) == 1
        assert choose(environ={}, cpus=0.25, memory=512 * 1024**2) == 1
        assert choose(environ={}, cpus=4.0, memory=2 * GIB) == 1

    def test_host_with_room_runs_two(self, conf):
        """Two CPUs and 4 GB: a second process keeps pages fast while SkyTonight calculates."""
        assert conf['choose_workers'](environ={}, cpus=2.0, memory=4 * GIB) == 2

    def test_unknown_memory_stays_on_one(self, conf):
        assert conf['choose_workers'](environ={}, cpus=8.0, memory=None) == 1

    def test_web_concurrency_wins(self, conf):
        """WEB_CONCURRENCY sets the count either way; an invalid value is ignored."""
        choose = conf['choose_workers']
        assert choose(environ={'WEB_CONCURRENCY': '2'}, cpus=0.5, memory=GIB) == 2
        assert choose(environ={'WEB_CONCURRENCY': '1'}, cpus=8.0, memory=16 * GIB) == 1
        assert choose(environ={'WEB_CONCURRENCY': 'lots'}, cpus=1.0, memory=GIB) == 1
        assert choose(environ={'WEB_CONCURRENCY': '0'}, cpus=1.0, memory=GIB) == 1


class TestResourceDetection:
    def test_cpu_quota_from_cgroup(self, conf, tmp_path):
        (tmp_path / 'cpu.max').write_text('25000 100000\n')
        assert conf['available_cpus'](str(tmp_path)) == pytest.approx(0.25)

    def test_no_cpu_quota_falls_back_to_the_cpu_count(self, conf, tmp_path):
        (tmp_path / 'cpu.max').write_text('max 100000\n')
        assert conf['available_cpus'](str(tmp_path)) == float(os.cpu_count() or 1)
        assert conf['available_cpus'](str(tmp_path / 'missing')) == float(os.cpu_count() or 1)

    def test_memory_limit_from_cgroup(self, conf, tmp_path):
        (tmp_path / 'memory.max').write_text(f'{GIB}\n')
        assert conf['available_memory_bytes'](str(tmp_path), str(tmp_path / 'none')) == GIB

    def test_no_memory_limit_falls_back_to_the_host_total(self, conf, tmp_path):
        (tmp_path / 'memory.max').write_text('max\n')
        meminfo = tmp_path / 'meminfo'
        meminfo.write_text('MemTotal:        4096000 kB\nMemFree:  1 kB\n')
        assert conf['available_memory_bytes'](str(tmp_path), str(meminfo)) == 4096000 * 1024
        assert conf['available_memory_bytes'](str(tmp_path / 'x'), str(tmp_path / 'y')) is None


def test_worker_init_shortens_the_gil_switch_interval(conf):
    """Each worker hands the GIL over faster than Python's 5 ms default, so request threads
    are not held up for long behind the background calculations."""
    previous = sys.getswitchinterval()
    try:
        conf['post_worker_init'](object())
        assert sys.getswitchinterval() == pytest.approx(conf['GIL_SWITCH_INTERVAL_S'])
        assert conf['GIL_SWITCH_INTERVAL_S'] < 0.005
    finally:
        sys.setswitchinterval(previous)


def test_binds_port_5000(conf):
    assert all(address.endswith(':5000') for address in conf['bind'])
