"""Migration is intentionally not wired into the current execution flow.
Keep this module for later extension. The current scheduler records forward
transitions as part of the execution transaction in scheduler.py.
"""
def auto_migrate_jobs(*args, **kwargs):
    raise NotImplementedError("Legacy auto-migration is deferred; use the forward-only scheduler.")
