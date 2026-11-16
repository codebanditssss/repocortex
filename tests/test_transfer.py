import pytest
from scripts.eval_transfer import split_audit
from repocortex.mine.dataset import assign_splits


def issue(ticket, commit, time, split, text=None):
    return dict(ticket=ticket, commit=commit, time=time, split=split,
                summary=text or str(ticket), description="report")


def test_chronological_commit_group_split_has_no_overlap():
    rows = [issue(1,"a",1,""),issue(2,"a",1,""),issue(3,"b",2,""),issue(4,"c",3,"")]
    assign_splits(rows, .4)
    audit = split_audit({"issues": rows})
    assert audit["chronological"]
    assert not any(audit["overlap"].values())
    assert rows[0]["split"] == rows[1]["split"]


@pytest.mark.parametrize("second", [
    issue(1,"b",2,"test"),
    issue(2,"a",2,"test"),
    issue(2,"b",0,"test"),
    issue(2,"b",2,"test", "  SAME   query  "),
])
def test_rejects_ticket_commit_chronology_and_normalized_query_leakage(second):
    with pytest.raises(ValueError, match="overlap"):
        split_audit({"issues":[issue(1,"a",1,"train","same query"),second]})
