def init_current_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS current_editions (
        exhibition TEXT PRIMARY KEY REFERENCES exhibitions(id),
        edition_id INTEGER NOT NULL REFERENCES editions(id))''')


def get_current_edition_id(db, exhibition):
    row = db.execute('SELECT edition_id FROM current_editions WHERE exhibition = ?', (exhibition,)).fetchone()
    return row[0] if row else None


def set_current_edition(db, exhibition, edition_id):
    db.execute('''INSERT INTO current_editions(exhibition, edition_id) VALUES (?, ?)
        ON CONFLICT(exhibition) DO UPDATE SET edition_id = excluded.edition_id''', (exhibition, edition_id))
