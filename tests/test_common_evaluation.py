"""XR-F-10: the common-set metrics count unknown targets as misses and rank deterministically."""
from graphrec_core.dgsr.evaluation import CommonExample, evaluate_popularity


def test_xr_f_10_popularity_on_common_set_counts_unknown_targets_as_misses():
    examples = [CommonExample("u1", (("a", 1),), "b"), CommonExample("u2", (("b", 1),), "zzz")]
    result = evaluate_popularity(["a", "b", "b", "c"], ["a", "b", "c"], examples)
    assert result["examples"] == 2 and result["unknown_targets"] == 1
    # u1: prefix "a" is excluded, "b" is the most popular remaining -> rank 1.
    assert result["Hit@1"] == 0.5 and result["Hit@10"] == 0.5


def test_xr_f_10_common_examples_round_trip():
    example = CommonExample("u", (("a", 1), ("b", 2)), "c")
    assert CommonExample.from_dict(example.as_dict()) == example
