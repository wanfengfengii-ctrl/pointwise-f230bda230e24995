from dataclasses import dataclass

from catalog.common import NotFound, PartConflict, availability, identifier, millimetres, transaction


@dataclass(frozen=True)
class SlotSpec:
    slot: str
    minimum: int
    maximum: int


@dataclass(frozen=True)
class Base:
    id: str
    slot: str
    active: bool


def init_base_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS slots (
        mark TEXT PRIMARY KEY, minimum INTEGER NOT NULL CHECK(minimum >= 0),
        maximum INTEGER NOT NULL CHECK(maximum >= minimum))''')
    db.execute('''CREATE TABLE IF NOT EXISTS bases (
        id TEXT PRIMARY KEY, slot TEXT NOT NULL REFERENCES slots(mark),
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)))''')


def get_slot_spec(db, slot):
    row = db.execute('SELECT mark, minimum, maximum FROM slots WHERE mark = ?', (slot,)).fetchone()
    return SlotSpec(*row) if row else None


def get_base(db, base_id):
    row = db.execute('SELECT id, slot, active FROM bases WHERE id = ?', (base_id,)).fetchone()
    return Base(row[0], row[1], bool(row[2])) if row else None


def _slot_spec(slot, minimum, maximum):
    identifier(slot, '槽标')
    millimetres(minimum, '槽深下限')
    millimetres(maximum, '槽深上限')
    if minimum > maximum:
        raise ValueError(f'槽深区间倒置：{slot}')
    return SlotSpec(slot, minimum, maximum)


def register_base(db, base_id, slot, minimum, maximum):
    identifier(base_id, '底座编号')
    proposed = _slot_spec(slot, minimum, maximum)
    with transaction(db):
        if get_base(db, base_id) is not None:
            raise PartConflict(f'底座已登记：{base_id}')
        existing = get_slot_spec(db, slot)
        if existing is None:
            db.execute('INSERT INTO slots VALUES (?, ?, ?)', (slot, minimum, maximum))
        elif existing != proposed:
            raise ValueError(f'同槽标底座规格不一致：{slot}')
        db.execute('INSERT INTO bases(id, slot) VALUES (?, ?)', (base_id, slot))
        return get_base(db, base_id)


def revise_slot_spec(db, slot, minimum, maximum):
    proposed = _slot_spec(slot, minimum, maximum)
    result = db.execute('UPDATE slots SET minimum = ?, maximum = ? WHERE mark = ?',
                        (minimum, maximum, slot))
    if not result.rowcount:
        raise NotFound(f'未知槽标：{slot}')
    return proposed


def set_base_availability(db, base_id, active):
    identifier(base_id, '底座编号')
    with transaction(db):
        result = db.execute('UPDATE bases SET active = ? WHERE id = ?',
                            (availability(active), base_id))
        if not result.rowcount:
            raise NotFound(f'未知底座：{base_id}')
        return get_base(db, base_id)
