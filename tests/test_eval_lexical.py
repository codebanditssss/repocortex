import pytest

from repocortex.eval.metrics import METRIC_NAMES
from scripts.eval_lexical import paired_gap


def test_gap_pairs_duplicate_tickets_by_row():
    def row(value):
        return {"ticket": 7, **{name: value for name in METRIC_NAMES}}

    # The same ticket can have distinct gold functions across fix commits.
    result = paired_gap([row(1.0), row(0.0)], [row(1.0), row(0.0)])
    assert result["n"] == 2
    assert result["function_acc@10"] == {"mean": 0.0, "lo": 0.0, "hi": 0.0}


def test_gap_rejects_unaligned_rows():
    with pytest.raises(ValueError, match="matching lengths"):
        paired_gap([{"ticket": 1}], [{"ticket": 2}])
    with pytest.raises(ValueError, match="matching lengths"):
        paired_gap([{"ticket": 1}], [])
