from audit.closeout import get_closeout_snapshot
from catalog.common import NotFound


class CloseoutNotFound(NotFound):
    pass


def read_closeout(db, closeout_id):
    snapshot = get_closeout_snapshot(db, closeout_id)
    if snapshot is None:
        raise CloseoutNotFound(f'未知班末核对号：{closeout_id}')
    return snapshot
