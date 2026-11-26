from dataclasses import asdict

from audit.closeout import create_closeout
from audit.history import read_closeout
from dispatch.http import View, esc, field, form, link, table


def submit_closeout(db, fields):
    return render_closeout(create_closeout(db, fields.get('exhibition')), status=201)


def show_closeout(db, closeout_id=None):
    if closeout_id is None:
        body = form('/closeouts', field('exhibition', '展次'), '生成班末核对')
        body += form('/closeouts', field('id', '核对号'), '重领班末核对', method='get')
        return View('班末配装核对', {}, body)
    return render_closeout(read_closeout(db, closeout_id))


def render_closeout(snapshot, status=200):
    body = f'<p>展次 {esc(snapshot.exhibition)} · {link(f"/closeouts/{snapshot.id}", "重领此页")}</p>'
    for category, label in (('pending', '未装'), ('mounted', '在展'), ('removed', '已撤')):
        entries = snapshot.categories[category]
        body += f'<h2>{label}（{len(entries)}）</h2>'
        rows = []
        for entry in entries:
            ticket = entry['ticket']
            installation = entry['installation'] or {}
            removal = entry['removal'] or {}
            moves = entry.get('moves') or []
            move_text = '；'.join(
                f"计划{m['relocation_id']}第{m['step']}步 {m['from_base_id']}→{m['to_base_id']}"
                for m in moves
            )
            actual_base_id = entry.get('actual_base_id') or installation.get('base_id', '')
            rows.append((ticket['id'], ticket['edition_id'], ticket['replica_id'], ticket['back'],
                         installation.get('id', ''), installation.get('base_id', ''),
                         actual_base_id, move_text,
                         installation.get('slot', ''), installation.get('pad_id', ''),
                         removal.get('id', ''), removal.get('reason', '')))
        body += table(('交接号', '原发行', '实物', '背标', '实装号', '初装底座',
                       '实际/末落点', '实移', '槽标', '垫片', '撤装号', '原因'), rows)
    return View(f'班末核对 {snapshot.id}', asdict(snapshot), body, status)
