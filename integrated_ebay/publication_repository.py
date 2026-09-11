"""Repository for immutable approvals and publication receipts."""


class PublicationRepository:
    def __init__(self, connection):
        self.connection = connection

    def get_for_draft(self, draft_id):
        row = self.connection.execute(
            "SELECT * FROM listing_publications WHERE listing_draft_id=? AND status<>'CANCELLED'",
            (draft_id,),
        ).fetchone()
        return dict(row) if row else None

    def insert(self, values):
        self.connection.execute('INSERT INTO listing_publications (' + ','.join(values) +
                                ') VALUES (' + ','.join('?' for _ in values) + ')', tuple(values.values()))

    def update(self, publication_id, **values):
        self.connection.execute('UPDATE listing_publications SET ' +
                                ','.join(f'{key}=?' for key in values) + ' WHERE publication_id=?',
                                (*values.values(), publication_id))

    def guard_edit(self, draft_id):
        record = self.get_for_draft(draft_id)
        if record and record['status'] in ('PUBLISHING', 'PUBLISHED', 'FAILED'):
            raise ValueError('公開処理を開始した版は編集・再生成・承認解除できません。失敗時は照合または再試行してください。')
        return record
