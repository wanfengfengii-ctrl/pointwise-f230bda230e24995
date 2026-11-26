from dataclasses import asdict, dataclass

from catalog.bases import get_base, get_slot_spec
from catalog.pads import get_pad
from catalog.replicas import get_backing_spec, get_replica
from proof.fit import allowed_pads


@dataclass(frozen=True)
class CoverageReport:
    replicas: dict
    bases: dict
    backings: dict
    slots: dict
    pads: dict
    groups: list
    missing: list
    errors: list

    @property
    def is_complete(self):
        return bool(self.groups) and not self.missing and not self.errors


def evaluate_coverage(db, draft):
    replicas = {}
    backings = {}
    bases = {}
    slots = {}
    pads = {}
    errors = []
    for replica_id in draft.replicas:
        replica = get_replica(db, replica_id)
        if replica is None or not replica.active:
            errors.append(f'复制件未登记或已停用：{replica_id}')
            continue
        backing = get_backing_spec(db, replica.back)
        if backing is None:
            errors.append(f'缺背板规格：{replica.back}')
            continue
        replicas[replica_id] = replica.back
        backings[replica.back] = backing
    for base_id in draft.bases:
        base = get_base(db, base_id)
        if base is None or not base.active:
            errors.append(f'底座未登记或已停用：{base_id}')
            continue
        slot = get_slot_spec(db, base.slot)
        if slot is None:
            errors.append(f'缺槽深规格：{base.slot}')
            continue
        bases[base_id] = base.slot
        slots[base.slot] = asdict(slot)
    for pad_id in draft.pads:
        pad = get_pad(db, pad_id)
        if pad is None or not pad.active:
            errors.append(f'垫片未登记或已停用：{pad_id}')
        else:
            pads[pad_id] = pad.thickness

    groups = []
    missing = []
    for group in draft.groups:
        back = group['back']
        slot = group['slot']
        banned = group['banned_pads']
        if back not in backings:
            errors.append(f'必配组缺可用背标：{back}/{slot}')
        if slot not in slots:
            errors.append(f'必配组缺可用槽标：{back}/{slot}')
        for pad_id in sorted(set(banned) - pads.keys()):
            errors.append(f'{back}/{slot} 的禁配垫片不在可用候选内：{pad_id}')
        options = []
        if back in backings and slot in slots:
            spec = slots[slot]
            options = allowed_pads(backings[back], spec['minimum'], spec['maximum'], pads, banned)
        groups.append({**group, 'allowed_pads': options})
        if not options:
            missing.append({'back': back, 'slot': slot})
    return CoverageReport(replicas, bases, backings, slots, pads, groups, missing, errors)
