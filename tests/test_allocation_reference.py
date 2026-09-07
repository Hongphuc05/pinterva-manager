from app.adapters.allocation.reference import ReferenceAllocationTool


def test_select_block_takes_first_n_in_order():
    tool = ReferenceAllocationTool()
    assert tool.select_block(["DJ1", "DJ2", "DJ3"], 2) == ["DJ1", "DJ2"]


def test_select_block_returns_fewer_when_not_enough_remain():
    tool = ReferenceAllocationTool()
    assert tool.select_block(["DJ1"], 5) == ["DJ1"]


def test_select_block_empty_when_nothing_remains():
    tool = ReferenceAllocationTool()
    assert tool.select_block([], 5) == []
