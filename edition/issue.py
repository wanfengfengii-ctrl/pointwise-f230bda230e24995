from catalog.common import Conflict, NotFound, identifier, transaction
from edition.current import set_current_edition
from edition.snapshots import store_snapshot
from proof.coverage import evaluate_coverage
from proof.drafts import get_revision


class IssueConflict(Conflict):
    pass


def issue_edition(db, revision):
    identifier(revision, '待签修订号')
    with transaction(db):
        draft = get_revision(db, revision)
        if draft is None:
            raise NotFound(f'未知待签修订：{revision}')
        report = evaluate_coverage(db, draft)
        if not report.is_complete:
            missing = [f'{group["back"]}/{group["slot"]} 无可用垫片' for group in report.missing]
            detail = '；'.join(report.errors + missing) or '未登记必配组合'
            raise IssueConflict(f'覆盖不完整：{detail}')
        snapshot = store_snapshot(db, draft, report)
        set_current_edition(db, draft.exhibition, snapshot.id)
        return snapshot
