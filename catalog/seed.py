import json
from pathlib import Path

from catalog.bases import register_base
from catalog.common import identifier, transaction
from catalog.pads import register_pad
from catalog.replicas import register_replica
from proof.drafts import save_draft


SAMPLE_PATH = Path(__file__).resolve().parents[1] / 'sample.json'


def init_seed_table(db):
    db.execute('CREATE TABLE IF NOT EXISTS sample_versions (version TEXT PRIMARY KEY)')


def get_loaded_sample_version(db, version=None):
    if version is None:
        row = db.execute('SELECT version FROM sample_versions ORDER BY rowid DESC LIMIT 1').fetchone()
    else:
        row = db.execute('SELECT version FROM sample_versions WHERE version = ?', (version,)).fetchone()
    return row[0] if row else None


def load_sample(db, path=SAMPLE_PATH):
    sample = json.loads(Path(path).read_text(encoding='utf-8'))
    version = identifier(sample['version'], '样例版本')
    with transaction(db):
        if get_loaded_sample_version(db, version) is not None:
            return {'version': version, 'loaded': False}
        for replica in sample['replicas']:
            register_replica(db, replica['id'], replica['back'], replica['thickness'])
        for base in sample['bases']:
            register_base(db, base['id'], base['slot'], base['minimum'], base['maximum'])
        for pad in sample['pads']:
            register_pad(db, pad['id'], pad['thickness'])
        save_draft(db, sample['draft'])
        db.execute('INSERT INTO sample_versions VALUES (?)', (version,))
        return {'version': version, 'loaded': True}
