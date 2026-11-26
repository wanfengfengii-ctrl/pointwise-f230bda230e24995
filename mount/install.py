from dataclasses import dataclass

from catalog.bases import get_base
from catalog.common import Conflict, NotFound, identifier, record_id, transaction
from catalog.pads import get_pad
from catalog.replicas import get_replica
from dispatch.tickets import get_handoff
from edition.snapshots import get_snapshot
from mount.occupancy import claim_base, get_occupancy


class MountConflict(Conflict):
    pass


@dataclass(frozen=True)
class Installation:
    id: int
    handoff_id: int
    base_id: str
    slot: str
    pad_id: str


def init_installation_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS installations (
        id INTEGER PRIMARY KEY, handoff_id INTEGER NOT NULL UNIQUE REFERENCES handoffs(id),
        base_id TEXT NOT NULL REFERENCES bases(id), slot TEXT NOT NULL,
        pad_id TEXT NOT NULL REFERENCES pads(id))''')


def get_installation(db, installation_id):
    row = db.execute('SELECT * FROM installations WHERE id = ?', (installation_id,)).fetchone()
    return Installation(*row) if row else None


def find_installation_for_handoff(db, handoff_id):
    row = db.execute('SELECT * FROM installations WHERE handoff_id = ?', (handoff_id,)).fetchone()
    return Installation(*row) if row else None


def _installation_context(db, handoff_id, base_id):
    ticket = get_handoff(db, record_id(handoff_id))
    if ticket is None:
        raise NotFound(f'未知交接号：{handoff_id}')
    if ticket.ended or find_installation_for_handoff(db, ticket.id):
        raise MountConflict(f'交接已办理实装：{ticket.id}')
    identifier(base_id, '实际底座编号')
    base = get_base(db, base_id)
    if base is None or not base.active:
        raise MountConflict(f'底座未登记或已停用：{base_id}')
    if get_occupancy(db, base_id) is not None:
        raise MountConflict(f'底座已占用：{base_id}')
    replica = get_replica(db, ticket.replica_id)
    if replica is None or not replica.active:
        raise MountConflict(f'复制件当前不可用：{ticket.replica_id}')
    snapshot = get_snapshot(db, ticket.edition_id)
    options = []
    for pad_id in snapshot.allowed_pads(ticket.back, base.slot):
        pad = get_pad(db, pad_id)
        if pad is not None and pad.active:
            options.append(pad.id)
    if not options:
        raise MountConflict(f'原发行在所报槽标无可用垫片：{base.slot}')
    return ticket, base, options


def list_install_options(db, handoff_id, base_id):
    with transaction(db, write=False):
        return _installation_context(db, handoff_id, base_id)[2]


def install_mount(db, handoff_id, base_id, pad_id):
    identifier(pad_id, '垫片编号')
    with transaction(db):
        ticket, base, options = _installation_context(db, handoff_id, base_id)
        if pad_id not in options:
            raise MountConflict(f'垫片不符合原发行的实际槽标规则：{pad_id}')
        result = db.execute('''INSERT INTO installations(handoff_id, base_id, slot, pad_id)
            VALUES (?, ?, ?, ?)''', (ticket.id, base.id, base.slot, pad_id))
        installation_id = result.lastrowid
        claim_base(db, base.id, installation_id)
        from relocation.service import assert_all_active_plans_feasible
        assert_all_active_plans_feasible(db)
        return get_installation(db, installation_id)
