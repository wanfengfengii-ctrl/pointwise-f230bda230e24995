from dataclasses import dataclass

from catalog.common import Conflict, NotFound, record_id, transaction
from dispatch.tickets import end_handoff
from mount.install import get_installation
from mount.occupancy import release_base


class RemovalConflict(Conflict):
    pass


@dataclass(frozen=True)
class Removal:
    id: int
    installation_id: int
    reason: str


def init_removal_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS removals (
        id INTEGER PRIMARY KEY, installation_id INTEGER NOT NULL UNIQUE REFERENCES installations(id),
        reason TEXT NOT NULL)''')


def find_removal_for_installation(db, installation_id):
    row = db.execute('SELECT * FROM removals WHERE installation_id = ?', (installation_id,)).fetchone()
    return Removal(*row) if row else None


def remove_mount(db, installation_id, reason):
    installation_id = record_id(installation_id)
    with transaction(db):
        installation = get_installation(db, installation_id)
        if installation is None:
            raise NotFound(f'未知实装号：{installation_id}')
        occupancy = db.execute('SELECT base_id FROM base_occupancy WHERE installation_id = ?',
                               (installation_id,)).fetchone()
        if find_removal_for_installation(db, installation_id) is not None or occupancy is None:
            raise RemovalConflict(f'该笔实装不在展：{installation_id}')
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ValueError('填写至多 1000 字的撤装原因')
        reason = reason.strip()

        from relocation.service import assert_all_active_plans_feasible, find_active_plan_for_installation
        plan_id = find_active_plan_for_installation(db, installation_id)
        if plan_id is not None:
            raise RemovalConflict(f'换座计划 {plan_id} 完成前不得撤装实装 {installation_id}')

        actual_base_id = occupancy[0]
        result = db.execute('INSERT INTO removals(installation_id, reason) VALUES (?, ?)',
                            (installation_id, reason))
        release_base(db, actual_base_id, installation_id)
        end_handoff(db, installation.handoff_id)
        assert_all_active_plans_feasible(db)
        return Removal(result.lastrowid, installation_id, reason)
