from catalog.common import Conflict, NotFound, identifier, record_id, transaction
from catalog.replicas import get_replica
from dispatch.tickets import find_open_handoff, insert_handoff
from edition.snapshots import get_snapshot


class HandoffConflict(Conflict):
    pass


def open_handoff(db, edition_id, replica_id):
    edition_id = record_id(edition_id)
    identifier(replica_id, '复制件编号')
    with transaction(db):
        edition = get_snapshot(db, edition_id)
        if edition is None:
            raise NotFound(f'未知正式号：{edition_id}')
        back = edition.replica_mark(replica_id)
        replica = get_replica(db, replica_id)
        if back is None or replica is None or not replica.active:
            raise HandoffConflict(f'复制件未列入此版或当前不可交：{replica_id}')
        existing = find_open_handoff(db, replica_id)
        if existing:
            raise HandoffConflict(f'复制件已有在途交接：{existing.id}')
        return insert_handoff(db, edition.exhibition, edition.id, replica_id, back)
