from dataclasses import dataclass

from catalog.common import NotFound, PartConflict, availability, identifier, millimetres, transaction


@dataclass(frozen=True)
class PadSpec:
    id: str
    thickness: int
    active: bool


def init_pad_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS pads (
        id TEXT PRIMARY KEY, thickness INTEGER NOT NULL CHECK(thickness >= 0),
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)))''')


def get_pad(db, pad_id):
    row = db.execute('SELECT id, thickness, active FROM pads WHERE id = ?', (pad_id,)).fetchone()
    return PadSpec(row[0], row[1], bool(row[2])) if row else None


def register_pad(db, pad_id, thickness):
    identifier(pad_id, '垫片编号')
    millimetres(thickness, '垫片厚度')
    with transaction(db):
        if get_pad(db, pad_id) is not None:
            raise PartConflict(f'垫片已登记：{pad_id}')
        db.execute('INSERT INTO pads(id, thickness) VALUES (?, ?)', (pad_id, thickness))
        return get_pad(db, pad_id)


def revise_pad_spec(db, pad_id, thickness):
    identifier(pad_id, '垫片编号')
    millimetres(thickness, '垫片厚度')
    with transaction(db):
        result = db.execute('UPDATE pads SET thickness = ? WHERE id = ?', (thickness, pad_id))
        if not result.rowcount:
            raise NotFound(f'未知垫片：{pad_id}')
        return get_pad(db, pad_id)


def set_pad_availability(db, pad_id, active):
    identifier(pad_id, '垫片编号')
    with transaction(db):
        result = db.execute('UPDATE pads SET active = ? WHERE id = ?', (availability(active), pad_id))
        if not result.rowcount:
            raise NotFound(f'未知垫片：{pad_id}')
        return get_pad(db, pad_id)
