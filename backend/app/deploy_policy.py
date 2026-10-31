"""Pure decisions for the update script.

The shell update flow asks this module what to do after a failed health check
so a migrated database is never blindly downgraded.
"""

from __future__ import annotations


def health_failure_action(*, schema_before: str, schema_after: str) -> str:
    """Return the recovery action after the new process fails its health check.

    ``rollback_release`` is safe only when the schema revision did not change.
    ``keep_new_and_require_backup_restore`` leaves the new release in place and
    tells the operator to restore the pre-migration backup if they need the old
    application. This function never selects a database downgrade.
    """

    before = (schema_before or "").strip()
    after = (schema_after or "").strip()
    if before == after:
        return "rollback_release"
    return "keep_new_and_require_backup_restore"
