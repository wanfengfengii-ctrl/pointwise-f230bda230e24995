import json
from dataclasses import dataclass


@dataclass(frozen=True)
class EditionSnapshot:
    id: int
    exhibition: str
    revision: str
    replicas: dict
    bases: dict
    backings: dict
    slots: dict
    pads: dict
    groups: list

    def replica_mark(self, replica_id):
        return self.replicas.get(replica_id)

    def allowed_pads(self, back, slot):
        for row in self.groups:
            if row['back'] == back and row['slot'] == slot:
                return list(row['allowed_pads'])
        return []


def init_edition_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS editions (
        id INTEGER PRIMARY KEY,
        exhibition TEXT NOT NULL REFERENCES exhibitions(id),
        revision TEXT NOT NULL REFERENCES drafts(revision), payload TEXT NOT NULL)''')


def store_snapshot(db, draft, report):
    payload = {
        'replicas': report.replicas, 'bases': report.bases, 'backings': report.backings,
        'slots': report.slots, 'pads': report.pads, 'groups': report.groups,
    }
    result = db.execute('INSERT INTO editions(exhibition, revision, payload) VALUES (?, ?, ?)',
                        (draft.exhibition, draft.revision, json.dumps(payload, sort_keys=True)))
    return EditionSnapshot(result.lastrowid, draft.exhibition, draft.revision, **payload)


def get_snapshot(db, edition_id):
    row = db.execute('SELECT id, exhibition, revision, payload FROM editions WHERE id = ?',
                     (edition_id,)).fetchone()
    if row is None:
        return None
    return EditionSnapshot(*row[:3], **json.loads(row[3]))
