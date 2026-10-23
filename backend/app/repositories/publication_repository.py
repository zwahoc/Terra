"""Named SQL Connect publication path; one guarded transaction per batch."""
from backend.app.services.ingestion_errors import IngestionError
from terra.local_adapter import LocalDataConnect, AdapterError, AdapterUnavailableError
from terra.publication_provider import EXTENSIONS
from terra.contract import FIELDS,camel


class PublicationRepository:
    def __init__(self, adapter=None):
        self.adapter=adapter if adapter is not None else LocalDataConnect()

    def state(self):
        if self.adapter.execute('GetOperationalVersion')['operationalVersion'] is None:
            try:self.adapter.execute('InitializeOperationalVersion',write=True)
            except AdapterError:
                if self.adapter.execute('GetOperationalVersion')['operationalVersion'] is None:raise
        # Revision bracketing rejects a multi-query view crossed by guarded writes.
        before=self.adapter.execute('GetOperationalVersion')['operationalVersion']['revision']
        state=self.adapter.execute('GetPublicationState')
        after=self.adapter.execute('GetOperationalVersion')['operationalVersion']['revision']
        if before!=after or state['operationalVersion']['revision']!=after:
            raise IngestionError('PUBLICATION_CONTEXT_STALE','Operational data changed while preparing publication. Refresh the plan.')
        if any(len(state[camel(e)])>=1000 for e in FIELDS) or any(len(state[e])>=1000 for e in EXTENSIONS):
            raise IngestionError('PUBLICATION_READ_CAPACITY','This atomic read guard reached the provider page boundary. Nothing was truncated or published; pagination/guard expansion is required.')
        return state

    def receipt(self, publication_id):
        return self.adapter.execute('GetPublicationReceipt',{'id':publication_id})['ingestionPublication']

    def publish(self, variables):
        try:self.adapter.execute('PublishIngestionBatch',variables,write=True)
        except AdapterUnavailableError as exc:
            raise IngestionError('PUBLICATION_OUTCOME_UNKNOWN','Publication transport failed. Reload the receipt or retry the same publication key; do not submit a new change set.',503) from exc
        except AdapterError as exc:
            if 'PUBLICATION_CONTEXT_STALE' in str(exc) or 'INGESTION_STALE_REVISION' in str(exc):
                raise IngestionError('PUBLICATION_CONTEXT_STALE','Database or review state changed. Nothing was partially applied; refresh and review again.') from exc
            raise IngestionError('PUBLICATION_REJECTED','The atomic database operation rejected the change set. No partial publication was applied.',409) from exc
        try:
            receipt = self.receipt(variables['id'])
        except AdapterError as exc:
            raise IngestionError('PUBLICATION_OUTCOME_UNKNOWN','Publication committed but receipt read-back failed. Reload the receipt or retry the same publication key.',503) from exc
        if receipt is None:
            raise IngestionError('PUBLICATION_OUTCOME_UNKNOWN','Publication returned without a readable receipt. Retry the same publication key before making another change set.',503)
        return receipt

    def dispatch(self, publication_id):
        # Intent and dirty scopes were saved with publication. The local worker
        # consumes them after commit; never wait for matching in publication.
        return self.receipt(publication_id)
