from dataclasses import dataclass

from catalog.common import NotFound, PartConflict, availability, identifier, millimetres, transaction


@dataclass(frozen=True)
class Replica:
    id: str
    back: str
    thickness: int
    active: bool


def init_replica_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS backings (
        mark TEXT PRIMARY KEY, thickness INTEGER NOT NULL CHECK(thickness >= 0))''')
    db.execute('''CREATE TABLE IF NOT EXISTS replicas (
        id TEXT PRIMARY KEY, back TEXT NOT NULL REFERENCES backings(mark),
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)))''')


def get_backing_spec(db, back):
    row = db.execute('SELECT thickness FROM backings WHERE mark = ?', (back,)).fetchone()
    return row[0] if row else None


def get_replica(db, replica_id):
    row = db.execute('''SELECT r.id, r.back, s.thickness, r.active
        FROM replicas AS r JOIN backings AS s ON s.mark = r.back WHERE r.id = ?''',
        (replica_id,)).fetchone()
    return Replica(*row[:3], bool(row[3])) if row else None


def register_replica(db, replica_id, back, thickness):
    identifier(replica_id, '复制件编号')
    identifier(back, '背标')
    millimetres(thickness, '背板厚度')
    with transaction(db):
        if get_replica(db, replica_id) is not None:
            raise PartConflict(f'复制件已登记：{replica_id}')
        existing = get_backing_spec(db, back)
        if existing is None:
            db.execute('INSERT INTO backings VALUES (?, ?)', (back, thickness))
        elif existing != thickness:
            raise ValueError(f'同背标背板规格不一致：{back}')
        db.execute('INSERT INTO replicas(id, back) VALUES (?, ?)', (replica_id, back))
        return get_replica(db, replica_id)


def revise_backing_spec(db, back, thickness):
    identifier(back, '背标')
    millimetres(thickness, '背板厚度')
    result = db.execute('UPDATE backings SET thickness = ? WHERE mark = ?', (thickness, back))
    if not result.rowcount:
        raise NotFound(f'未知背标：{back}')
    return {'back': back, 'thickness': thickness}


def set_replica_availability(db, replica_id, active):
    identifier(replica_id, '复制件编号')
    with transaction(db):
        result = db.execute('UPDATE replicas SET active = ? WHERE id = ?',
                            (availability(active), replica_id))
        if not result.rowcount:
            raise NotFound(f'未知复制件：{replica_id}')
        return get_replica(db, replica_id)
