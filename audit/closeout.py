import json
from dataclasses import asdict, dataclass

from audit.reconcile import reconcile_exhibition
from catalog.common import NotFound, identifier, transaction
from proof.drafts import exhibition_exists


@dataclass(frozen=True)
class CloseoutSnapshot:
    id: int
    exhibition: str
    categories: dict


def init_closeout_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS closeouts (
        id INTEGER PRIMARY KEY, exhibition TEXT NOT NULL REFERENCES exhibitions(id),
        payload TEXT NOT NULL)''')


def create_closeout(db, exhibition):
    identifier(exhibition, '核对展次')
    with transaction(db):
        if not exhibition_exists(db, exhibition):
            raise NotFound(f'未知展次：{exhibition}')
        categories = asdict(reconcile_exhibition(db, exhibition))
        result = db.execute('INSERT INTO closeouts(exhibition, payload) VALUES (?, ?)',
                            (exhibition, json.dumps(categories)))
        return CloseoutSnapshot(result.lastrowid, exhibition, categories)


def get_closeout_snapshot(db, closeout_id):
    row = db.execute('SELECT id, exhibition, payload FROM closeouts WHERE id = ?', (closeout_id,)).fetchone()
    return CloseoutSnapshot(row[0], row[1], json.loads(row[2])) if row else None
