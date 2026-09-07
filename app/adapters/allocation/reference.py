from __future__ import annotations


class ReferenceAllocationTool:
    """V1's only AllocationTool — the exact FIFO/contiguous-block algorithm from
    claude.md §3 C2, written for test/demo purposes. NOT the production tool (a
    different one already runs elsewhere) — this exists so the domain layer has a
    correct interface to depend on before that integration happens.
    """

    def select_block(self, remaining_order_ids: list[str], quantity: int) -> list[str]:
        return remaining_order_ids[:quantity]
