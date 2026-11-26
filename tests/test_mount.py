from tests.support import Forms, SiteCase, group


class TestMount(SiteCase):
    def setUp(self):
        super().setUp()
        self.catalog()

    def issue_one(self, groups=None):
        self.draft(groups=groups)
        return self.issue()

    def test_handoff_to_mount(self):
        edition = self.issue_one([group('A', 'u', 'Y')])
        handoff_page = self.get('/handoffs', {'edition_id': edition['id']}, html=True)
        dispatch_fields = Forms(handoff_page).get('/handoffs', 'post')
        self.assertIn('R1', dispatch_fields['options']['replica_id'])
        html = self.post('/handoffs', {**dispatch_fields['inputs'], 'replica_id': 'R1'}, form=True, html=True)
        handoff_id = self.rows('SELECT id FROM handoffs')[0][0]
        self.assertIn(f'交接 {handoff_id}', html)
        start_page = self.get('/mounts', {'handoff_id': handoff_id}, html=True)
        self.assertIn('背标 A', start_page)
        start_fields = Forms(start_page).get('/mounts', 'get')
        choices = self.get('/mounts', {**start_fields['inputs'], 'base_id': 'U1'}, html=True)
        install_form = Forms(choices).get('/mounts', 'post')
        self.assertEqual(['X'], install_form['options']['pad_id'])
        self.post('/mounts', {**install_form['inputs'], 'pad_id': 'X'}, form=True, html=True)
        receipt = self.receipt(handoff_id)
        self.assertEqual('mounted', receipt['state'])
        self.assertEqual(edition['id'], receipt['ticket']['edition_id'])
        self.assertEqual(handoff_id, receipt['installation']['handoff_id'])
        self.assertEqual(('U1', 'u', 'X'), tuple(receipt['installation'][key] for key in ('base_id', 'slot', 'pad_id')))
        self.assertIn(f'/editions/{edition["id"]}', self.get(f'/handoffs/{handoff_id}', html=True))

    def test_pinned_handoff(self):
        old = self.issue_one([group('A', 'u', 'Y')])
        handoff = self.handoff(old)
        old_form = Forms(self.get('/mounts', {'handoff_id': handoff, 'base_id': 'U1'}, html=True)).get('/mounts', 'post')
        self.draft('r2', parent='r1', groups=[group('A', 'u', 'X')])
        new = self.issue('r2')
        self.assertEqual(['Y'], new['groups'][0]['allowed_pads'])
        self.assertEqual(['X'], self.get(f'/editions/{old["id"]}')['groups'][0]['allowed_pads'])
        new_ticket = self.handoff(new, 'R2')
        self.assertEqual(['Y'], self.get('/mounts', {'handoff_id': new_ticket, 'base_id': 'U1'})['allowed_pads'])
        opened = self.get('/mounts', {'handoff_id': handoff, 'base_id': 'U1'}, html=True)
        self.assertEqual(['X'], Forms(opened).get('/mounts', 'post')['options']['pad_id'])
        self.post('/mounts', {**old_form['inputs'], 'pad_id': 'Y'}, form=True, status=409)
        self.assertEqual(0, self.count('installations'))
        self.assertEqual(0, self.count('base_occupancy'))
        self.post('/mounts', {**old_form['inputs'], 'pad_id': 'X'}, form=True, html=True)
        self.reopen()
        receipt = self.receipt(handoff)
        self.assertEqual(old['id'], receipt['ticket']['edition_id'])
        self.assertEqual('X', receipt['installation']['pad_id'])
        self.assertEqual('U1', receipt['installation']['base_id'])

    def test_actual_slot(self):
        edition = self.issue_one([group('A', 'u', 'Y'), group('A', 'v')])
        ticket = self.handoff(edition)
        self.assertEqual(['X'], self.get('/mounts', {'handoff_id': ticket, 'base_id': 'U1'})['allowed_pads'])
        self.assertEqual(['Y'], self.get('/mounts', {'handoff_id': ticket, 'base_id': 'V1'})['allowed_pads'])
        self.mount(ticket, base='V1', pad='X', status=409)
        self.assertEqual(0, self.count('installations'))
        self.assertEqual('v', self.mount(ticket, base='V1', pad='Y')['slot'])

    def test_single_install(self):
        first = self.handoff(self.issue_one())
        installed = self.mount(first)
        self.mount(first, base='U2', status=409)
        self.assertEqual(installed, self.receipt(first)['installation'])
        self.assertEqual([('U1', installed['id'])], self.rows('SELECT * FROM base_occupancy'))
        self.assertEqual(1, self.count('installations'))

    def test_occupied_base(self):
        edition = self.issue_one()
        first = self.handoff(edition)
        second = self.handoff(edition, 'R2')
        installed = self.mount(first)
        self.mount(second, status=409)
        self.assertEqual(1, self.count('installations'))
        self.assertEqual([('U1', installed['id'])], self.rows('SELECT * FROM base_occupancy'))
        self.assertEqual(installed, self.receipt(first)['installation'])
        self.assertEqual('pending', self.receipt(second)['state'])
        self.assertIsNone(self.receipt(second)['installation'])

    def test_duplicate_handoff(self):
        old = self.issue_one()
        first = self.handoff(old)
        self.draft('r2', parent='r1')
        self.handoff(self.issue('r2'), status=409)
        self.assertEqual(1, self.count('handoffs'))
        self.assertEqual(old['id'], self.receipt(first)['ticket']['edition_id'])
        self.assertEqual('pending', self.receipt(first)['state'])

    def test_unknown_handoff(self):
        edition = self.issue_one()
        installed = self.mount(self.handoff(edition))
        before = self.rows('SELECT * FROM base_occupancy')
        self.get('/handoffs/999', status=404)
        self.get('/mounts', {'handoff_id': 999, 'base_id': 'U2'}, status=404, html=True)
        self.mount(999, base='U2', status=404)
        self.assertEqual(1, self.count('installations'))
        self.assertEqual([('U1', installed['id'])], before)
        self.assertEqual(before, self.rows('SELECT * FROM base_occupancy'))
