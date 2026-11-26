from dataclasses import dataclass
from html import escape
from urllib.parse import urlencode


@dataclass(frozen=True)
class View:
    title: str
    data: dict
    body: str
    status: int = 200


def esc(value):
    return escape(str(value), quote=True)


def link(path, label, **query):
    href = path + ('?' + urlencode(query) if query else '')
    return f'<a href="{esc(href)}">{esc(label)}</a>'


def field(name, label, value='', *, hidden=False):
    control = f'<input name="{esc(name)}" value="{esc(value)}"'
    if hidden:
        return control + ' type="hidden">'
    return f'<label>{esc(label)} {control}></label>'


def textarea(name, label, value=''):
    return f'<label>{esc(label)}<textarea name="{esc(name)}" rows="5">{esc(value)}</textarea></label>'


def select(name, label, options):
    choices = ''.join(f'<option value="{esc(value)}">{esc(text)}</option>' for value, text in options)
    return f'<label>{esc(label)} <select name="{esc(name)}">{choices}</select></label>'


def form(action, controls, submit, *, method='post'):
    return (f'<form method="{esc(method)}" action="{esc(action)}">{controls}'
            f'<button type="submit">{esc(submit)}</button></form>')


def table(headers, rows):
    head = ''.join(f'<th scope="col">{esc(item)}</th>' for item in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{esc(item)}</td>' for item in row) + '</tr>' for row in rows)
    return f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def error_view(status, message):
    return View('无法办理', {'error': message}, f'<p role="alert">{esc(message)}</p>', status)


def document(view):
    navigation = ' '.join(link(path, text) for path, text in (
        ('/', '配装台'), ('/parts', '目录'), ('/proofs', '校样'), ('/editions', '发行'),
        ('/handoffs', '备件交接'), ('/mounts', '展台实装'), ('/removals', '撤装'), ('/closeouts', '班末核对'),
    ))
    return f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(view.title)} · 巡展配装台</title>
<style>
body {{ background: #f4f3ec; color: #17342e; font: 16px/1.6 system-ui, sans-serif; margin: 0; }}
nav {{ padding: 1rem max(1rem, calc((100% - 65rem)/2)); background: #17342e; display: flex; flex-wrap: wrap; gap: 1rem; }}
nav a {{ color: #fff; }} main {{ max-width: 65rem; padding: 1.5rem; margin: auto; }}
form, table {{ background: white; margin: 1rem 0; border: 1px solid #c2c9bb; }}
form {{ padding: 1rem; display: flex; align-items: end; flex-wrap: wrap; gap: .75rem; }}
label {{ display: grid; }} input, select, textarea, button {{ font: inherit; padding: .3rem .5rem; }}
textarea {{ width: min(26rem, 75vw); }} button {{ background: #17342e; color: white; cursor: pointer; }}
table {{ border-collapse: collapse; }} th, td {{ padding: .35rem .85rem; text-align: left; border-bottom: 1px solid #c2c9bb; }}
a {{ color: #095644; }} [role=alert] {{ color: #842d21; }}
</style><nav aria-label="办理入口">{navigation}</nav>
<main><h1>{esc(view.title)}</h1>{view.body}</main></html>'''
