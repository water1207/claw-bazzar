"""Tests for thread-safe oracle logs."""
import threading

from app.services.oracle import _oracle_logs, _oracle_logs_lock, MAX_LOGS


def test_oracle_logs_lock_exists():
    """Verify _oracle_logs_lock is a threading.Lock instance."""
    assert isinstance(_oracle_logs_lock, type(threading.Lock()))


def test_concurrent_log_writes_no_corruption():
    """10 threads each append 50 entries; verify no data loss or corruption."""
    # Save original state
    original_logs = _oracle_logs[:]
    _oracle_logs.clear()

    num_threads = 10
    entries_per_thread = 50
    errors: list[Exception] = []

    def writer(thread_id: int):
        try:
            for i in range(entries_per_thread):
                with _oracle_logs_lock:
                    _oracle_logs.append({"thread": thread_id, "index": i})
                    if len(_oracle_logs) > MAX_LOGS:
                        _oracle_logs[:] = _oracle_logs[-MAX_LOGS:]
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors during concurrent writes: {errors}"

    total_expected = num_threads * entries_per_thread
    # All entries fit within MAX_LOGS (200), total is 500, so capped
    expected_len = min(total_expected, MAX_LOGS)
    assert len(_oracle_logs) == expected_len

    # Every entry must be a valid dict with thread and index keys
    for entry in _oracle_logs:
        assert isinstance(entry, dict)
        assert "thread" in entry
        assert "index" in entry

    # Restore original state
    _oracle_logs.clear()
    _oracle_logs.extend(original_logs)
