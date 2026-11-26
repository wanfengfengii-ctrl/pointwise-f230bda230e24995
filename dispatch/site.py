import argparse
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qsl
from wsgiref.simple_server import make_server

from audit.closeout import init_closeout_tables
from audit.pages import show_closeout, submit_closeout
from catalog.bases import (get_base, get_slot_spec, init_base_tables, register_base,
                           revise_slot_spec, set_base_availability)
from catalog.common import Conflict, NotFound, record_id, transaction
from catalog.pads import (get_pad, init_pad_table, register_pad, revise_pad_spec,
                          set_pad_availability)
from catalog.replicas import (get_replica, init_replica_tables, register_replica,
                              revise_backing_spec, set_replica_availability)
from catalog.seed import init_seed_table, load_sample
from dispatch.http import View, document, error_view, field, form, link, select, table
from dispatch.pages import show_handoff_form, show_receipt, submit_handoff
from dispatch.tickets import init_ticket_tables
from edition.current import init_current_table
from edition.pages import show_current_edition, show_edition, submit_edition
from edition.snapshots import init_edition_tables
from mount.install import init_installation_table
from mount.occupancy import init_occupancy_table
from mount.pages import show_mount_form, show_removal_form, submit_mount, submit_removal
from mount.remove import init_removal_table
from proof.drafts import init_draft_tables
from proof.pages import render_proof, render_revision_diff, submit_proof
from relocation.pages import show_plan, show_relocation_form, submit_plan_move, submit_relocation
from relocation.service import init_relocation_tables


def _connect(path):
    db = sqlite3.connect(path, isolation_level=None)
    db.execute('PRAGMA foreign_keys = ON')
    return db


def open_database(path):
    db = _connect(path)
    try:
        with transaction(db):
            for initialize in (init_replica_tables, init_base_tables, init_pad_table, init_draft_tables,
                               init_seed_table, init_edition_tables, init_current_table, init_ticket_tables,
                               init_installation_table, init_occupancy_table, init_removal_table,
                               init_relocation_tables, init_closeout_tables):
                initialize(db)
    except BaseException:
        db.close()
        raise
    return db


def _kind(fields):
    kind = fields.get('kind')
    if kind not in ('replica', 'base', 'pad'):
        raise ValueError('部件品类须为 replica、base 或 pad')
    return kind


def _measurement(fields, name):
    value = fields.get(name)
    if isinstance(value, str) and re.fullmatch(r'-?[0-9]{1,19}', value):
        return int(value)
    return value


def _catalog_view(db):
    kinds = [('replica', '复制件'), ('base', '底座'), ('pad', '垫片')]
    kind_controls = select('kind', '品类', kinds)
    specifications = (field('thickness', '背板或垫片厚度') + field('minimum', '槽深下限')
                      + field('maximum', '槽深上限'))
    controls = kind_controls + field('id', '编号') + field('back', '背标') + field('slot', '槽标') + specifications
    body = '<p>厚度和槽深均填整数毫米。复制件填背标与厚度，底座填槽标与槽深区间，垫片填厚度。</p>'
    body += form('/parts', controls, '录入部件')
    body += form('/parts/revise', kind_controls + field('id', '背标、槽标或垫片编号') + specifications, '更正规格')
    controls = kind_controls + field('id', '实物或垫片编号')
    controls += select('active', '可用状态', [('true', '可用'), ('false', '停用')])
    body += form('/parts/availability', controls, '保存可用状态')
    replicas = [asdict(get_replica(db, row[0])) for row in db.execute('SELECT id FROM replicas ORDER BY id')]
    bases = [asdict(get_base(db, row[0])) for row in db.execute('SELECT id FROM bases ORDER BY id')]
    pads = [asdict(get_pad(db, row[0])) for row in db.execute('SELECT id FROM pads ORDER BY id')]
    for base in bases:
        spec = get_slot_spec(db, base['slot'])
        base.update(minimum=spec.minimum, maximum=spec.maximum)
    for label, rows, columns in (
        ('复制件', replicas, ('id', 'back', 'thickness', 'active')),
        ('底座', bases, ('id', 'slot', 'minimum', 'maximum', 'active')),
        ('垫片', pads, ('id', 'thickness', 'active')),
    ):
        names = {'id': '编号', 'back': '背标', 'slot': '槽标', 'thickness': '厚度',
                 'minimum': '槽深下限', 'maximum': '槽深上限', 'active': '可用'}
        body += f'<h2>{label}</h2>'
        body += table((names[column] for column in columns),
                      ([('是' if row[column] else '否') if column == 'active' else row[column]
                        for column in columns] for row in rows))
    return View('部件目录', {'replicas': replicas, 'bases': bases, 'pads': pads}, body)


def _part_result(part, status):
    data = asdict(part) if is_dataclass(part) else part
    body = table(('字段', '规格'), data.items()) + link('/parts', '返回部件目录')
    return View('部件已保存', data, body, status)


def _add_part(db, fields):
    kind = _kind(fields)
    part_id = fields.get('id')
    if kind == 'replica':
        part = register_replica(db, part_id, fields.get('back'), _measurement(fields, 'thickness'))
    elif kind == 'base':
        part = register_base(db, part_id, fields.get('slot'), _measurement(fields, 'minimum'),
                             _measurement(fields, 'maximum'))
    else:
        part = register_pad(db, part_id, _measurement(fields, 'thickness'))
    return _part_result(part, 201)


def _revise_part(db, fields):
    kind = _kind(fields)
    part_id = fields.get('id')
    if kind == 'replica':
        part = revise_backing_spec(db, part_id, _measurement(fields, 'thickness'))
    elif kind == 'base':
        part = revise_slot_spec(db, part_id, _measurement(fields, 'minimum'), _measurement(fields, 'maximum'))
    else:
        part = revise_pad_spec(db, part_id, _measurement(fields, 'thickness'))
    return _part_result(part, 200)


def _set_availability(db, fields):
    functions = {'replica': set_replica_availability, 'base': set_base_availability, 'pad': set_pad_availability}
    active = fields.get('active')
    if isinstance(active, str) and active in ('true', 'false'):
        active = active == 'true'
    return _part_result(functions[_kind(fields)](db, fields.get('id'), active), 200)


def _read_path_id(value):
    try:
        return record_id(value)
    except ValueError as error:
        raise NotFound('找不到该记录') from error


_POST = {
    '/parts': _add_part, '/parts/revise': _revise_part, '/parts/availability': _set_availability,
    '/proofs': submit_proof, '/editions': submit_edition, '/handoffs': submit_handoff,
    '/mounts': submit_mount, '/removals': submit_removal, '/closeouts': submit_closeout,
    '/relocations': submit_relocation,
}


def _get(db, path, fields):
    match path:
        case '/':
            body = '<p>准备校样、发行、交出实物，并凭原交接号登记实装和撤装。</p>'
            return View('巡展复制件配装台', {}, body + link('/proofs', '建立校样'))
        case '/parts':
            return _catalog_view(db)
        case '/proofs':
            return render_proof(db)
        case '/editions' | '/editions/current':
            return show_current_edition(db, fields.get('exhibition'))
        case '/handoffs':
            if fields.get('id'):
                return show_receipt(db, _read_path_id(fields['id']))
            return show_handoff_form(db, fields)
        case '/mounts':
            return show_mount_form(db, fields)
        case '/removals':
            return show_removal_form(db, fields)
        case '/closeouts':
            return show_closeout(db, _read_path_id(fields['id']) if fields.get('id') else None)
        case '/relocations':
            if fields.get('id'):
                return show_plan(db, _read_path_id(fields['id']))
            return show_relocation_form(db, fields.get('exhibition', ''))
    match path.strip('/').split('/'):
        case ['proofs', revision]:
            return render_proof(db, revision)
        case ['proofs', revision, 'diff']:
            return render_revision_diff(db, revision, fields.get('against'))
        case ['editions', edition_id]:
            return show_edition(db, _read_path_id(edition_id))
        case ['handoffs', handoff_id]:
            return show_receipt(db, _read_path_id(handoff_id))
        case ['closeouts', closeout_id]:
            return show_closeout(db, _read_path_id(closeout_id))
        case ['relocations', relocation_id]:
            return show_plan(db, _read_path_id(relocation_id))
    if path in _POST:
        return error_view(405, '该入口须提交表单')
    raise NotFound('未知办理路径')


class Application:
    def __init__(self, db_path):
        self.db_path = db_path
        with closing(open_database(db_path)):
            pass

    def handle(self, method, path, fields=None):
        fields = {} if fields is None else fields
        try:
            if not isinstance(fields, dict):
                raise ValueError('请求字段须构成一个对象')
            with closing(_connect(self.db_path)) as db:
                if method == 'GET':
                    with transaction(db, write=False):
                        return _get(db, path, fields)
                if method == 'POST' and path in _POST:
                    return _POST[path](db, fields)
                if method == 'POST':
                    parts = path.strip('/').split('/')
                    if len(parts) == 3 and parts[0] == 'relocations' and parts[2] == 'moves':
                        return submit_plan_move(db, _read_path_id(parts[1]), fields)
                    raise NotFound('未知提交路径')
                return error_view(405, '该站点接收 GET 和 POST')
        except Conflict as error:
            return error_view(409, str(error))
        except NotFound as error:
            return error_view(404, str(error))
        except ValueError as error:
            return error_view(422, str(error))

    def __call__(self, environ, start_response):
        method = environ['REQUEST_METHOD']
        content_type = environ.get('CONTENT_TYPE', '').partition(';')[0].strip().lower()
        accepts_json = 'application/json' in environ.get('HTTP_ACCEPT', '') or content_type == 'application/json'
        try:
            fields = dict(parse_qsl(environ.get('QUERY_STRING', ''), keep_blank_values=True))
            if method == 'POST':
                size = int(environ.get('CONTENT_LENGTH') or '0')
                if not 0 <= size <= 1_000_000:
                    raise ValueError('表单超过可接受大小')
                raw = environ['wsgi.input'].read(size).decode('utf-8')
                fields = json.loads(raw) if content_type == 'application/json' else dict(parse_qsl(raw, keep_blank_values=True))
            view = self.handle(method, environ.get('PATH_INFO', '/'), fields)
        except (ValueError, UnicodeError) as error:
            view = error_view(422, str(error))
        if accepts_json:
            content = json.dumps(view.data, ensure_ascii=False)
            media_type = 'application/json'
        else:
            content = document(view)
            media_type = 'text/html'
        body = content.encode('utf-8')
        start_response(f'{view.status} {HTTPStatus(view.status).phrase}',
                       [('Content-Type', media_type + '; charset=utf-8'), ('Content-Length', str(len(body)))])
        return [body]


def _demo_original_fit_and_closeout():
    with TemporaryDirectory(prefix='tour-mount-demo-') as directory:
        db_path = Path(directory) / 'tour.sqlite3'
        app = Application(db_path)
        with closing(open_database(db_path)) as db:
            load_sample(db)

        def request(method, path, fields=None):
            view = app.handle(method, path, fields)
            if view.status not in (200, 201):
                raise RuntimeError(f'{method} {path}: {view.status} {view.data}')
            return view.data

        proof = request('GET', '/proofs/river-1')
        edition = request('POST', '/editions', {'revision': 'river-1'})
        issued = []
        for replica_id in ('R1', 'R2', 'R3'):
            receipt = request('POST', '/handoffs', {'edition_id': edition['id'], 'replica_id': replica_id})
            issued.append(receipt['ticket']['id'])
        mount_fields = {'handoff_id': issued[0], 'base_id': 'U1'}
        options = request('GET', '/mounts', mount_fields)['allowed_pads']
        mounted = request('POST', '/mounts', {**mount_fields, 'pad_id': 'X'})
        removed = request('POST', '/removals', {'installation_id': mounted['id'], 'reason': '完成试摆'})
        request('POST', '/mounts', {'handoff_id': issued[1], 'base_id': 'U1', 'pad_id': 'Y'})
        closeout = request('POST', '/closeouts', {'exhibition': 'river'})
        app = Application(db_path)
        history = request('GET', f'/closeouts/{closeout["id"]}')
        receipt = request('GET', f'/handoffs/{issued[0]}')
        expected = ['X', 'Y']
        actual = proof['coverage']['groups'][0]['allowed_pads']
        downstream_expected = {'options': expected, 'slot': 'u', 'pad_id': 'X', 'original_edition': edition['id']}
        downstream_actual = {'options': options, 'slot': receipt['installation']['slot'],
                             'pad_id': receipt['installation']['pad_id'], 'original_edition': receipt['ticket']['edition_id']}
        if actual != expected or downstream_actual != downstream_expected:
            raise RuntimeError(f'明标试配与实装不符：{actual} / {downstream_actual}')
        expected_groups = {'pending': [issued[2]], 'mounted': [issued[1]], 'removed': [issued[0]]}
        actual_groups = {state: [entry['ticket']['id'] for entry in rows]
                         for state, rows in history['categories'].items()}
        if (history != closeout or actual_groups != expected_groups or receipt['removal'] != removed
                or receipt['installation'] != mounted):
            raise RuntimeError(f'班末核对或原号回执不符：{history} / {receipt}')
        scenario = {
            'case_id': 'N1', 'input': {'backing_mm': 8, 'slot_mm': [10, 11], 'pads_mm': {'L': 1, 'X': 2, 'Y': 3, 'H': 4}},
            'expected': expected, 'actual': actual, 'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': ['proof/fit.py', 'proof/coverage.py', 'edition/issue.py', 'mount/install.py', 'dispatch/lookup.py'],
            'oracle': '手算 8 + 2 = 10、8 + 3 = 11，其余两片在区间外。实际底座 U1 为 u，原交接选择 X。',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False, sort_keys=True))
        print(json.dumps({'receipt': receipt, 'closeout': history}, ensure_ascii=False, sort_keys=True))


def _demo():
    _demo_original_fit_and_closeout()
    from relocation.demo import run_demo
    run_demo()


def main(argv=None):
    parser = argparse.ArgumentParser(description='巡展复制件配装台')
    parser.add_argument('--db', type=Path, default=Path('tour.sqlite3'))
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--sample', action='store_true')
    serve = commands.add_parser('serve')
    serve.add_argument('--port', type=int, default=8000)
    commands.add_parser('demo')
    options = parser.parse_args(argv)
    if options.command == 'demo':
        _demo()
    elif options.command == 'init':
        with closing(open_database(options.db)) as db:
            if options.sample:
                print(json.dumps(load_sample(db), ensure_ascii=False))
    else:
        with make_server('127.0.0.1', options.port, Application(options.db)) as server:
            print(f'http://127.0.0.1:{server.server_port}', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                return


if __name__ == '__main__':
    main()
