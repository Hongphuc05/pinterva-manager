from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AllocationTool(Protocol):
    def select_block(self, remaining_order_ids: list[str], quantity: int) -> list[str]:
        """Return which of remaining_order_ids to grant, at most `quantity` of them.

        V1's contract (claude.md §3 C2, chốt không đổi): FIFO, contiguous block —
        the first `quantity` entries of `remaining_order_ids` in the order given, or
        fewer if remaining_order_ids has fewer than `quantity` entries. Never
        round-robin, never re-pick from an already-granted order. The real
        production allocation tool (chạy nơi khác, không phải repo này) plugs in
        here later without any caller needing to change.
        """
        ...
