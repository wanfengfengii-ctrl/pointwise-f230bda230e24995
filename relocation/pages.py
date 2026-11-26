from dispatch.http import View, esc, field, form, link, table, textarea
from relocation.service import RelocationConflict, confirm_move, create_relocation, get_plan


def show_relocation_form(db, exhibition=''):
    controls = field('exhibition', '展次', exhibition)
    targets = textarea('targets', '目标清单（每行：实装号,目标底座编号）')
    buffers = field('buffers', '托架编号（逗号分隔，可留空）')
    body = '<p>先按当前实际占用核验整条搬移路线；签出后实际位置仍在逐步确认时才改变。</p>'
    body += form('/relocations', controls + targets + buffers, '签出换座计划')
    body += form('/relocations', field('id', '换座计划号'), '按号继续', method='get')
    return View('换座签出', {}, body)


def submit_relocation(db, fields):
    plan = create_relocation(
        db,
        fields.get('exhibition'),
        fields.get('targets'),
        fields.get('buffers', []),
    )
    return render_plan(plan, status=201, notice='换座计划已签出，请确认当前第一步。')


def show_plan(db, plan_id):
    return render_plan(get_plan(db, plan_id))


def submit_plan_move(db, plan_id, fields):
    try:
        plan = confirm_move(db, plan_id, fields)
    except RelocationConflict as error:
        message = esc(str(error))
        body = f'<p role="alert">{message}</p>'
        body += f'<p>{link(f"/relocations/{plan_id}", "返回计划查看当前步骤")}</p>'
        return View('确认冲突', {'error': str(error)}, body, 409)
    step = plan['moves'][-1]['step'] if plan['moves'] else None
    notice = f'第 {step} 步已确认，实际占用和实移记录已同时更新。' if step else '已确认移动。'
    if plan['state'] == 'completed':
        notice += ' 本计划已完成。'
    return render_plan(plan, status=201, notice=notice)


def render_plan(plan, status=200, notice=None):
    plan_id = plan['id']
    state_text = '已完成' if plan['state'] == 'completed' else '在办'
    body = f'<p>展次 {esc(plan["exhibition"])} · 状态 {state_text}</p>'
    if notice:
        body += f'<p role="status">{esc(notice)}</p>'
    body += '<h2>各件位置与目标</h2>'
    body += table(('实装号', '当前确认底座', '目标底座'),
                 ((row['installation_id'], row['base_id'], row['target_base_id'])
                  for row in plan['positions']))

    next_move = plan['next_move']
    if next_move:
        action = f'/relocations/{plan_id}/moves'
        body += '<h2>当前可办的一步</h2>'
        body += table(('步骤', '实装号', '起点', '落点'), [(
            next_move['step'], next_move['installation_id'],
            next_move['from_base_id'], next_move['to_base_id'])])
        controls = (
            field('step', '', next_move['step'], hidden=True)
            + field('installation_id', '', next_move['installation_id'], hidden=True)
            + field('from_base_id', '', next_move['from_base_id'], hidden=True)
            + field('to_base_id', '', next_move['to_base_id'], hidden=True)
        )
        body += form(action, controls, f'确认第 {next_move["step"]} 步')
    elif plan['state'] == 'completed':
        body += '<p>全部目标已经确认完成；现在可按各件的实际底座办理撤装。</p>'

    body += '<h2>已确认实移</h2>'
    if plan['moves']:
        body += table(('步骤', '实装号', '起点', '落点'),
                      ((move['step'], move['installation_id'],
                        move['from_base_id'], move['to_base_id']) for move in plan['moves']))
    else:
        body += '<p>尚无实移。</p>'
    body += f'<p>{link(f"/relocations/{plan_id}", "刷新/续办此计划")}</p>'
    return View(f'换座计划 {plan_id}', plan, body, status)
