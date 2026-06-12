"""Regression tests for the singleton per-request-options race.

The proxy reuses ONE ``ContentRouter`` / ``SmartCrusher`` (and one module
level ``compress()`` pipeline) across every request. Per-request runtime
options used to be stored as plain instance attributes on those shared
singletons, so two concurrent ``compress()`` calls with different configs
clobbered each other — one call's ``target_ratio`` / ``force_kompress`` /
``kompress_model`` / ``compression_policy`` bled into another's.

The fix backs those ``_runtime_*`` fields with ``threading.local`` so each
in-flight request is isolated. These tests pin that contract:

* mechanism level — a SHARED instance, concurrent threads writing DIFFERENT
  values, each thread must read back its OWN value (not a neighbour's).
* end-to-end — concurrent ``compress()`` calls with different runtime
  options on the shared pipeline produce per-config-deterministic results
  (concurrent == serial), never a crash or cross-contaminated output.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from headroom import compress
from headroom.transforms.content_router import ContentRouter
from headroom.transforms.smart_crusher import SmartCrusher

N_THREADS = 16


def _make_messages(seed: int) -> list[dict[str, str]]:
    """A message large enough to exercise the routing/compression path."""
    body = f"item-{seed} " + ("the quick brown fox jumps over the lazy dog. " * 60)
    return [{"role": "user", "content": body}]


class TestContentRouterRuntimeOptionsIsolation:
    """A shared ContentRouter must not leak per-request options across threads."""

    def test_concurrent_writes_do_not_cross_contaminate(self) -> None:
        router = ContentRouter()  # ONE shared instance, as the pipeline uses
        barrier = threading.Barrier(N_THREADS)
        observed: dict[int, tuple[float, bool, str, object]] = {}
        lock = threading.Lock()

        def worker(i: int) -> None:
            # Each thread sets a DISTINCT set of runtime options.
            router._runtime_target_ratio = 0.1 * (i + 1)
            router._runtime_force_kompress = bool(i % 2)
            router._runtime_kompress_model = f"model-{i}"
            policy = object()
            router._runtime_compression_policy = policy

            # Release only once every thread has written — this is the
            # window where a plain-attribute implementation interleaves
            # writes and the "last writer wins" for everyone.
            barrier.wait()

            with lock:
                observed[i] = (
                    router._runtime_target_ratio,
                    router._runtime_force_kompress,
                    router._runtime_kompress_model,
                    router._runtime_compression_policy,
                )
            # Hold the policy reference so identity comparison is valid.
            assert router._runtime_compression_policy is policy

        with ThreadPoolExecutor(max_workers=N_THREADS) as pool:
            list(pool.map(worker, range(N_THREADS)))

        # Every thread must have read back exactly its own values.
        for i in range(N_THREADS):
            ratio, force, model, _policy = observed[i]
            assert ratio == 0.1 * (i + 1), f"thread {i} saw a foreign target_ratio"
            assert force == bool(i % 2), f"thread {i} saw a foreign force_kompress"
            assert model == f"model-{i}", f"thread {i} saw a foreign kompress_model"

    def test_runtime_defaults_when_unset(self) -> None:
        """A freshly used thread sees the documented defaults, not another's."""
        router = ContentRouter()
        # Main thread sets values...
        router._runtime_target_ratio = 0.9
        router._runtime_force_kompress = True
        router._runtime_kompress_model = "main-model"

        seen: dict[str, object] = {}

        def worker() -> None:
            seen["ratio"] = router._runtime_target_ratio
            seen["force"] = router._runtime_force_kompress
            seen["model"] = router._runtime_kompress_model
            seen["policy"] = router._runtime_compression_policy

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        # The worker thread never set anything → documented defaults.
        assert seen["ratio"] is None
        assert seen["force"] is False
        assert seen["model"] is None
        assert seen["policy"] is None
        # Main thread's values are untouched.
        assert router._runtime_target_ratio == 0.9
        assert router._runtime_force_kompress is True
        assert router._runtime_kompress_model == "main-model"

    def test_getattr_read_sites_still_work(self) -> None:
        """The ``getattr(self, "_runtime_*", default)`` read sites must resolve.

        The properties always exist, so getattr returns the property value
        (with the property's own default) rather than the getattr default.
        """
        router = ContentRouter()
        assert getattr(router, "_runtime_force_kompress", False) is False
        assert getattr(router, "_runtime_target_ratio", None) is None
        assert getattr(router, "_runtime_kompress_model", None) is None
        router._runtime_force_kompress = True
        assert getattr(router, "_runtime_force_kompress", False) is True


class TestSmartCrusherRuntimeOptionsIsolation:
    """A shared SmartCrusher must not leak its per-request policy across threads."""

    def test_concurrent_policy_writes_do_not_cross_contaminate(self) -> None:
        crusher = SmartCrusher()
        barrier = threading.Barrier(N_THREADS)
        observed: dict[int, object] = {}
        lock = threading.Lock()
        policies = [object() for _ in range(N_THREADS)]

        def worker(i: int) -> None:
            crusher._runtime_compression_policy = policies[i]
            barrier.wait()
            with lock:
                observed[i] = crusher._runtime_compression_policy

        with ThreadPoolExecutor(max_workers=N_THREADS) as pool:
            list(pool.map(worker, range(N_THREADS)))

        for i in range(N_THREADS):
            assert observed[i] is policies[i], f"thread {i} saw a foreign policy"

    def test_policy_default_when_unset(self) -> None:
        crusher = SmartCrusher()
        crusher._runtime_compression_policy = object()
        seen: list[object] = []

        def worker() -> None:
            seen.append(crusher._runtime_compression_policy)

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        assert seen == [None]


class TestCompressConcurrentDifferentConfigs:
    """End-to-end: concurrent compress() with different configs on the shared pipeline."""

    def test_concurrent_compress_matches_serial(self) -> None:
        # Distinct per-call runtime options. compress() routes these through
        # the SHARED module-level pipeline (one ContentRouter/SmartCrusher),
        # which is exactly where the race lived.
        cases = [
            {"target_ratio": 0.2, "force_kompress": False},
            {"target_ratio": 0.5, "force_kompress": True},
            {"target_ratio": 0.8, "force_kompress": False},
            {"target_ratio": 0.3, "force_kompress": True},
        ]
        # Repeat each case so threads genuinely overlap on the shared pipeline.
        work = [(i % len(cases), _make_messages(i)) for i in range(N_THREADS)]

        # Serial baseline: each (config, messages) pair run alone.
        serial = {
            idx: compress(msgs, **cases[case_i]).messages
            for idx, (case_i, msgs) in enumerate(work)
        }

        # Concurrent run on the same shared pipeline.
        def run(item: tuple[int, tuple[int, list[dict[str, str]]]]):
            idx, (case_i, msgs) = item
            return idx, compress(msgs, **cases[case_i]).messages

        with ThreadPoolExecutor(max_workers=N_THREADS) as pool:
            concurrent = dict(pool.map(run, list(enumerate(work))))

        # Each concurrent call must produce exactly what it produces serially.
        # If runtime options bled across threads, a call would be compressed
        # under a foreign target_ratio/force_kompress and diverge.
        for idx in range(len(work)):
            assert concurrent[idx] == serial[idx], (
                f"call {idx} diverged under concurrency — runtime options leaked"
            )
