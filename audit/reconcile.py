from dataclasses import dataclass

from catalog.common import transaction
from dispatch.lookup import HandoffReceipt, build_receipt
from dispatch.tickets import list_exhibition_handoffs


@dataclass(frozen=True)
class Reconciliation:
    pending: list[HandoffReceipt]
    mounted: list[HandoffReceipt]
    removed: list[HandoffReceipt]


def reconcile_exhibition(db, exhibition):
    categories = {'pending': [], 'mounted': [], 'removed': []}
    with transaction(db, write=False):
        for ticket in list_exhibition_handoffs(db, exhibition):
            receipt = build_receipt(db, ticket)
            categories[receipt.state].append(receipt)
    return Reconciliation(**categories)
