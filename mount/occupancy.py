from catalog.common import Conflict


def init_occupancy_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS base_occupancy (
        base_id TEXT PRIMARY KEY REFERENCES bases(id),
        installation_id INTEGER NOT NULL UNIQUE REFERENCES installations(id))''')


def get_occupancy(db, base_id):
    row = db.execute('SELECT installation_id FROM base_occupancy WHERE base_id = ?', (base_id,)).fetchone()
    return row[0] if row else None


def claim_base(db, base_id, installation_id):
    result = db.execute('''INSERT INTO base_occupancy(base_id, installation_id) VALUES (?, ?)
        ON CONFLICT(base_id) DO NOTHING''', (base_id, installation_id))
    if not result.rowcount:
        raise Conflict(f'底座已占用：{base_id}')


def release_base(db, base_id, installation_id):
    result = db.execute('DELETE FROM base_occupancy WHERE base_id = ? AND installation_id = ?',
                        (base_id, installation_id))
    if not result.rowcount:
        raise Conflict(f'实装 {installation_id} 未持有底座 {base_id}')
