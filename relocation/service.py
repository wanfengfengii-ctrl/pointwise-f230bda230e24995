from catalog.bases import get_base
from catalog.common import Conflict, NotFound, identifier, record_id, transaction
from dispatch.tickets import get_handoff
from edition.snapshots import get_snapshot
from mount.install import get_installation
from mount.remove import find_removal_for_installation
from proof.drafts import exhibition_exists
from relocation.routing import find_route


class RelocationConflict(Conflict):
    pass


def init_relocation_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS relocations (
        id INTEGER PRIMARY KEY,
        exhibition TEXT NOT NULL REFERENCES exhibitions(id),
        state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active', 'completed'))
    )''')
    db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS relocation_one_active_per_exhibition
        ON relocations(exhibition) WHERE state = 'active' ''')

    db.execute('''CREATE TABLE IF NOT EXISTS relocation_items (
        plan_id INTEGER NOT NULL REFERENCES relocations(id),
        ordinal INTEGER NOT NULL,
        installation_id INTEGER NOT NULL REFERENCES installations(id),
        initial_base_id TEXT NOT NULL REFERENCES bases(id),
        target_base_id TEXT NOT NULL REFERENCES bases(id),
        current_base_id TEXT NOT NULL REFERENCES bases(id),
        PRIMARY KEY(plan_id, installation_id),
        UNIQUE(plan_id, ordinal),
        UNIQUE(plan_id, target_base_id)
    )''')

    db.execute('''CREATE TABLE IF NOT EXISTS relocation_bases (
        plan_id INTEGER NOT NULL REFERENCES relocations(id),
        ordinal INTEGER NOT NULL,
        base_id TEXT NOT NULL REFERENCES bases(id),
        PRIMARY KEY(plan_id, base_id),
        UNIQUE(plan_id, ordinal)
    )''')

    db.execute('''CREATE TABLE IF NOT EXISTS relocation_moves (
        id INTEGER PRIMARY KEY,
        plan_id INTEGER NOT NULL REFERENCES relocations(id),
        step INTEGER NOT NULL CHECK(step >= 1),
        installation_id INTEGER NOT NULL REFERENCES installations(id),
        from_base_id TEXT NOT NULL REFERENCES bases(id),
        to_base_id TEXT NOT NULL REFERENCES bases(id),
        UNIQUE(plan_id, step)
    )''')
    db.execute('''CREATE INDEX IF NOT EXISTS relocation_moves_by_installation
        ON relocation_moves(installation_id, id)''')


def parse_targets(raw):
    if isinstance(raw, str):
        parsed = []
        for line in raw.splitlines():
            text = line.strip()
            if not text:
                continue
            parts = [part.strip() for part in text.replace('，', ',').split(',')]
            if len(parts) != 2 or not all(parts):
                raise ValueError('每行目标须为“实装号,目标底座编号”')
            parsed.append({'installation_id': parts[0], 'base_id': parts[1]})
        raw = parsed

    if not isinstance(raw, list) or not raw:
        raise ValueError('targets 须为至少一件的目标列表')

    targets = []
    seen_installations = set()
    seen_bases = set()
    for row in raw:
        if isinstance(row, str):
            parts = [part.strip() for part in row.split(',')]
            if len(parts) != 2:
                raise ValueError('每个目标须包含实装号和目标底座编号')
            row = {'installation_id': parts[0], 'base_id': parts[1]}
        if not isinstance(row, dict):
            raise ValueError('每个目标须为实装号和目标底座对象')
        installation_id = record_id(row.get('installation_id'))
        base_id = identifier(row.get('base_id'), '目标底座编号')
        if installation_id in seen_installations:
            raise ValueError(f'换座清单中的实装号重复：{installation_id}')
        if base_id in seen_bases:
            raise ValueError(f'换座目标底座重复：{base_id}')
        seen_installations.add(installation_id)
        seen_bases.add(base_id)
        targets.append({'installation_id': installation_id, 'base_id': base_id})
    return targets


def parse_buffers(raw):
    if raw is None:
        raw = []
    if isinstance(raw, str):
        if not raw.strip():
            return []
        raw = raw.replace('，', ',').split(',')
    if not isinstance(raw, list):
        raise ValueError('buffers 须为托架编号列表或逗号分隔文字')
    buffers = []
    for value in raw:
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        base_id = identifier(text, '托架编号')
        if base_id not in buffers:
            buffers.append(base_id)
    return buffers


def parse_move_fields(fields):
    return {
        'step': record_id(fields.get('step')),
        'installation_id': record_id(fields.get('installation_id')),
        'from_base_id': identifier(fields.get('from_base_id'), '起点底座编号'),
        'to_base_id': identifier(fields.get('to_base_id'), '落点底座编号'),
    }


def _plan_row(db, plan_id):
    return db.execute('SELECT id, exhibition, state FROM relocations WHERE id = ?',
                      (plan_id,)).fetchone()


def get_plan_row(db, plan_id):
    row = _plan_row(db, plan_id)
    if row is None:
        raise NotFound(f'未知换座计划：{plan_id}')
    return row


def list_moves_for_installation(db, installation_id):
    rows = db.execute('''SELECT plan_id, step, installation_id, from_base_id, to_base_id
        FROM relocation_moves WHERE installation_id = ? ORDER BY id''',
                      (installation_id,)).fetchall()
    return [{
        'relocation_id': plan_id,
        'step': step,
        'installation_id': item_id,
        'from_base_id': from_base,
        'to_base_id': to_base,
    } for plan_id, step, item_id, from_base, to_base in rows]


def actual_base_for_installation(db, installation_id, fallback_base_id):
    row = db.execute('SELECT base_id FROM base_occupancy WHERE installation_id = ?',
                     (installation_id,)).fetchone()
    if row is not None:
        return row[0]
    row = db.execute('''SELECT to_base_id FROM relocation_moves
        WHERE installation_id = ? ORDER BY id DESC LIMIT 1''',
                     (installation_id,)).fetchone()
    return row[0] if row is not None else fallback_base_id


def find_active_plan_for_installation(db, installation_id):
    row = db.execute('''SELECT p.id FROM relocations AS p
        JOIN relocation_items AS i ON i.plan_id = p.id
        WHERE i.installation_id = ? AND p.state = 'active' LIMIT 1''',
                     (installation_id,)).fetchone()
    return row[0] if row else None


def _eligible_pad_move(db, installation_id, base_id):
    installation = get_installation(db, installation_id)
    base = get_base(db, base_id)
    if installation is None or base is None:
        return False
    ticket = get_handoff(db, installation.handoff_id)
    if ticket is None:
        return False
    edition = get_snapshot(db, ticket.edition_id)
    if edition is None:
        return False
    return installation.pad_id in edition.allowed_pads(ticket.back, base.slot)


def plan_route(db, plan_id):
    row = _plan_row(db, plan_id)
    if row is None:
        return None
    _, _, state = row

    item_rows = db.execute('''SELECT installation_id, target_base_id, current_base_id
        FROM relocation_items WHERE plan_id = ? ORDER BY ordinal''', (plan_id,)).fetchall()
    if not item_rows:
        return None

    item_ids = [item_id for item_id, _, _ in item_rows]
    target_by_item = {item_id: target for item_id, target, _ in item_rows}

    start_by_item = {}
    for item_id, _, stored_base in item_rows:
        occupancy = db.execute('SELECT base_id FROM base_occupancy WHERE installation_id = ?',
                               (item_id,)).fetchone()
        if state == 'active':
            if occupancy is None:
                return None
            start_by_item[item_id] = occupancy[0]
        else:
            start_by_item[item_id] = occupancy[0] if occupancy is not None else stored_base

    scope_rows = db.execute('SELECT base_id FROM relocation_bases WHERE plan_id = ? ORDER BY ordinal',
                            (plan_id,)).fetchall()
    scope_bases = [row[0] for row in scope_rows]
    occupancy_rows = db.execute('SELECT base_id, installation_id FROM base_occupancy').fetchall()
    external_occupants = {base_id: installation_id for base_id, installation_id in occupancy_rows}

    return find_route(
        item_ids=item_ids,
        start_by_item=start_by_item,
        target_by_item=target_by_item,
        scope_bases=scope_bases,
        external_occupants=external_occupants,
        base_active=lambda base_id: (base := get_base(db, base_id)) is not None and base.active,
        eligible=lambda installation_id, base_id: _eligible_pad_move(db, installation_id, base_id),
    )


def current_next_move(db, plan_id):
    plan = _plan_row(db, plan_id)
    if plan is None or plan[2] != 'active':
        return None
    route = plan_route(db, plan_id)
    if not route:
        return None
    count = db.execute('SELECT COUNT(*) FROM relocation_moves WHERE plan_id = ?',
                       (plan_id,)).fetchone()[0]
    return {'step': count + 1, **route[0]}


def assert_all_active_plans_feasible(db):
    plan_ids = [row[0] for row in db.execute(
        "SELECT id FROM relocations WHERE state = 'active' ORDER BY id").fetchall()]
    for plan_id in plan_ids:
        if plan_route(db, plan_id) is None:
            raise RelocationConflict(f'该操作会断掉换座计划 {plan_id} 的全部完成路线')


def _active_scope_overlap(db, exhibition, scope_bases):
    if not scope_bases:
        return None
    placeholders = ','.join('?' for _ in scope_bases)
    row = db.execute(f'''SELECT p.id FROM relocations AS p
        JOIN relocation_bases AS b ON b.plan_id = p.id
        WHERE p.state = 'active' AND p.exhibition != ?
          AND b.base_id IN ({placeholders})
        ORDER BY p.id LIMIT 1''', (exhibition, *scope_bases)).fetchone()
    return row[0] if row else None


def create_relocation(db, exhibition, raw_targets, raw_buffers=None):
    exhibition = identifier(exhibition, '展次')
    targets = parse_targets(raw_targets)
    buffers = parse_buffers(raw_buffers)

    with transaction(db):
        if not exhibition_exists(db, exhibition):
            raise NotFound(f'未知展次：{exhibition}')

        active = db.execute('SELECT id FROM relocations WHERE exhibition = ? AND state = ?',
                            (exhibition, 'active')).fetchone()
        if active is not None:
            raise RelocationConflict(f'展次 {exhibition} 已有在办换座计划：{active[0]}')

        loaded = []
        initial_bases = []
        for target in targets:
            installation_id = target['installation_id']
            target_base_id = target['base_id']
            installation = get_installation(db, installation_id)
            if installation is None:
                raise NotFound(f'未知实装号：{installation_id}')
            ticket = get_handoff(db, installation.handoff_id)
            if ticket is None or ticket.exhibition != exhibition:
                raise RelocationConflict(f'实装 {installation_id} 不属于展次 {exhibition}')
            if find_removal_for_installation(db, installation_id) is not None:
                raise RelocationConflict(f'实装 {installation_id} 已撤装，不能换座')
            occupancy = db.execute('SELECT base_id FROM base_occupancy WHERE installation_id = ?',
                                   (installation_id,)).fetchone()
            if occupancy is None:
                raise RelocationConflict(f'实装 {installation_id} 当前不在展')
            current_base_id = occupancy[0]
            if target_base_id == current_base_id:
                raise RelocationConflict(f'实装 {installation_id} 的目标底座与实际位置相同')

            target_base = get_base(db, target_base_id)
            if target_base is None:
                raise NotFound(f'未知目标底座：{target_base_id}')

            loaded.append((installation_id, current_base_id, target_base_id))
            initial_bases.append(current_base_id)

        for base_id in buffers:
            if get_base(db, base_id) is None:
                raise NotFound(f'未知托架底座：{base_id}')

        scope_bases = list(dict.fromkeys([
            *initial_bases,
            *[target['base_id'] for target in targets],
            *buffers,
        ]))

        overlapping_plan = _active_scope_overlap(db, exhibition, scope_bases)
        if overlapping_plan is not None:
            raise RelocationConflict(f'落点范围与在办换座计划 {overlapping_plan} 冲突')

        cursor = db.execute('INSERT INTO relocations(exhibition) VALUES (?)', (exhibition,))
        plan_id = cursor.lastrowid
        for ordinal, (installation_id, current_base_id, target_base_id) in enumerate(loaded, 1):
            db.execute('''INSERT INTO relocation_items(plan_id, ordinal, installation_id,
                    initial_base_id, target_base_id, current_base_id)
                VALUES (?, ?, ?, ?, ?, ?)''',
                       (plan_id, ordinal, installation_id, current_base_id,
                        target_base_id, current_base_id))
        for ordinal, base_id in enumerate(scope_bases, 1):
            db.execute('INSERT INTO relocation_bases(plan_id, ordinal, base_id) VALUES (?, ?, ?)',
                       (plan_id, ordinal, base_id))

        if current_next_move(db, plan_id) is None:
            raise RelocationConflict('从当前实际占用找不到可逐步完成全部目标的路线')
        return fetch_plan(db, plan_id)


def fetch_plan(db, plan_id):
    row = get_plan_row(db, plan_id)
    plan_id, exhibition, state = row
    items = db.execute('''SELECT installation_id, current_base_id, target_base_id
        FROM relocation_items WHERE plan_id = ? ORDER BY ordinal''', (plan_id,)).fetchall()
    moves = db.execute('''SELECT step, installation_id, from_base_id, to_base_id
        FROM relocation_moves WHERE plan_id = ? ORDER BY step''', (plan_id,)).fetchall()
    plan = {
        'id': plan_id,
        'exhibition': exhibition,
        'state': state,
        'positions': [{
            'installation_id': installation_id,
            'base_id': current_base_id,
            'target_base_id': target_base_id,
        } for installation_id, current_base_id, target_base_id in items],
        'moves': [{
            'step': step,
            'installation_id': installation_id,
            'from_base_id': from_base_id,
            'to_base_id': to_base_id,
        } for step, installation_id, from_base_id, to_base_id in moves],
        'next_move': current_next_move(db, plan_id),
    }
    if state == 'completed':
        plan['next_move'] = None
    return plan


def get_plan(db, plan_id):
    with transaction(db, write=False):
        return fetch_plan(db, record_id(plan_id) if not isinstance(plan_id, int) else plan_id)


def confirm_move(db, plan_id, raw_fields):
    plan_id = record_id(plan_id)
    submitted = parse_move_fields(raw_fields)

    with transaction(db):
        get_plan_row(db, plan_id)
        expected = current_next_move(db, plan_id)
        if expected is None or submitted != expected:
            raise RelocationConflict('确认步骤已过期、重复或与当前计划不一致')

        installation_id = submitted['installation_id']
        from_base_id = submitted['from_base_id']
        to_base_id = submitted['to_base_id']

        item = db.execute('''SELECT current_base_id FROM relocation_items
            WHERE plan_id = ? AND installation_id = ?''',
                          (plan_id, installation_id)).fetchone()
        if item is None or item[0] != from_base_id:
            raise RelocationConflict('确认起点与计划当前落点不一致')
        occupancy = db.execute('SELECT installation_id FROM base_occupancy WHERE base_id = ?',
                               (from_base_id,)).fetchone()
        if occupancy is None or occupancy[0] != installation_id:
            raise RelocationConflict('实际占用已变化，起点不可搬出')
        destination = db.execute('SELECT installation_id FROM base_occupancy WHERE base_id = ?',
                                 (to_base_id,)).fetchone()
        if destination is not None:
            raise RelocationConflict(f'落点已被占用：{to_base_id}')
        base = get_base(db, to_base_id)
        if base is None or not base.active:
            raise RelocationConflict(f'落点未登记或已停用：{to_base_id}')
        if not _eligible_pad_move(db, installation_id, to_base_id):
            raise RelocationConflict('原发行规则不认可原垫片在该落点槽标使用')

        result = db.execute('DELETE FROM base_occupancy WHERE base_id = ? AND installation_id = ?',
                            (from_base_id, installation_id))
        if result.rowcount != 1:
            raise RelocationConflict('实际占用与换座步骤冲突')
        db.execute('INSERT INTO base_occupancy(base_id, installation_id) VALUES (?, ?)',
                   (to_base_id, installation_id))
        db.execute('UPDATE relocation_items SET current_base_id = ? WHERE plan_id = ? AND installation_id = ?',
                   (to_base_id, plan_id, installation_id))
        db.execute('''INSERT INTO relocation_moves(plan_id, step, installation_id,
                from_base_id, to_base_id) VALUES (?, ?, ?, ?, ?)''',
                   (plan_id, submitted['step'], installation_id, from_base_id, to_base_id))

        remaining = db.execute('''SELECT COUNT(*) FROM relocation_items AS i
            WHERE i.plan_id = ? AND i.current_base_id != i.target_base_id''',
                               (plan_id,)).fetchone()[0]
        if remaining == 0:
            db.execute("UPDATE relocations SET state = 'completed' WHERE id = ?", (plan_id,))

        assert_all_active_plans_feasible(db)
        return fetch_plan(db, plan_id)
