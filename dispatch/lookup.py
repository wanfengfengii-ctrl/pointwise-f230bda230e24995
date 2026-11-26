from dataclasses import asdict, dataclass

from catalog.common import NotFound, transaction
from dispatch.tickets import HandoffTicket, get_handoff
from mount.install import Installation, find_installation_for_handoff
from mount.remove import Removal, find_removal_for_installation
from relocation.service import actual_base_for_installation, list_moves_for_installation


@dataclass(frozen=True)
class HandoffReceipt:
    ticket: HandoffTicket
    state: str
    installation: Installation | None
    removal: Removal | None
    actual_base_id: str | None = None
    moves: list[dict] | None = None


def build_receipt(db, ticket):
    installation = find_installation_for_handoff(db, ticket.id)
    if installation is None:
        return HandoffReceipt(ticket, 'pending', None, None)
    removal = find_removal_for_installation(db, installation.id)
    moves = list_moves_for_installation(db, installation.id)
    actual_base_id = actual_base_for_installation(db, installation.id, installation.base_id)
    state = 'removed' if removal else 'mounted'
    return HandoffReceipt(ticket, state, installation, removal, actual_base_id, moves)


def receipt_data(receipt):
    data = {
        'ticket': asdict(receipt.ticket),
        'state': receipt.state,
        'installation': asdict(receipt.installation) if receipt.installation else None,
        'removal': asdict(receipt.removal) if receipt.removal else None,
    }
    if receipt.moves:
        data['actual_base_id'] = receipt.actual_base_id
        data['moves'] = receipt.moves
    return data


def get_receipt(db, handoff_id):
    with transaction(db, write=False):
        ticket = get_handoff(db, handoff_id)
        if ticket is None:
            raise NotFound(f'未知交接号：{handoff_id}')
        return build_receipt(db, ticket)
