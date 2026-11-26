from relocation_fixture import prepare
from tests.support import Forms, SiteCase


class RelocationFlowTest(SiteCase):
    def setUp(self):
        super().setUp()
        self.fixture = prepare(self)
        self.i1 = self.fixture['installations']['R1']['id']
        self.i2 = self.fixture['installations']['R2']['id']
        self.r3 = self.fixture['handoffs']['R3']
        self.targets = [
            {'installation_id': self.i1, 'base_id': 'U2'},
            {'installation_id': self.i2, 'base_id': 'U1'},
        ]

    def checkout(self, buffers=('S',), status=201):
        return self.post('/relocations', {
            'exhibition': 'river', 'targets': self.targets, 'buffers': list(buffers),
        }, status=status)

    def complete(self, plan_id):
        plan = self.get(f'/relocations/{plan_id}')
        for _ in range(10):
            if plan['state'] == 'completed':
                return plan
            move = plan['next_move']
            self.assertIsNotNone(move)
            plan = self.post(f'/relocations/{plan_id}/moves', move)
        self.fail('relocation did not complete')

    def test_checkout_requires_route_and_protects_plan(self):
        before = self.post('/closeouts', {'exhibition': 'river'})
        initial = [('U1', self.i1), ('U2', self.i2)]
        for buffers in ((), ('V1',)):
            self.checkout(buffers, status=409)
            self.assertEqual(0, self.count('relocations'))
            self.assertEqual(initial, self.rows(
                'SELECT base_id, installation_id FROM base_occupancy ORDER BY base_id'))

        plan = self.checkout(['S'])
        plan_id = plan['id']
        self.checkout(['S'], status=409)
        self.assertEqual(1, self.count('relocations'))
        self.assertEqual('active', plan['state'])
        self.assertEqual([
            {'installation_id': self.i1, 'base_id': 'U1', 'target_base_id': 'U2'},
            {'installation_id': self.i2, 'base_id': 'U2', 'target_base_id': 'U1'},
        ], plan['positions'])
        self.assertEqual([], plan['moves'])
        first = {'step': 1, 'installation_id': self.i1,
                 'from_base_id': 'U1', 'to_base_id': 'S'}
        self.assertEqual(first, plan['next_move'])
        self.assertEqual(initial, self.rows(
            'SELECT base_id, installation_id FROM base_occupancy ORDER BY base_id'))

        self.mount(self.r3, base='S', status=409)
        self.post('/parts/availability',
                  {'kind': 'base', 'id': 'S', 'active': False}, status=409)
        self.assertEqual(1, self.rows('SELECT active FROM bases WHERE id = ?', ('S',))[0][0])
        self.remove(self.i1, status=409)
        self.remove(self.i2, status=409)
        self.assertEqual(initial, self.rows(
            'SELECT base_id, installation_id FROM base_occupancy ORDER BY base_id'))

        outside = self.mount(self.r3, base='F')
        self.assertEqual(('F', outside['id']), self.rows(
            'SELECT base_id, installation_id FROM base_occupancy WHERE base_id = ?', ('F',))[0])
        self.assertEqual(before, self.get(f"/closeouts/{before['id']}"))

        page = self.get(f'/relocations/{plan_id}', html=True)
        form = Forms(page).get(f'/relocations/{plan_id}/moves', 'post')
        self.assertEqual({key: str(value) for key, value in first.items()}, form['inputs'])
        self.post(f'/relocations/{plan_id}/moves', form['inputs'], form=True, html=True)

        moved = self.get(f'/relocations/{plan_id}')
        self.assertEqual([first], moved['moves'])
        self.assertEqual({
            'step': 2, 'installation_id': self.i2,
            'from_base_id': 'U2', 'to_base_id': 'U1',
        }, moved['next_move'])
        occupancy = self.rows('SELECT base_id, installation_id FROM base_occupancy ORDER BY base_id')
        self.assertEqual([('F', outside['id']), ('S', self.i1), ('U2', self.i2)], occupancy)

        mid = self.post('/closeouts', {'exhibition': 'river'})
        mounted = {row['installation']['id']: row for row in mid['categories']['mounted']
                   if row['installation']}
        self.assertEqual('S', mounted[self.i1]['actual_base_id'])
        self.assertEqual('mounted', mounted[self.i1]['state'])
        self.assertEqual(1, len(mounted[self.i1]['moves']))

        self.reopen()
        self.post(f'/relocations/{plan_id}/moves', first, status=409)
        after_stale = self.get(f'/relocations/{plan_id}')
        self.assertEqual(1, len(after_stale['moves']))

        plan = self.complete(plan_id)
        self.assertEqual('completed', plan['state'])
        self.assertIsNone(plan['next_move'])
        self.assertEqual(3, len(plan['moves']))
        self.assertEqual([
            {'step': 1, 'installation_id': self.i1, 'from_base_id': 'U1', 'to_base_id': 'S'},
            {'step': 2, 'installation_id': self.i2, 'from_base_id': 'U2', 'to_base_id': 'U1'},
            {'step': 3, 'installation_id': self.i1, 'from_base_id': 'S', 'to_base_id': 'U2'},
        ], plan['moves'])
        self.assertEqual([
            {'installation_id': self.i1, 'base_id': 'U2', 'target_base_id': 'U2'},
            {'installation_id': self.i2, 'base_id': 'U1', 'target_base_id': 'U1'},
        ], plan['positions'])
        self.assertEqual(plan, self.get(f'/relocations/{plan_id}'))
        completed_page = self.get(f'/relocations/{plan_id}', html=True)
        self.assertIn('全部目标已经确认完成', completed_page)
        self.assertIn('已确认实移', completed_page)

        final_closeout = self.post('/closeouts', {'exhibition': 'river'})
        closeout_page = self.get(f"/closeouts/{final_closeout['id']}", html=True)
        self.assertIn('实际/末落点', closeout_page)
        self.assertIn(f'计划{plan_id}第1步', closeout_page)
        self.assertEqual(before, self.get(f"/closeouts/{before['id']}"))
        self.assertEqual(mid, self.get(f"/closeouts/{mid['id']}"))

        r1_handoff = self.fixture['handoffs']['R1']
        r2_handoff = self.fixture['handoffs']['R2']
        receipt1 = self.receipt(r1_handoff)
        receipt2 = self.receipt(r2_handoff)
        self.assertEqual('U1', receipt1['installation']['base_id'])
        self.assertEqual('U2', receipt1['actual_base_id'])
        self.assertEqual([
            {'relocation_id': plan_id, 'step': 1, 'installation_id': self.i1,
             'from_base_id': 'U1', 'to_base_id': 'S'},
            {'relocation_id': plan_id, 'step': 3, 'installation_id': self.i1,
             'from_base_id': 'S', 'to_base_id': 'U2'},
        ], receipt1['moves'])
        receipt_page = self.get(f'/handoffs/{r1_handoff}', html=True)
        self.assertIn('当前/撤装前最后实际落点', receipt_page)
        self.assertIn('U2', receipt_page)
        self.assertEqual('U2', receipt2['installation']['base_id'])
        self.assertEqual('U1', receipt2['actual_base_id'])
        self.assertEqual([
            {'relocation_id': plan_id, 'step': 2, 'installation_id': self.i2,
             'from_base_id': 'U2', 'to_base_id': 'U1'},
        ], receipt2['moves'])
        self.assertEqual(final_closeout['categories']['mounted'],
                         [self.receipt(row['ticket']['id'])
                          for row in final_closeout['categories']['mounted']])

        self.remove(self.i1)
        self.remove(self.i2)
        self.assertEqual([], self.rows(
            "SELECT base_id FROM base_occupancy WHERE base_id IN ('U1', 'U2') ORDER BY base_id"))
        removed1 = self.receipt(r1_handoff)
        removed2 = self.receipt(r2_handoff)
        self.assertEqual('removed', removed1['state'])
        self.assertEqual('U2', removed1['actual_base_id'])
        self.assertEqual('removed', removed2['state'])
        self.assertEqual('U1', removed2['actual_base_id'])
        self.assertEqual(2, len(removed1['moves']))

    def test_second_buffer_permits_ordinary_occupancy_and_reroutes(self):
        self.post('/parts', {'kind': 'base', 'id': 'W', 'slot': 'u',
                             'minimum': 10, 'maximum': 11})
        i1 = self.i1
        i2 = self.i2
        r3 = self.r3
        plan = self.post('/relocations', {
            'exhibition': 'river',
            'targets': [
                {'installation_id': i1, 'base_id': 'U2'},
                {'installation_id': i2, 'base_id': 'U1'},
            ],
            'buffers': ['S', 'W'],
        })
        self.assertEqual('S', plan['next_move']['to_base_id'])

        self.mount(r3, base='S')
        changed = self.get(f"/relocations/{plan['id']}")
        self.assertEqual('W', changed['next_move']['to_base_id'])
        self.post(f"/relocations/{plan['id']}/moves", plan['next_move'], status=409)

        completed = self.complete(plan['id'])
        self.assertEqual(3, len(completed['moves']))
        self.assertEqual(['W', 'U1', 'U2'], [move['to_base_id'] for move in completed['moves']])

    def test_browser_checkout_form_and_conflict_link(self):
        page = self.get('/relocations', html=True)
        form = Forms(page).get('/relocations', 'post')
        html = self.post('/relocations', {
            **form['inputs'],
            'exhibition': 'river',
            'targets': f'{self.i1},U2\n{self.i2},U1\n',
            'buffers': 'S',
        }, form=True, html=True)
        plan_id = self.rows('SELECT id FROM relocations')[0][0]
        self.assertIn(f'/relocations/{plan_id}/moves', html)

        plan = self.get(f'/relocations/{plan_id}')
        stale = dict(plan['next_move'], step=99)
        conflict_html = self.post(f'/relocations/{plan_id}/moves', stale,
                                  status=409, form=True, html=True)
        self.assertIn(f'href="/relocations/{plan_id}"', conflict_html)

    def test_unneeded_or_outside_bases_can_change(self):
        self.post('/parts', {'kind': 'base', 'id': 'W', 'slot': 'u',
                             'minimum': 10, 'maximum': 11})
        plan = self.checkout(['S', 'W'])
        self.post('/parts/availability',
                  {'kind': 'base', 'id': 'S', 'active': False}, status=200)
        changed = self.get(f"/relocations/{plan['id']}")
        self.assertEqual('W', changed['next_move']['to_base_id'])
        self.post('/parts/availability',
                  {'kind': 'base', 'id': 'F', 'active': False}, status=200)
        completed = self.complete(plan['id'])
        self.assertEqual(['W', 'U1', 'U2'], [m['to_base_id'] for m in completed['moves']])

    def test_can_checkout_again_after_completion(self):
        first = self.checkout(['S'])
        completed = self.complete(first['id'])
        self.assertEqual('completed', completed['state'])
        reverse = self.post('/relocations', {
            'exhibition': 'river',
            'targets': [
                {'installation_id': self.i1, 'base_id': 'U1'},
                {'installation_id': self.i2, 'base_id': 'U2'},
            ],
            'buffers': ['S'],
        })
        self.assertEqual(2, reverse['id'])
        done = self.complete(reverse['id'])
        self.assertEqual('completed', done['state'])
        receipt1 = self.receipt(self.fixture['handoffs']['R1'])
        self.assertEqual('U1', receipt1['actual_base_id'])
        self.assertEqual(4, len(receipt1['moves']))
        self.assertEqual([1, 1, 2, 2], [move['relocation_id'] for move in receipt1['moves']])

    def test_unknown_and_malformed_relocation_records(self):
        self.get('/relocations/999', status=404)
        self.post('/relocations/999/moves', {
            'step': 1, 'installation_id': self.i1,
            'from_base_id': 'U1', 'to_base_id': 'S',
        }, status=404)
        plan = self.checkout(['S'])
        self.post(f"/relocations/{plan['id']}/moves", {
            'step': 'bad', 'installation_id': self.i1,
            'from_base_id': 'U1', 'to_base_id': 'S',
        }, status=422)
        self.post(f"/relocations/{plan['id']}/moves", {
            'step': 1, 'installation_id': self.i1, 'from_base_id': 'U1',
        }, status=422)
        self.post('/relocations', {
            'exhibition': 'river', 'targets': 'bad-target-line', 'buffers': ['S'],
        }, status=422)
        self.post('/relocations', {
            'exhibition': 'river',
            'targets': [{'installation_id': self.i1, 'base_id': 'U1'}],
            'buffers': [],
        }, status=409)
        self.post('/relocations', {
            'exhibition': 'river',
            'targets': [self.targets[0], self.targets[0]],
            'buffers': ['S'],
        }, status=422)
