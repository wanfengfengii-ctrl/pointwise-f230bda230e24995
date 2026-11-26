from dataclasses import dataclass

from catalog.common import NotFound, transaction
from dispatch.tickets import HandoffTicket, get_handoff
from mount.install import Installation, find_installation_for_handoff
from mount.remove import Removal, find_removal_for_installation


@dataclass(frozen=True)
class HandoffReceipt:
    ticket: HandoffTicket
    state: str
    installation: Installation | None
    removal: Removal | None


def build_receipt(db, ticket):
    installation = find_installation_for_handoff(db, ticket.id)
    if installation is None:
        return HandoffReceipt(ticket, 'pending', None, None)
    removal = find_removal_for_installation(db, installation.id)
    return HandoffReceipt(ticket, 'removed' if removal else 'mounted', installation, removal)


def get_receipt(db, handoff_id):
    with transaction(db, write=False):
        ticket = get_handoff(db, handoff_id)
        if ticket is None:
            raise NotFound(f'未知交接号：{handoff_id}')
        return build_receipt(db, ticket)
