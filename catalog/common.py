import re
from contextlib import contextmanager


class Conflict(ValueError):
    pass


class NotFound(LookupError):
    pass


class PartConflict(Conflict):
    pass


def identifier(value, field):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', value):
        raise ValueError(f'{field} 须为有效编号')
    return value


def millimetres(value, field):
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError(f'{field} 须为非负整数毫米')
    return value


def record_id(value):
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,19}', value):
        value = int(value)
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError('记录号须为正整数')
    return value


def availability(value):
    if type(value) is not bool:
        raise ValueError('可用状态须为布尔值')
    return int(value)


@contextmanager
def transaction(db, *, write=True):
    if db.in_transaction:
        db.execute('SAVEPOINT business_operation')
        try:
            yield
        except BaseException:
            db.execute('ROLLBACK TO business_operation')
            raise
        finally:
            db.execute('RELEASE business_operation')
        return
    with db:
        db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield
