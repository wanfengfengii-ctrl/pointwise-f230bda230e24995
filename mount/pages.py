from dataclasses import asdict

from catalog.common import NotFound, record_id
from dispatch.http import View, esc, field, form, link, select, table
from dispatch.lookup import get_receipt, receipt_data
from mount.install import get_installation, install_mount, list_install_options
from mount.remove import remove_mount


def show_mount_form(db, fields):
    raw_id = fields.get('handoff_id')
    base_id = fields.get('base_id', '')
    if not raw_id:
        controls = field('handoff_id', '交接号')
        return View('展台实装', {}, form('/mounts', controls, '领取交接', method='get'))
    handoff_id = record_id(raw_id)
    receipt = get_receipt(db, handoff_id)
    ticket = receipt.ticket
    body = f'<p>交接 {ticket.id} · 原正式版 {ticket.edition_id} · 背标 {esc(ticket.back)}</p>'
    data = {'handoff_id': ticket.id, 'edition_id': ticket.edition_id, 'back': ticket.back,
            'base_id': base_id, 'allowed_pads': []}
    if receipt.installation:
        if base_id:
            list_install_options(db, handoff_id, base_id)
        body += f'<p>{link(f"/handoffs/{ticket.id}", "领取已办回执")}</p>'
        return View('展台实装', data, body)
    controls = field('handoff_id', '', ticket.id, hidden=True) + field('base_id', '实际底座编号', base_id)
    body += form('/mounts', controls, '查看可用垫片', method='get')
    if base_id:
        options = list_install_options(db, handoff_id, base_id)
        data['allowed_pads'] = options
        controls = field('handoff_id', '', ticket.id, hidden=True)
        controls += field('base_id', '', base_id, hidden=True)
        controls += select('pad_id', '实用垫片', ((pad, pad) for pad in options))
        body += form('/mounts', controls, '登记实装')
    return View('展台实装', data, body)


def submit_mount(db, fields):
    installation = install_mount(db, fields.get('handoff_id'), fields.get('base_id'), fields.get('pad_id'))
    body = table(('实装号', '交接号', '底座', '槽标', '垫片'),
                 [(installation.id, installation.handoff_id, installation.base_id,
                   installation.slot, installation.pad_id)])
    body += link(f'/handoffs/{installation.handoff_id}', '领取交接回执')
    return View(f'实装 {installation.id}', asdict(installation), body, 201)


def show_removal_form(db, fields):
    raw_id = fields.get('installation_id')
    if not raw_id:
        controls = field('installation_id', '实装号')
        return View('撤装', {}, form('/removals', controls, '查询实装', method='get'))
    installation_id = record_id(raw_id)
    installation = get_installation(db, installation_id)
    if installation is None:
        raise NotFound(f'未知实装号：{installation_id}')
    receipt = get_receipt(db, installation.handoff_id)
    actual_base_id = receipt.actual_base_id or installation.base_id
    body = f'<p>实装 {installation.id} · 初装底座 {esc(installation.base_id)} · 实际底座 {esc(actual_base_id)}</p>'
    if receipt.removal:
        body += f'<p>已撤装。{link(f"/handoffs/{installation.handoff_id}", "原号回执")}</p>'
    else:
        controls = field('installation_id', '', installation_id, hidden=True) + field('reason', '撤装原因')
        body += form('/removals', controls, '确认撤装并释放底座')
    return View(f'撤装实装 {installation_id}', receipt_data(receipt), body)


def submit_removal(db, fields):
    removal = remove_mount(db, fields.get('installation_id'), fields.get('reason'))
    installation = get_installation(db, removal.installation_id)
    body = f'<p>原实装 {removal.installation_id} · 原因 {esc(removal.reason)}</p>'
    body += link(f'/handoffs/{installation.handoff_id}', '领取原交接回执')
    return View(f'撤装 {removal.id}', asdict(removal), body, 201)
