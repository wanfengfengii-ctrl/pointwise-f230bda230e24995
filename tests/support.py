import json
import sqlite3
import unittest
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from wsgiref.simple_server import WSGIRequestHandler, make_server

from dispatch.site import Application


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


class Forms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms = []
        self.current = None
        self.selected_field = None
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'form':
            self.current = {'action': attrs.get('action'), 'method': attrs.get('method'),
                            'inputs': {}, 'options': {}}
            self.forms.append(self.current)
        elif self.current is not None:
            if tag == 'input':
                self.current['inputs'][attrs['name']] = attrs.get('value', '')
            elif tag == 'select':
                self.selected_field = attrs['name']
                self.current['options'][self.selected_field] = []
            elif tag == 'option' and self.selected_field is not None:
                self.current['options'][self.selected_field].append(attrs['value'])

    def handle_endtag(self, tag):
        if tag == 'form':
            self.current = None
        elif tag == 'select':
            self.selected_field = None

    def get(self, action, method):
        return next(form for form in self.forms if form['action'] == action and form['method'] == method)


class SiteCase(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory(prefix='tour-mount-test-')
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'test.sqlite3'
        self.server = None
        self.addCleanup(self.stop)
        self.start()

    def start(self):
        self.server = make_server('127.0.0.1', 0, Application(self.path), handler_class=QuietHandler)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.thread.join(timeout=5)
            self.server.server_close()
            self.server = None
            self.assertFalse(self.thread.is_alive())

    def reopen(self):
        self.stop()
        self.start()

    def request(self, method, path, fields=None, *, status=200, form=False, html=False):
        headers = {'Accept': 'text/html' if html else 'application/json'}
        data = None
        if fields is not None and method == 'GET':
            path += '?' + urlencode(fields)
        elif fields is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
            data = (urlencode(fields) if form else json.dumps(fields)).encode('utf-8')
        try:
            response = urlopen(Request(self.url + path, data=data, headers=headers, method=method), timeout=5)
        except HTTPError as error:
            response = error
        with response:
            text = response.read().decode('utf-8')
            self.assertEqual(status, response.code, text)
            self.assertEqual('text/html' if html else 'application/json', response.headers.get_content_type())
        return text if html else json.loads(text)

    def get(self, path, fields=None, **kwargs):
        return self.request('GET', path, fields, **kwargs)

    def post(self, path, fields, status=201, **kwargs):
        return self.request('POST', path, fields, status=status, **kwargs)

    def rows(self, query, args=()):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(query, args).fetchall()

    def count(self, table):
        return self.rows(f'SELECT COUNT(*) FROM {table}')[0][0]

    def catalog(self, pads=(('X', 2), ('Y', 3))):
        for replica_id, back in (('R1', 'A'), ('R2', 'A'), ('R3', 'A'), ('R4', 'B')):
            self.post('/parts', {'kind': 'replica', 'id': replica_id, 'back': back, 'thickness': 8})
        for base_id, slot, minimum, maximum in (('U1', 'u', 10, 11), ('U2', 'u', 10, 11), ('V1', 'v', 11, 11)):
            self.post('/parts', {'kind': 'base', 'id': base_id, 'slot': slot,
                                 'minimum': minimum, 'maximum': maximum})
        for pad_id, thickness in pads:
            self.post('/parts', {'kind': 'pad', 'id': pad_id, 'thickness': thickness})

    def draft(self, revision='r1', *, exhibition='river', parent=None, pads=None, groups=None, status=201):
        fields = {'exhibition': exhibition, 'revision': revision, 'parent': parent,
                  'replicas': ['R1', 'R2', 'R3', 'R4'], 'bases': ['U1', 'U2', 'V1'],
                  'pads': ['X', 'Y'] if pads is None else pads,
                  'groups': [group('A', 'u')] if groups is None else groups}
        return self.post('/proofs', fields, status=status)

    def issue(self, revision='r1', status=201):
        return self.post('/editions', {'revision': revision}, status=status)

    def handoff(self, edition, replica='R1', status=201):
        result = self.post('/handoffs', {'edition_id': edition['id'], 'replica_id': replica}, status=status)
        return result['ticket']['id'] if status == 201 else result

    def mount(self, handoff_id, base='U1', pad='X', status=201):
        return self.post('/mounts', {'handoff_id': handoff_id, 'base_id': base, 'pad_id': pad}, status=status)

    def remove(self, installation_id, reason='本轮撤下', status=201):
        return self.post('/removals', {'installation_id': installation_id, 'reason': reason}, status=status)

    def receipt(self, handoff_id):
        return self.get(f'/handoffs/{handoff_id}')


def group(back, slot, *banned):
    return {'back': back, 'slot': slot, 'banned_pads': list(banned)}
