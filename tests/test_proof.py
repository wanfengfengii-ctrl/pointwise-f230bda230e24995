from contextlib import closing

from catalog.seed import load_sample
from dispatch.site import open_database
from tests.support import Forms, SiteCase, group


class TestProof(SiteCase):
    def test_exact_fit_boundaries(self):
        self.catalog((('P1', 1), ('P2', 2), ('P3', 3), ('P4', 4)))
        proof = self.draft(pads=['P1', 'P2', 'P3', 'P4'])
        self.assertEqual(['P2', 'P3'], proof['coverage']['groups'][0]['allowed_pads'])
        self.assertEqual([], proof['coverage']['missing'])
        edition = self.issue()
        self.assertEqual(['P2', 'P3'], edition['groups'][0]['allowed_pads'])
        handoff_id = self.handoff(edition)
        self.assertEqual(['P2', 'P3'], self.get('/mounts', {'handoff_id': handoff_id,
                                                            'base_id': 'U1'})['allowed_pads'])
        self.mount(handoff_id, pad='P4', status=409)
        installed = self.mount(handoff_id, pad='P3')
        self.assertEqual('P3', self.receipt(handoff_id)['installation']['pad_id'])
        self.assertEqual(installed['id'], self.rows('SELECT installation_id FROM base_occupancy')[0][0])

    def test_pad_order(self):
        self.catalog((('Z', 2), ('A2', 3)))
        result = self.draft(pads=['Z', 'A2'])
        self.assertEqual(['A2', 'Z'], result['coverage']['groups'][0]['allowed_pads'])
        self.assertIn('A2, Z', self.get('/proofs/r1', html=True))

    def test_invalid_and_missing_spec(self):
        self.catalog()
        count = self.count('pads')
        bad = self.post('/parts', {'kind': 'pad', 'id': 'bad', 'thickness': -1}, status=422)
        self.assertIn('厚度', bad['error'])
        for value in (None, 1.5, True):
            self.post('/parts', {'kind': 'pad', 'id': 'bad', 'thickness': value}, status=422)
        error = self.draft(pads=['X', 'missing'], status=422)
        self.assertIn('missing', error['error'])
        self.assertEqual(count, self.count('pads'))
        self.assertEqual(0, self.count('drafts'))
        self.assertEqual(0, self.count('exhibitions'))

    def test_part_conflict(self):
        self.catalog()
        for fields in (
            {'kind': 'replica', 'id': 'R1', 'back': 'A', 'thickness': 9},
            {'kind': 'base', 'id': 'U1', 'slot': 'u', 'minimum': 9, 'maximum': 11},
            {'kind': 'pad', 'id': 'X', 'thickness': 7},
        ):
            self.post('/parts', fields, status=409)
        catalog = self.get('/parts')
        self.assertEqual(8, catalog['replicas'][0]['thickness'])
        self.assertEqual(10, catalog['bases'][0]['minimum'])
        self.assertEqual(2, catalog['pads'][0]['thickness'])

    def test_stale_draft(self):
        self.catalog()
        first = self.draft()
        second = self.draft('r2', parent='r1', groups=[group('A', 'u', 'Y')])
        self.draft('r3', parent='r1', groups=[group('A', 'u', 'X')], status=409)
        self.assertEqual(first, self.get('/proofs/r1'))
        self.assertEqual(second, self.get('/proofs/r2'))
        self.assertEqual(2, self.count('drafts'))
        self.get('/proofs/r3', status=404)
        diff = self.get('/proofs/r2/diff', {'against': 'r1'})
        self.assertEqual(['X', 'Y'], diff['groups'][0]['before']['allowed_pads'])
        self.assertEqual(['X'], diff['groups'][0]['after']['allowed_pads'])

    def test_inactive_reference(self):
        self.catalog()
        self.draft()
        self.post('/parts/availability', {'kind': 'pad', 'id': 'Y', 'active': False}, status=200)
        self.draft('r2', parent='r1', status=422)
        self.assertEqual(1, self.count('drafts'))
        self.assertEqual('r1', self.get('/proofs/r1')['draft']['revision'])
        self.assertIn('Y', ' '.join(self.get('/proofs/r1')['coverage']['errors']))
        self.get('/proofs/r2', status=404)

    def test_seed_preserves_edits(self):
        with closing(open_database(self.path)) as db:
            first = load_sample(db)
        self.assertTrue(first['loaded'])
        self.post('/parts/revise', {'kind': 'pad', 'id': 'X', 'thickness': 4}, status=200)
        self.post('/parts/availability', {'kind': 'replica', 'id': 'R3', 'active': False}, status=200)
        counts = {name: self.count(name) for name in ('replicas', 'pads', 'bases', 'drafts', 'sample_versions')}
        draft = self.get('/proofs/river-1')['draft']
        self.reopen()
        with closing(open_database(self.path)) as db:
            rerun = load_sample(db)
        self.assertEqual({'version': first['version'], 'loaded': False}, rerun)
        updated = self.get('/parts')
        self.assertEqual(4, next(row['thickness'] for row in updated['pads'] if row['id'] == 'X'))
        self.assertFalse(next(row['active'] for row in updated['replicas'] if row['id'] == 'R3'))
        self.assertEqual(counts, {name: self.count(name) for name in counts})
        self.assertEqual(draft, self.get('/proofs/river-1')['draft'])

    def test_curator_proof_form(self):
        self.catalog()
        editor = Forms(self.get('/proofs', html=True)).get('/proofs', 'post')
        record = {**editor['inputs'], 'exhibition': 'river', 'revision': 'r1', 'replicas': 'R1',
                  'bases': 'U1', 'pads': 'X,Y', 'groups': 'A,u,Y,统一高度'}
        report = self.post('/proofs', record, form=True, html=True)
        self.assertIn('统一高度', report)
        issue = Forms(report).get('/editions', 'post')
        self.post('/editions', issue['inputs'], form=True, html=True)
        self.assertEqual(['X'], self.get('/editions/current', {'exhibition': 'river'})['groups'][0]['allowed_pads'])
