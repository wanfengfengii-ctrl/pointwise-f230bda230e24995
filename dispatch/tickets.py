from dataclasses import dataclass

from catalog.common import Conflict


@dataclass(frozen=True)
class HandoffTicket:
    id: int
    exhibition: str
    edition_id: int
    replica_id: str
    back: str
    ended: bool


def init_ticket_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS handoffs (
        id INTEGER PRIMARY KEY, exhibition TEXT NOT NULL REFERENCES exhibitions(id),
        edition_id INTEGER NOT NULL REFERENCES editions(id),
        replica_id TEXT NOT NULL REFERENCES replicas(id), back TEXT NOT NULL,
        ended INTEGER NOT NULL DEFAULT 0 CHECK(ended IN (0, 1)))''')
    db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS handoff_open_replica
        ON handoffs(replica_id) WHERE ended = 0''')
    db.execute('CREATE INDEX IF NOT EXISTS handoff_by_exhibition ON handoffs(exhibition, id)')


def _ticket(row):
    return HandoffTicket(*row[:5], bool(row[5])) if row else None


def insert_handoff(db, exhibition, edition_id, replica_id, back):
    result = db.execute('''INSERT INTO handoffs(exhibition, edition_id, replica_id, back)
        VALUES (?, ?, ?, ?)''', (exhibition, edition_id, replica_id, back))
    return get_handoff(db, result.lastrowid)


def get_handoff(db, handoff_id):
    return _ticket(db.execute('SELECT * FROM handoffs WHERE id = ?', (handoff_id,)).fetchone())


def find_open_handoff(db, replica_id):
    return _ticket(db.execute('SELECT * FROM handoffs WHERE replica_id = ? AND ended = 0',
                              (replica_id,)).fetchone())


def list_exhibition_handoffs(db, exhibition):
    rows = db.execute('SELECT * FROM handoffs WHERE exhibition = ? ORDER BY id', (exhibition,))
    return [_ticket(row) for row in rows]


def end_handoff(db, handoff_id):
    result = db.execute('UPDATE handoffs SET ended = 1 WHERE id = ? AND ended = 0', (handoff_id,))
    if not result.rowcount:
        raise Conflict(f'交接已结束或不存在：{handoff_id}')
