from tests.support import SiteCase, group


class TestEdition(SiteCase):
    def swap_editions(self):
        self.catalog()
        self.post('/parts/revise', {'kind': 'base', 'id': 'u', 'minimum': 10, 'maximum': 10}, status=200)
        self.draft()
        old = self.issue()
        self.post('/parts/revise', {'kind': 'pad', 'id': 'X', 'thickness': 3}, status=200)
        self.post('/parts/revise', {'kind': 'pad', 'id': 'Y', 'thickness': 2}, status=200)
        self.draft('r2', parent='r1')
        return old, self.issue('r2')

    def test_old_snapshot(self):
        old, new = self.swap_editions()
        self.reopen()
        old_read = self.get(f'/editions/{old["id"]}')
        new_read = self.get(f'/editions/{new["id"]}')
        self.assertEqual(['X'], old_read['groups'][0]['allowed_pads'])
        self.assertEqual(['Y'], new_read['groups'][0]['allowed_pads'])
        self.assertIn('正式版', self.get(f'/editions/{old["id"]}', html=True))

    def test_fixed_specs(self):
        old, new = self.swap_editions()
        self.reopen()
        for edition, expected in ((old, {'X': 2, 'Y': 3}), (new, {'X': 3, 'Y': 2})):
            read = self.get(f'/editions/{edition["id"]}')
            self.assertEqual(edition, read)
            self.assertEqual(expected, read['pads'])
            self.assertEqual({'A': 8, 'B': 8}, read['backings'])
            self.assertEqual({'slot': 'u', 'minimum': 10, 'maximum': 10}, read['slots']['u'])
        self.assertEqual(new, self.get('/editions/current', {'exhibition': 'river'}))

    def test_selected_revision(self):
        self.catalog()
        self.draft(groups=[group('A', 'u', 'Y')])
        self.draft('r2', parent='r1', groups=[group('A', 'u', 'X')])
        published = self.issue('r1')
        self.assertEqual('r1', published['revision'])
        self.assertEqual(['X'], published['groups'][0]['allowed_pads'])
        self.assertEqual(published, self.get('/editions/current', {'exhibition': 'river'}))
        self.assertEqual(['Y'], self.get('/proofs/r2')['coverage']['groups'][0]['allowed_pads'])

    def test_reject_missing_fit(self):
        self.catalog((('X', 2),))
        self.draft(pads=['X'])
        old = self.issue()
        rejected = self.draft('r2', parent='r1', pads=['X'], groups=[group('A', 'u', 'X')])
        self.assertEqual([{'back': 'A', 'slot': 'u'}], rejected['coverage']['missing'])
        self.assertIn('A/u', self.issue('r2', status=409)['error'])
        self.assertEqual(old, self.get('/editions/current', {'exhibition': 'river'}))
        self.assertEqual(rejected, self.get('/proofs/r2'))
        fixed = self.draft('r3', parent='r2', pads=['X'])
        self.assertTrue(fixed['coverage']['is_complete'])
        self.assertEqual('r3', self.issue('r3')['revision'])

    def test_all_groups(self):
        self.catalog((('X', 2),))
        first = self.draft(pads=['X'])
        old = self.issue()
        rejected = self.draft('r2', parent='r1', pads=['X'], groups=[group('A', 'u'), group('B', 'u', 'X')])
        self.assertEqual(['X'], rejected['coverage']['groups'][0]['allowed_pads'])
        self.assertEqual([], rejected['coverage']['groups'][1]['allowed_pads'])
        self.issue('r2', status=409)
        self.assertEqual(1, self.count('editions'))
        self.assertEqual(old, self.get('/editions/current', {'exhibition': 'river'}))
        self.assertEqual(first, self.get('/proofs/r1'))
        self.assertEqual(rejected, self.get('/proofs/r2'))
        self.get('/editions/999', status=404)
