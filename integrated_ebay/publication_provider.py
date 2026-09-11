"""No-network provider boundary. LIVE/SANDBOX transports are intentionally absent."""

from dataclasses import dataclass
from hashlib import sha256


class PublicationError(ValueError):
    def __init__(self, code, message, *, uncertain=False):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain


@dataclass(frozen=True)
class PublicationReceipt:
    item_id: str
    listing_url: str | None = None


class MockPublicationProvider:
    mode = 'MOCK'

    def lookup(self, idempotency_key):
        # Stateless replay of the simulation, including after a local process restart.
        return PublicationReceipt('MOCK-' + sha256(idempotency_key.encode()).hexdigest()[:24])

    def publish(self, payload, *, idempotency_key):
        return self.lookup(idempotency_key)


def publication_provider(mode='DISABLED'):
    if mode == 'MOCK':
        return MockPublicationProvider()
    raise PublicationError('DISABLED', '実eBay公開は未接続です。認証・API設定・本番操作の別途承認が必要です。')
