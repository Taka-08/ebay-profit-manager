"""Approval records and explicit execution-attempt history."""


class ApprovalRepository:
    def __init__(self, connection):
        self.c = connection

    def get(self, request_id):
        row = self.c.execute('SELECT * FROM approval_requests WHERE approval_request_id=?', (request_id,)).fetchone()
        return dict(row) if row else None

    def list(self):
        return [dict(r) for r in self.c.execute('''SELECT a.*,p.product_name FROM approval_requests a
            JOIN products p ON p.product_id=a.product_id ORDER BY a.created_at DESC,a.approval_request_id''')]

    def insert(self, values):
        self.c.execute('INSERT INTO approval_requests (' + ','.join(values) + ') VALUES (' +
                       ','.join('?' for _ in values) + ')', tuple(values.values()))

    def update(self, request_id, **values):
        self.c.execute('UPDATE approval_requests SET ' + ','.join(f'{k}=?' for k in values) +
                       ' WHERE approval_request_id=?', (*values.values(), request_id))

    def attempts(self, request_id):
        return [dict(r) for r in self.c.execute('''SELECT * FROM approval_execution_attempts
            WHERE approval_request_id=? ORDER BY attempt_number''', (request_id,))]


def marketplace_record(c, marketplace_id):
    row = c.execute('SELECT * FROM marketplace_listings WHERE marketplace_listing_id=?', (marketplace_id,)).fetchone()
    return dict(row) if row else None
