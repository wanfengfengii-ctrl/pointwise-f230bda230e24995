from dataclasses import asdict

from catalog.common import NotFound, identifier
from dispatch.http import View, esc, field, form, link, table, textarea
from proof.coverage import evaluate_coverage
from proof.drafts import get_revision, save_draft


def _split(value, separator):
    return [item.strip() for item in value.split(separator) if item.strip()]


def _form_fields(fields):
    draft = dict(fields)
    for key in ('replicas', 'bases', 'pads'):
        draft[key] = _split(fields.get(key, ''), ',')
    groups = []
    for line in fields.get('groups', '').splitlines():
        if not line.strip():
            continue
        columns = [column.strip() for column in line.split(',', 3)]
        if len(columns) < 2:
            raise ValueError('每行至少填写背标和槽标')
        back, slot, banned, reason = columns + [''] * (4 - len(columns))
        groups.append({'back': back, 'slot': slot, 'banned_pads': _split(banned, '|'), 'reason': reason})
    draft['groups'] = groups
    return draft


def submit_proof(db, fields):
    draft, report = save_draft(db, _form_fields(fields) if isinstance(fields.get('groups'), str) else fields)
    return _render_draft(draft, report, status=201)


def _editor(draft=None):
    controls = field('exhibition', '展次', draft.exhibition if draft else '')
    controls += field('revision', '新修订号')
    controls += field('parent', '编辑基线', draft.revision if draft else '')
    for key, label in (('replicas', '复制件'), ('bases', '底座'), ('pads', '候选垫片')):
        value = ','.join(getattr(draft, key)) if draft else ''
        controls += field(key, f'{label}编号（逗号分隔）', value)
    groups = ''
    if draft:
        groups = '\n'.join(','.join((row['back'], row['slot'], '|'.join(row['banned_pads']), row['reason']))
                           for row in draft.groups)
    controls += textarea('groups', '每行填写 背标,槽标,禁配垫片（用 | 分隔）,原因', groups)
    return form('/proofs', controls, '保存校样')


def _render_draft(draft, report, status=200):
    rows = [(row['back'], row['slot'], ', '.join(row['allowed_pads']) or '缺项',
             ', '.join(row['banned_pads']), row['reason']) for row in report.groups]
    body = f'<p>展次 {esc(draft.exhibition)} · 编辑基线 {esc(draft.parent or "首稿")}</p>'
    body += table(('背标', '槽标', '允许垫片', '禁配垫片', '原因'), rows)
    if not report.groups:
        body += '<p role="alert">尚未填写必配组合。</p>'
    if report.errors:
        body += f'<p role="alert">{esc("；".join(report.errors))}</p>'
    if report.is_complete:
        body += form('/editions', field('revision', '', draft.revision, hidden=True), '签发此修订')
    if draft.parent:
        body += link(f'/proofs/{draft.revision}/diff', '与上稿比较', against=draft.parent)
    body += '<h2>保存后继修订</h2>' + _editor(draft)
    coverage = {**asdict(report), 'is_complete': report.is_complete}
    return View(f'校样 {draft.revision}', {'draft': asdict(draft), 'coverage': coverage}, body, status)


def render_proof(db, revision=None):
    if revision is None:
        return View('新建校样', {}, _editor())
    draft = get_revision(db, revision)
    if draft is None:
        raise NotFound(f'未知校样：{revision}')
    return _render_draft(draft, evaluate_coverage(db, draft))


def render_revision_diff(db, revision, against):
    identifier(against, '比较修订号')
    before = get_revision(db, against)
    after = get_revision(db, revision)
    if not before or not after or before.exhibition != after.exhibition:
        raise NotFound('找不到同展次的两份校样')
    old_report = evaluate_coverage(db, before)
    new_report = evaluate_coverage(db, after)
    old = {(row['back'], row['slot']): row for row in old_report.groups}
    new = {(row['back'], row['slot']): row for row in new_report.groups}
    changes = [{'back': key[0], 'slot': key[1], 'before': old.get(key), 'after': new.get(key)}
               for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)]
    references = {name: {'before': getattr(before, name), 'after': getattr(after, name)}
                  for name in ('replicas', 'bases', 'pads') if getattr(before, name) != getattr(after, name)}
    body = '<p>按当前目录比较两稿的试配结果。</p>'
    body += table(('部件引用', '原稿', '本稿'), ((key, ', '.join(row['before']), ', '.join(row['after']))
                  for key, row in references.items()))
    body += table(('背标', '槽标', '原组', '本组'),
                  ((row['back'], row['slot'], _describe_group(row['before']), _describe_group(row['after']))
                   for row in changes))
    errors = {'before': old_report.errors, 'after': new_report.errors}
    if any(errors.values()):
        body += table(('修订', '目录问题'), ((against, '；'.join(errors['before'])),
                                             (revision, '；'.join(errors['after']))))
    return View(f'{against} 与 {revision} 的校样差异',
                {'groups': changes, 'references': references, 'errors': errors}, body)


def _describe_group(row):
    if row is None:
        return '未列'
    allowed = ', '.join(row['allowed_pads']) or '缺项'
    banned = ', '.join(row['banned_pads']) or '无'
    return f'允许 {allowed}，禁配 {banned} {row["reason"]}'.rstrip()
