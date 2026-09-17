"""Approval records and explicit execution-attempt history."""


class ApprovalRepository:
    def __init__(self, connection, *, sandbox=False):
        self.c = connection
        self.table = 'sandbox_approval_requests' if sandbox else 'approval_requests'
        self.attempt_table = 'sandbox_approval_attempts' if sandbox else 'approval_execution_attempts'

    def get(self, request_id):
        row = self.c.execute(f'SELECT * FROM {self.table} WHERE approval_request_id=?', (request_id,)).fetchone()
        return dict(row) if row else None

    def list(self):
        return [dict(r) for r in self.c.execute(f'''SELECT a.*,p.product_name FROM {self.table} a
            JOIN products p ON p.product_id=a.product_id ORDER BY a.created_at DESC,a.approval_request_id''')]

    def insert(self, values):
        self.c.execute(f'INSERT INTO {self.table} (' + ','.join(values) + ') VALUES (' +
                       ','.join('?' for _ in values) + ')', tuple(values.values()))

    def update(self, request_id, **values):
        self.c.execute(f'UPDATE {self.table} SET ' + ','.join(f'{k}=?' for k in values) +
                       ' WHERE approval_request_id=?', (*values.values(), request_id))

    def attempts(self, request_id):
        return [dict(r) for r in self.c.execute(f'''SELECT * FROM {self.attempt_table}
            WHERE approval_request_id=? ORDER BY attempt_number''', (request_id,))]


def marketplace_record(c, marketplace_id, *, sandbox=False):
    table = 'sandbox_marketplace_listings' if sandbox else 'marketplace_listings'
    row = c.execute(f'SELECT * FROM {table} WHERE marketplace_listing_id=?', (marketplace_id,)).fetchone()
    return dict(row) if row else None
