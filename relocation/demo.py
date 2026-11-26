import json
from pathlib import Path
from tempfile import TemporaryDirectory

from dispatch.site import Application


def run_demo():
    with TemporaryDirectory(prefix='tour-relocation-demo-') as directory:
        db_path = Path(directory) / 'relocation.sqlite3'
        app = Application(db_path)

        def request(method, path, fields=None, *, allowed=(200, 201)):
            view = app.handle(method, path, fields)
            if view.status not in allowed:
                raise RuntimeError(f'{method} {path} -> {view.status}: {view.data}')
            return view.data, view.status

        def post(path, fields, *, allowed=(200, 201)):
            return request('POST', path, fields, allowed=allowed)[0]

        for replica_id in ('R1', 'R2', 'R3'):
            post('/parts', {'kind': 'replica', 'id': replica_id, 'back': 'A', 'thickness': 8})
        for base_id, slot, low, high in (
            ('U1', 'u', 10, 11), ('U2', 'u', 10, 11), ('V1', 'v', 11, 11),
            ('S', 'u', 10, 11), ('F', 'u', 10, 11),
        ):
            post('/parts', {'kind': 'base', 'id': base_id, 'slot': slot,
                            'minimum': low, 'maximum': high})
        for pad_id, thickness in (('X', 2), ('Y', 3)):
            post('/parts', {'kind': 'pad', 'id': pad_id, 'thickness': thickness})

        groups = [
            {'back': 'A', 'slot': 'u', 'banned_pads': ['Y'], 'reason': ''},
            {'back': 'A', 'slot': 'v', 'banned_pads': [], 'reason': ''},
        ]
        post('/proofs', {
            'exhibition': 'river', 'revision': 'r1', 'parent': None,
            'replicas': ['R1', 'R2', 'R3'], 'bases': ['U1', 'U2', 'V1', 'S', 'F'],
            'pads': ['X', 'Y'], 'groups': groups,
        })
        old_edition = post('/editions', {'revision': 'r1'})

        handoffs = {}
        for replica_id in ('R1', 'R2', 'R3'):
            receipt = post('/handoffs', {'edition_id': old_edition['id'], 'replica_id': replica_id})
            handoffs[replica_id] = receipt['ticket']['id']

        mount1 = post('/mounts', {'handoff_id': handoffs['R1'], 'base_id': 'U1', 'pad_id': 'X'})
        mount2 = post('/mounts', {'handoff_id': handoffs['R2'], 'base_id': 'U2', 'pad_id': 'X'})
        installation1 = mount1['id']
        installation2 = mount2['id']

        post('/parts/revise', {'kind': 'base', 'id': 'v', 'minimum': 10, 'maximum': 11},
             allowed=(200,))
        post('/proofs', {
            'exhibition': 'river', 'revision': 'r2', 'parent': 'r1',
            'replicas': ['R1', 'R2', 'R3'], 'bases': ['U1', 'U2', 'V1', 'S', 'F'],
            'pads': ['X', 'Y'],
            'groups': [
                {'back': 'A', 'slot': 'u', 'banned_pads': ['X'], 'reason': ''},
                {'back': 'A', 'slot': 'v', 'banned_pads': ['Y'], 'reason': ''},
            ],
        })
        post('/editions', {'revision': 'r2'})

        before = post('/closeouts', {'exhibition': 'river'})
        targets = [
            {'installation_id': installation1, 'base_id': 'U2'},
            {'installation_id': installation2, 'base_id': 'U1'},
        ]
        no_buffer, no_buffer_status = request('POST', '/relocations', {
            'exhibition': 'river', 'targets': targets, 'buffers': [],
        }, allowed=(409,))
        v_buffer, v_status = request('POST', '/relocations', {
            'exhibition': 'river', 'targets': targets, 'buffers': ['V1'],
        }, allowed=(409,))

        plan = post('/relocations', {
            'exhibition': 'river', 'targets': targets, 'buffers': ['S'],
        }, allowed=(201,))
        plan_id = plan['id']

        occupied_buffer, occupied_status = request('POST', '/mounts', {
            'handoff_id': handoffs['R3'], 'base_id': 'S', 'pad_id': 'X',
        }, allowed=(409,))
        outside = post('/mounts', {
            'handoff_id': handoffs['R3'], 'base_id': 'F', 'pad_id': 'X',
        })

        first_move = plan['next_move']
        first_confirmed = post(f'/relocations/{plan_id}/moves', first_move, allowed=(201,))
        mid = post('/closeouts', {'exhibition': 'river'})

        # Reopen the same database: continuation must use confirmed occupancy.
        app = Application(db_path)
        stale, stale_status = request('POST', f'/relocations/{plan_id}/moves', first_move,
                                      allowed=(409,))

        current = request('GET', f'/relocations/{plan_id}')[0]
        confirmed_steps = [first_confirmed['moves'][-1]]
        while current['state'] == 'active':
            current = post(f'/relocations/{plan_id}/moves', current['next_move'],
                           allowed=(201,))
            confirmed_steps.append(current['moves'][-1])
        final_plan = current

        completed_closeout = post('/closeouts', {'exhibition': 'river'})
        receipt1 = request('GET', f'/handoffs/{handoffs["R1"]}')[0]
        receipt2 = request('GET', f'/handoffs/{handoffs["R2"]}')[0]

        removal1 = post('/removals', {'installation_id': installation1, 'reason': '互换完成，按U2撤装'})
        removal2 = post('/removals', {'installation_id': installation2, 'reason': '互换完成，按U1撤装'})
        removed_receipt1 = request('GET', f'/handoffs/{handoffs["R1"]}')[0]
        removed_receipt2 = request('GET', f'/handoffs/{handoffs["R2"]}')[0]
        after_removal_closeout = post('/closeouts', {'exhibition': 'river'})

        summary = {
            'case_id': 'RELOCATION-SWAP',
            'plan_id': plan_id,
            'rejected_without_buffer_status': no_buffer_status,
            'rejected_v_buffer_status': v_status,
            'buffer_occupancy_conflict_status': occupied_status,
            'stale_confirmation_status': stale_status,
            'outside_installation_id': outside['id'],
            'confirmed_steps': confirmed_steps,
            'final_positions': final_plan['positions'],
            'removals': [removal1['id'], removal2['id']],
        }
        print('POINTWISE_RELOCATION_DEMO ' + json.dumps(summary, ensure_ascii=False, sort_keys=True))
        print(json.dumps({
            'plan': final_plan,
            'initial_closeout_id': before['id'],
            'mid_closeout_id': mid['id'],
            'completed_closeout': completed_closeout,
            'receipts': [receipt1, receipt2],
            'removed_receipts': [removed_receipt1, removed_receipt2],
            'after_removal_closeout_id': after_removal_closeout['id'],
            'rejections': {
                'without_buffer': no_buffer,
                'v_buffer': v_buffer,
                'occupied_buffer': occupied_buffer,
                'stale': stale,
            },
        }, ensure_ascii=False, sort_keys=True))
