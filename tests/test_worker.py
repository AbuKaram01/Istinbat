# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

import threading

from istinbat.services import Worker


def immediate(callback):
    callback()


def make_worker():
    return Worker(immediate)


def test_results_are_delivered_through_dispatch():
    worker, received = make_worker(), []
    worker.submit(lambda task: 41 + 1, on_done=received.append)
    assert worker.wait_idle(2) and received == [42]
    worker.shutdown()


def test_jobs_run_one_at_a_time_in_submission_order():
    worker, order, gate = make_worker(), [], threading.Event()

    def slow(task):
        gate.wait(2)
        order.append("first")

    worker.submit(slow)
    worker.submit(lambda task: order.append("second"))
    assert worker.is_busy
    gate.set()
    assert worker.wait_idle(2) and order == ["first", "second"] and not worker.is_busy
    worker.shutdown()


def test_errors_are_forwarded_and_do_not_stop_the_worker():
    worker, errors, results = make_worker(), [], []

    def failing(task):
        raise ValueError("boom")

    worker.submit(failing, on_error=errors.append)
    worker.submit(lambda task: "still alive", on_done=results.append)
    assert worker.wait_idle(2)
    assert [str(error) for error in errors] == ["boom"] and results == ["still alive"]
    worker.shutdown()


def test_a_task_cancelled_before_it_starts_is_skipped():
    worker, ran, skipped, gate = make_worker(), [], [], threading.Event()
    worker.submit(lambda task: gate.wait(2))
    task = worker.submit(lambda task: ran.append(True), on_skipped=lambda: skipped.append(True))
    task.cancel()
    gate.set()
    assert worker.wait_idle(2) and ran == [] and skipped == [True]
    worker.shutdown()


def test_a_running_job_can_observe_cancellation():
    worker, seen = make_worker(), []
    started, cancelled = threading.Event(), threading.Event()

    def job(task):
        started.set()
        cancelled.wait(2)
        seen.append(task.is_cancelled())

    task = worker.submit(job)
    assert started.wait(2)
    task.cancel()
    cancelled.set()
    assert worker.wait_idle(2) and seen == [True]
    worker.shutdown()


def test_post_dispatches_a_callback_with_arguments():
    worker, calls = make_worker(), []
    worker.post(lambda a, b: calls.append((a, b)), 1, "x")
    assert calls == [(1, "x")]
    worker.shutdown()


def test_shutdown_stops_the_thread():
    worker = make_worker()
    worker.shutdown()
    assert not worker._thread.is_alive()
