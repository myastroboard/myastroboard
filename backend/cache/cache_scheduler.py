import threading
import os
import sys
from datetime import datetime
from utils.logging_config import get_logger
from cache.cache_updater import fully_initialize_caches
from utils.constants import DATA_DIR_CACHE, CACHE_SCHEDULER_INTERVAL_SECONDS

# Windows-compatible file locking
if sys.platform == "win32":
    import msvcrt
else:  # pragma: no cover
    import fcntl

# Initialize logger for this module
logger = get_logger(__name__)


class CacheScheduler:
    def __init__(self, interval_seconds=CACHE_SCHEDULER_INTERVAL_SECONDS):
        """
        Scheduler to pre-compute heavy caches in the background.
        interval_seconds: frequency of calculations (default 300s = 5 min; TTL gating prevents unnecessary work)
        """
        self.interval = interval_seconds
        self._stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self._first_run = True
        self._lock_file = None
        self._has_lock = False
        # Signalled after the first successful cache update so that dependent
        # schedulers (e.g. SkyTonightScheduler) can wait before their first run.
        self.cache_ready_event = threading.Event()

    def start(self):
        """Start the cache scheduler if it can acquire the lock"""
        if self._acquire_lock():
            self.thread.start()
            logger.info("CacheScheduler started - will update caches immediately then every %d seconds", self.interval)
            return True
        else:
            logger.debug("Cache scheduler is already running in another process")
            return False

    def _acquire_lock(self):
        """Acquire lock file to prevent multiple instances"""
        try:
            lock_file_path = os.path.join(DATA_DIR_CACHE, 'cache_scheduler.lock')
            self._lock_file = open(lock_file_path, 'w')

            if sys.platform == "win32":
                # Windows file locking
                try:
                    msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    self._lock_file.close()
                    self._lock_file = None
                    return False
            else:  # pragma: no cover
                # Unix file locking
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            self._lock_file.write(str(os.getpid()))
            self._lock_file.flush()
            self._has_lock = True
            return True
        except (IOError, OSError):
            if self._lock_file:
                self._lock_file.close()
                self._lock_file = None
            return False

    def _release_lock(self):
        """Release the lock file"""
        if self._lock_file and self._has_lock:
            try:
                if sys.platform == "win32":
                    # Windows file unlocking — seek to 0 to match where the lock was acquired
                    self._lock_file.seek(0)
                    msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:  # pragma: no cover
                    # Unix file unlocking
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)

                self._lock_file.close()
                lock_file_path = os.path.join(DATA_DIR_CACHE, 'cache_scheduler.lock')
                if os.path.exists(lock_file_path):
                    os.unlink(lock_file_path)
            except Exception as e:
                try:
                    logger.error(f"Error releasing cache scheduler lock: {e}")
                except (ValueError, OSError):
                    pass  # Log stream already closed during process shutdown
            finally:
                self._lock_file = None
                self._has_lock = False

    def stop(self):
        """Stop the cache scheduler and release lock"""
        self._stop_event.set()
        if self.thread.is_alive():
            self.thread.join()
        self._release_lock()
        logger.info("CacheScheduler stopped")

    def _run(self):
        while not self._stop_event.is_set():
            try:
                if self._first_run:
                    logger.info("Running initial cache population...")
                    self._first_run = False
                else:
                    logger.debug("Running scheduled cache update...")
                self.update_all_caches()
                if not self.cache_ready_event.is_set():
                    self.cache_ready_event.set()
                    logger.info('Initial cache update complete - cache_ready_event set.')
            except Exception as e:
                logger.error(f"Error updating caches: {e}", exc_info=True)

            if self._stop_event.wait(self.interval):
                break  # Exit if stop event is set during sleep

    def update_all_caches(self):
        """Update all caches by calling the calculation functions"""
        start_time = datetime.now()
        logger.debug("Starting cache update process...")
        try:
            fully_initialize_caches()
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"Cache update completed successfully in {duration:.2f} seconds")
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"Cache update failed after {duration:.2f} seconds: {e}", exc_info=True)
            raise
