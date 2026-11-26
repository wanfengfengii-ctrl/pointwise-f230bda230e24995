from tests.support import Forms, SiteCase, group


class TestAudit(SiteCase):
    def setUp(self):
        super().setUp()
        self.catalog()
        self.draft(groups=[group('A', 'u'), group('B', 'u')])
        self.edition = self.issue()

    def closeout(self, exhibition='river', status=201):
        return self.post('/closeouts', {'exhibition': exhibition}, status=status)

    def three_states(self):
        removed = self.handoff(self.edition, 'R1')
        installation = self.mount(removed)
        page = self.get('/removals', {'installation_id': installation['id']}, html=True)
        form = Forms(page).get('/removals', 'post')
        self.post('/removals', {**form['inputs'], 'reason': '取下运回'}, form=True, html=True)
        mounted = self.handoff(self.edition, 'R2')
        self.mount(mounted, base='U2')
        pending = self.handoff(self.edition, 'R3')
        return removed, mounted, pending

    def test_removal_and_closeout(self):
        removed, mounted, pending = self.three_states()
        self.assertEqual([('U2',)], self.rows('SELECT base_id FROM base_occupancy'))
        page = self.get('/closeouts', html=True)
        fields = Forms(page).get('/closeouts', 'post')['inputs']
        self.post('/closeouts', {**fields, 'exhibition': 'river'}, form=True, html=True)
        number = self.rows('SELECT id FROM closeouts')[0][0]
        snapshot = self.get(f'/closeouts/{number}')
        self.assertEqual([removed], self.ids(snapshot, 'removed'))
        self.assertEqual([mounted], self.ids(snapshot, 'mounted'))
        self.assertEqual([pending], self.ids(snapshot, 'pending'))
        self.reopen()
        self.assertEqual(snapshot, self.get(f'/closeouts/{number}'))
        self.assertEqual('取下运回', self.receipt(removed)['removal']['reason'])

    def test_release_and_reuse(self):
        first = self.handoff(self.edition)
        old_install = self.mount(first)
        removal = self.remove(old_install['id'])
        self.assertEqual([], self.rows('SELECT * FROM base_occupancy'))
        second = self.handoff(self.edition, 'R1')
        new_install = self.mount(second, pad='Y')
        self.assertEqual([('U1', new_install['id'])], self.rows('SELECT * FROM base_occupancy'))
        self.assertEqual(old_install, self.receipt(first)['installation'])
        self.assertEqual(removal, self.receipt(first)['removal'])
        self.assertTrue(self.receipt(first)['ticket']['ended'])
        self.assertEqual(new_install, self.receipt(second)['installation'])

    def test_invalid_removal(self):
        first = self.handoff(self.edition)
        installation = self.mount(first)
        self.remove(999, status=404)
        self.assertEqual([('U1', installation['id'])], self.rows('SELECT * FROM base_occupancy'))
        old_removal = self.remove(installation['id'])
        second = self.handoff(self.edition, 'R2')
        new_installation = self.mount(second)
        self.remove(installation['id'], reason='不应重写', status=409)
        self.assertEqual([('U1', new_installation['id'])], self.rows('SELECT * FROM base_occupancy'))
        self.assertEqual(1, self.count('removals'))
        self.assertEqual(old_removal, self.receipt(first)['removal'])
        self.assertEqual('mounted', self.receipt(second)['state'])

    def test_all_ticket_states(self):
        removed, mounted, pending = self.three_states()
        first = self.closeout()
        seen = [ticket for section in ('removed', 'mounted', 'pending') for ticket in self.ids(first, section)]
        self.assertEqual([removed, mounted, pending], seen)
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(self.receipt(removed), first['categories']['removed'][0])
        self.assertEqual(self.receipt(mounted), first['categories']['mounted'][0])
        self.assertEqual(self.receipt(pending), first['categories']['pending'][0])

    def test_immutable_closeout(self):
        removed, mounted, pending = self.three_states()
        before = self.closeout()
        new_mount = self.mount(pending)
        self.remove(self.receipt(mounted)['installation']['id'])
        self.reopen()
        old_path = f'/closeouts/{before["id"]}'
        self.assertEqual(before, self.get(old_path))
        self.assertIn('未装（1）', self.get(old_path, html=True))
        after = self.closeout()
        self.assertEqual([], self.ids(after, 'pending'))
        self.assertEqual([pending], self.ids(after, 'mounted'))
        self.assertEqual([removed, mounted], self.ids(after, 'removed'))
        self.assertEqual(new_mount, after['categories']['mounted'][0]['installation'])

    def test_exhibition_scope(self):
        river_id = self.handoff(self.edition)
        self.draft('empty-1', exhibition='empty')
        self.assertEqual({'pending': [], 'mounted': [], 'removed': []}, self.closeout('empty')['categories'])
        self.draft('coast-1', exhibition='coast', groups=[group('B', 'u')])
        other = self.handoff(self.issue('coast-1'), 'R4')
        self.assertEqual([river_id], self.ids(self.closeout(), 'pending'))
        self.assertEqual([other], self.ids(self.closeout('coast'), 'pending'))
        count = self.count('closeouts')
        self.closeout('unknown', status=404)
        self.get('/closeouts/999', status=404)
        self.assertEqual(count, self.count('closeouts'))

    @staticmethod
    def ids(snapshot, section):
        return [entry['ticket']['id'] for entry in snapshot['categories'][section]]
