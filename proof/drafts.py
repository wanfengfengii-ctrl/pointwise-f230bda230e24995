import json
from dataclasses import asdict, dataclass

from catalog.common import Conflict, identifier, transaction
from proof.coverage import evaluate_coverage


class DraftConflict(Conflict):
    pass


@dataclass(frozen=True)
class DraftRevision:
    exhibition: str
    revision: str
    parent: str | None
    replicas: list[str]
    bases: list[str]
    pads: list[str]
    groups: list[dict]


def init_draft_tables(db):
    db.execute('CREATE TABLE IF NOT EXISTS exhibitions (id TEXT PRIMARY KEY)')
    db.execute('''CREATE TABLE IF NOT EXISTS drafts (
        ordinal INTEGER PRIMARY KEY, revision TEXT NOT NULL UNIQUE,
        exhibition TEXT NOT NULL REFERENCES exhibitions(id),
        parent TEXT REFERENCES drafts(revision), payload TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS draft_by_exhibition ON drafts(exhibition, ordinal)')


def exhibition_exists(db, exhibition):
    return db.execute('SELECT 1 FROM exhibitions WHERE id = ?', (exhibition,)).fetchone() is not None


def get_revision(db, revision):
    row = db.execute('SELECT payload FROM drafts WHERE revision = ?', (revision,)).fetchone()
    return DraftRevision(**json.loads(row[0])) if row else None


def get_latest_revision(db, exhibition):
    row = db.execute('''SELECT payload FROM drafts WHERE exhibition = ?
        ORDER BY ordinal DESC LIMIT 1''', (exhibition,)).fetchone()
    return DraftRevision(**json.loads(row[0])) if row else None


def _codes(value, field):
    if not isinstance(value, list):
        raise ValueError(f'{field} 须为编号列表')
    codes = [identifier(item, field) for item in value]
    if len(codes) != len(set(codes)):
        raise ValueError(f'{field} 有重复编号')
    return codes


def _read_draft(fields):
    exhibition = identifier(fields.get('exhibition'), '展次')
    revision = identifier(fields.get('revision'), '修订号')
    parent = fields.get('parent')
    if parent not in ('', None):
        parent = identifier(parent, '编辑基线')
    replicas = _codes(fields.get('replicas'), '复制件')
    bases = _codes(fields.get('bases'), '底座')
    pads = _codes(fields.get('pads'), '候选垫片')
    rows = fields.get('groups')
    if not isinstance(rows, list):
        raise ValueError('必配组合须为列表')
    groups = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('每个必配组合须提供背标和槽标')
        back = identifier(row.get('back'), '背标')
        slot = identifier(row.get('slot'), '槽标')
        if (back, slot) in seen:
            raise ValueError(f'重复必配组合：{back}/{slot}')
        seen.add((back, slot))
        banned = _codes(row.get('banned_pads', []), '禁配垫片')
        reason = row.get('reason', '')
        if not isinstance(reason, str) or len(reason) > 1000:
            raise ValueError('策展禁配原因须为至多 1000 字的文字')
        groups.append({'back': back, 'slot': slot, 'banned_pads': banned, 'reason': reason.strip()})
    return DraftRevision(exhibition, revision, parent or None, replicas, bases, pads, groups)


def save_draft(db, fields):
    draft = _read_draft(fields)
    with transaction(db):
        latest = get_latest_revision(db, draft.exhibition)
        expected_parent = latest.revision if latest else None
        if draft.parent != expected_parent:
            raise DraftConflict(f'编辑基线已过期，当前稿：{expected_parent or "无"}')
        if get_revision(db, draft.revision):
            raise DraftConflict(f'修订号已存在：{draft.revision}')
        report = evaluate_coverage(db, draft)
        if report.errors:
            raise ValueError('；'.join(report.errors))
        db.execute('INSERT OR IGNORE INTO exhibitions(id) VALUES (?)', (draft.exhibition,))
        db.execute('''INSERT INTO drafts(revision, exhibition, parent, payload) VALUES (?, ?, ?, ?)''',
                   (draft.revision, draft.exhibition, draft.parent, json.dumps(asdict(draft))))
        return draft, report
