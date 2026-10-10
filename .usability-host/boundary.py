def released_state(status, guard):
    if status not in {'succeeded', 'failed', 'cancelled', 'timed_out'}:
        raise ValueError('Worker is not terminal')
    if status == 'succeeded':
        if guard is not None:
            raise ValueError('Successful closure requires terminal sibling reconciliation')
        return 'terminal'
    return 'failure-terminal' if guard is None else 'blocked-unknown-preserved'
