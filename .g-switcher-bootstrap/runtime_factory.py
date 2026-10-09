def make_runtime_factory(canonical_runtime, authenticate, *, lease_ttl=1200):
    """Construct the exact canonical types; delegate only its supported quiescence argument."""
    def factory(*args, **kwargs):
        runtime = canonical_runtime(*args, **kwargs)
        original = runtime.acquire_execution_lease
        def acquire(store, revision, repository, source_ref, owner_id, task_id, attempt_id, at, **options):
            quiescence = authenticate(store, revision, repository, source_ref, owner_id, task_id, attempt_id, at)
            options.setdefault('ttl', lease_ttl)
            return original(store, revision, repository, source_ref, owner_id, task_id, attempt_id, at,
                            quiescence=quiescence, **options)
        runtime.acquire_execution_lease = acquire
        return runtime
    return factory
