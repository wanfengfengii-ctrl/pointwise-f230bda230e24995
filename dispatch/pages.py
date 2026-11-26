from catalog.common import NotFound, record_id
from dispatch.handover import open_handoff
from dispatch.http import View, esc, field, form, link, select, table
from dispatch.lookup import get_receipt, receipt_data
from edition.snapshots import get_snapshot
from relocation.service import find_active_plan_for_installation


def show_handoff_form(db, fields):
    raw_id = fields.get('edition_id')
    if raw_id:
        edition_id = record_id(raw_id)
        edition = get_snapshot(db, edition_id)
        if edition is None:
            raise NotFound(f'未知正式号：{edition_id}')
        controls = field('edition_id', '', edition.id, hidden=True)
        controls += select('replica_id', '实物编号', ((key, f'{key} · {back}')
                           for key, back in sorted(edition.replicas.items())))
        title = f'按正式版 {edition.id} 交出实物'
    else:
        edition_id = None
        controls = field('edition_id', '正式发行号') + field('replica_id', '实物编号')
        title = '备件交接'
    body = form('/handoffs', controls, '确认交出')
    body += form('/handoffs', field('id', '交接号'), '按号查单', method='get')
    return View(title, {'edition_id': edition_id}, body)


def submit_handoff(db, fields):
    ticket = open_handoff(db, fields.get('edition_id'), fields.get('replica_id'))
    return render_receipt(get_receipt(db, ticket.id), status=201, db=db)


def show_receipt(db, handoff_id):
    return render_receipt(get_receipt(db, handoff_id), db=db)


def render_receipt(receipt, status=200, db=None):
    ticket = receipt.ticket
    labels = {'pending': '未装', 'mounted': '在展', 'removed': '已撤'}
    body = f'<p>实物 {esc(ticket.replica_id)} · 背标 {esc(ticket.back)} · {labels[receipt.state]}</p>'
    body += link(f'/editions/{ticket.edition_id}', f'原正式版 {ticket.edition_id}')
    if receipt.installation:
        installation = receipt.installation
        body += '<h2>初装内容（原号保留）</h2>'
        body += table(('实装号', '初装底座', '初装槽标', '垫片'),
                      [(installation.id, installation.base_id, installation.slot, installation.pad_id)])
        if receipt.moves:
            body += f'<p>当前/撤装前最后实际落点：<strong>{esc(receipt.actual_base_id)}</strong></p>'
            body += table(('换座计划', '步骤', '实装号', '起点', '落点'),
                          ((move['relocation_id'], move['step'], move['installation_id'],
                            move['from_base_id'], move['to_base_id']) for move in receipt.moves))
        if db is not None:
            active_plan_id = find_active_plan_for_installation(db, installation.id)
            if active_plan_id is not None:
                body += f'<p>{link(f"/relocations/{active_plan_id}", "前往换座计划续办")}</p>'
        if receipt.removal:
            body += table(('撤装号', '撤装原因'), [(receipt.removal.id, receipt.removal.reason)])
        else:
            removal_base = receipt.actual_base_id or installation.base_id
            body += link('/removals', '按实际底座办理撤装', installation_id=installation.id)
            body += f'<p>撤装将释放实际底座 {esc(removal_base)}。</p>'
    else:
        body += f'<p>{link("/mounts", "前往展台", handoff_id=ticket.id)}</p>'
    return View(f'交接 {ticket.id}', receipt_data(receipt), body, status)
