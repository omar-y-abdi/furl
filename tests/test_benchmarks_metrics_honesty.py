"""Honesty pins for the benchmark measurement plane (EFF-7 / TEST-16).

Covers:
* the STRICT presence ladder in ``benchmarks.metrics`` (the lenient
  scalar-substring fallback the verify harness removed is gone here too);
* per-case engine reset (same case twice ⇒ identical numbers);
* recovery via the raw-text compressors' bracket ``Retrieve …: hash=H``
  markers;
* the needle-recall control arm (non-naming queries, reported separately);
* ``verify.measure`` ordering check (byte_exact is no longer claimable for
  a reordered full reconstruction);
* the imp2 A/B corroboration channel (asserted, and proven to fire).
"""

from __future__ import annotations

import json

import pytest

from benchmarks import metrics
from benchmarks.metrics import (
    _bracket_marker_hashes,
    _item_in_recovered,
    _item_present,
)

# ---------------------------------------------------------------------------
# Strict presence ladder (TEST-16b).
# ---------------------------------------------------------------------------


def test_scattered_scalars_no_longer_count_as_present() -> None:
    """The exact case the lenient fallback passed: every scalar of the row
    appears in the text, but the row is not reconstructible. Strict rejects."""
    item = {"commit": "abc123", "subject": "fix parser"}
    output_text = "unrelated abc123 prose mentioning fix parser somewhere"
    assert _item_present(item, output_text, row_sigs=None, decoded_sigs=None) is False


def test_string_item_counts_only_when_verbatim() -> None:
    line = "npm WARN deprecated glob@7.2.3: Glob versions prior to v9 are no longer supported"
    assert _item_present(line, f"prefix\n{line}\nsuffix", None, None) is True
    assert _item_present(line[:30], "some other text entirely", None, None) is False


def test_json_array_rendering_still_uses_exact_signature_membership() -> None:
    item = {"a": 1, "b": "x"}
    sig = json.dumps(item, sort_keys=True, ensure_ascii=False)
    assert _item_present(item, "ignored", row_sigs={sig}, decoded_sigs=None) is True
    assert _item_present({"a": 2, "b": "x"}, "ignored", row_sigs={sig}, decoded_sigs=None) is False


def test_recovered_blob_strictness() -> None:
    """JSON blobs need exact row equality; text blobs recover only STRING
    items verbatim — a structured item's scattered scalars never count."""
    row = {"commit": "abc123", "subject": "fix parser"}
    json_blob = json.dumps([row])
    assert _item_in_recovered(row, [json_blob]) is True
    assert _item_in_recovered({**row, "subject": "other"}, [json_blob]) is False

    text_blob = "line one abc123\nfix parser line two"
    assert _item_in_recovered(row, [text_blob]) is False  # lenient would say True
    assert _item_in_recovered("line one abc123", [text_blob]) is True


def test_bracket_marker_hashes_extraction() -> None:
    out = (
        "kept line\n"
        "[300 matches compressed to 30. Retrieve more: hash=e895e3b28f88e41f02f42359]\n"
        "[41 lines compressed to 12. Retrieve full diff: hash=6C502DA0DEA6F6F6B03DAEB7]"
    )
    assert _bracket_marker_hashes(out) == {
        "e895e3b28f88e41f02f42359",
        "6c502da0dea6f6f6b03daeb7",
    }
    assert _bracket_marker_hashes("no markers here, hash=deadbeef is too short") == set()


# ---------------------------------------------------------------------------
# Per-case engine reset (TEST-16c) + raw-text recovery, one real E2E case.
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_measure_case_is_cold_per_case_and_repeatable() -> None:
    """Same case measured twice ⇒ byte-identical metrics. Without the
    per-case reset the second run is served the first run's cached
    compression against a differently-warmed store."""
    from benchmarks.datasets import build_markdown_doc_dataset

    dataset = build_markdown_doc_dataset()
    first = metrics.measure_case("md@1", dataset.query, dataset.items, dataset.messages)
    second = metrics.measure_case("md@1", dataset.query, dataset.items, dataset.messages)
    assert first == second


@pytest.mark.slow
def test_raw_text_case_recovery_via_bracket_marker() -> None:
    """A raw-text dataset must score dropped lines as CCR-recoverable through
    the compressor's bracket marker (full-original store entry): retention
    100% while drop ratio > 0."""
    from benchmarks.datasets import build_ci_log_dataset

    dataset = build_ci_log_dataset()
    case = metrics.measure_case("ci_log@n", dataset.query, dataset.items, dataset.messages)
    assert case.took_lossy_path, "LogCompressor should elide lines on a 200+ line log"
    assert case.n_dropped > 0
    assert case.n_recoverable == case.n_dropped, (
        f"dropped lines not recoverable via the bracket marker: "
        f"{case.n_recoverable}/{case.n_dropped}"
    )
    assert case.information_retention == 1.0
    assert case.lossless_reduction > 0.5


# ---------------------------------------------------------------------------
# Needle control arm (EFF-7 / TEST-16a).
# ---------------------------------------------------------------------------


def test_control_queries_never_name_the_needle() -> None:
    """The control arm's whole point: no literal token of the needle row may
    appear in the control query (the naming query, by contrast, must name
    the sentinel)."""
    from benchmarks.needle_recall import FAMILIES

    for family in FAMILIES:
        assert "__FURL_NEEDLE_DO_NOT_DROP__" in family.query
        control_lower = family.control_query.lower()
        for value in family.needle.values():
            for token in str(value).replace("/", " ").replace("_", " ").split():
                if len(token) < 4:
                    continue  # articles/numbers shared with any English query
                assert token.lower() not in control_lower, (
                    f"{family.name} control query leaks needle token {token!r}"
                )


@pytest.mark.slow
def test_needle_grid_tags_and_separates_the_two_arms() -> None:
    from benchmarks.needle_recall import SEARCH_FAMILY, recall_rate, run_needle_recall

    results = run_needle_recall(
        families=(SEARCH_FAMILY,),
        cardinalities=(30,),
        positions=("middle",),
        arms=("naming", "control"),
    )
    assert [r.arm for r in results] == ["naming", "control"]
    naming = [r for r in results if r.arm == "naming"]
    control = [r for r in results if r.arm == "control"]
    # Per-arm rates are computable independently; the search family is the
    # lossless regime, so the NAMING arm must recall its needle.
    assert recall_rate(naming) == 1.0
    assert 0.0 <= recall_rate(control) <= 1.0


def test_payload_reports_arms_separately() -> None:
    """The floor gate reads the naming number; the control number must live
    in its own block, never blended."""
    from benchmarks.needle_recall import NeedleResult
    from benchmarks.run_bench import build_results_payload

    trials = [
        NeedleResult("search", 30, "middle", True, True, False, 30, arm="naming"),
        NeedleResult("logs", 30, "middle", True, False, True, 5, arm="naming"),
        NeedleResult("search", 30, "middle", True, True, False, 30, arm="control"),
        NeedleResult("logs", 30, "middle", False, False, False, 5, arm="control"),
    ]
    payload = build_results_payload([], trials)
    needle = payload["needle_recall"]
    assert needle["overall_output_or_ccr"] == 1.0  # naming arm only
    assert needle["control"]["overall_output_or_ccr"] == 0.5  # control arm only
    assert len(needle["trials"]) == 4


# ---------------------------------------------------------------------------
# verify.measure ordering check (TEST-16d).
# ---------------------------------------------------------------------------


def _rows(n: int) -> list[dict[str, int]]:
    return [{"id": i, "value": i * 10} for i in range(n)]


def test_verify_byte_exact_requires_order_on_full_visible_reconstruction() -> None:
    from verify.measure import hash_compare_structured

    items = _rows(5)
    in_order = json.dumps(items)
    reordered = json.dumps(list(reversed(items)))

    ok = hash_compare_structured(items, in_order, {})
    assert ok.byte_exact and ok.order_checked and ok.order_exact

    scrambled = hash_compare_structured(items, reordered, {})
    assert scrambled.order_checked and not scrambled.order_exact
    assert not scrambled.byte_exact, (
        "a reordered full reconstruction must no longer claim byte-exact"
    )
    # The multiset itself still matches — only the ordering claim fails.
    assert scrambled.n_missing == 0


def test_verify_ccr_filled_reconstruction_keeps_multiset_semantics() -> None:
    """When CCR fills gaps there is no ordered surface covering the multiset:
    order is not claimable and byte_exact keeps its multiset meaning."""
    from verify.measure import hash_compare_structured

    items = _rows(5)
    visible = json.dumps(items[:3])
    recovered = {"aa" * 12: json.dumps(items[3:])}
    hc = hash_compare_structured(items, visible, recovered)
    assert hc.byte_exact and not hc.order_checked and hc.n_missing == 0


# ---------------------------------------------------------------------------
# imp2 A/B corroboration (TEST-16e).
# ---------------------------------------------------------------------------


def test_imp2_dup_count_channel_fires_and_matches_the_mirror() -> None:
    from benchmarks.imp2_ab import validate_dup_count_channel

    validate_dup_count_channel()  # raises AssertionError on drift


def test_imp2_prediction_mirrors_first_kept_representative_rule() -> None:
    from benchmarks.imp2_ab import predict_dup_stamps

    all_items = [
        {"host": "a", "msg": "same", "seq": 0},
        {"host": "a", "msg": "same", "seq": 1},
        {"host": "a", "msg": "same", "seq": 2},
        {"host": "a", "msg": "other", "seq": 3},
    ]
    exclude = frozenset({"seq"})
    kept = [
        {"host": "a", "msg": "same", "seq": 0, "_dup_count": 3},
        {"host": "a", "msg": "same", "seq": 2},  # later family member: no stamp
        {"host": "a", "msg": "other", "seq": 3},  # singleton: no stamp
    ]
    assert predict_dup_stamps(kept, all_items, exclude) == [3, None, None]


@pytest.mark.slow
def test_imp2_measurement_asserts_corroboration_on_the_real_dataset() -> None:
    from benchmarks.datasets import repeated_log_rows
    from benchmarks.imp2_ab import measure_imp2_ab

    ab = measure_imp2_ab("repeated_logs", repeated_log_rows(limit=90))
    assert ab.exclude_set == ("icmp_seq",)
    assert ab.families_on < ab.families_off
    # engine_max_dup_count is now a CHECKED fact (assert inside measure_imp2_ab),
    # whatever its value — not a printed number nothing verifies.
    assert ab.engine_max_dup_count >= 0
