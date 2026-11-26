from dataclasses import asdict

from catalog.common import NotFound, identifier
from dispatch.http import View, esc, field, form, link, table
from edition.current import get_current_edition_id
from edition.issue import issue_edition
from edition.snapshots import get_snapshot


def submit_edition(db, fields):
    return render_edition(issue_edition(db, fields.get('revision')), status=201)


def show_current_edition(db, exhibition):
    if not exhibition:
        body = form('/editions/current', field('exhibition', '展次'), '领当前版', method='get')
        body += form('/editions', field('revision', '待签修订号'), '签发正式版')
        return View('配装发行', {}, body)
    identifier(exhibition, '展次')
    edition_id = get_current_edition_id(db, exhibition)
    if edition_id is None:
        raise NotFound(f'展次尚无当前发行：{exhibition}')
    return show_edition(db, edition_id)


def show_edition(db, edition_id):
    snapshot = get_snapshot(db, edition_id)
    if snapshot is None:
        raise NotFound(f'未知正式号：{edition_id}')
    return render_edition(snapshot)


def render_edition(snapshot, status=200):
    body = f'<p>展次 {esc(snapshot.exhibition)} · 校样 {esc(snapshot.revision)}</p>'
    body += link('/handoffs', '用此发行开单', edition_id=snapshot.id)
    body += table(('背标', '槽标', '允许垫片'), ((r['back'], r['slot'], ', '.join(r['allowed_pads']))
                  for r in snapshot.groups))
    body += '<h2>采用规格</h2>'
    body += table(('实物编号', '背标', '背板毫米'), ((key, back, snapshot.backings[back])
                  for key, back in sorted(snapshot.replicas.items())))
    body += table(('底座编号', '槽标', '槽深下限', '槽深上限'), (
        (key, slot, snapshot.slots[slot]['minimum'], snapshot.slots[slot]['maximum'])
        for key, slot in sorted(snapshot.bases.items())
    ))
    body += table(('垫片编号', '厚度毫米'), sorted(snapshot.pads.items()))
    return View(f'正式版 {snapshot.id}', asdict(snapshot), body, status)
