"""Build transfer actions; the window supplies conflict/error interactions."""

import os

from multipane_commander.services.jobs.model import FileJobAction


def plan_transfer(
    *,
    operation,
    sources,
    destination_dir,
    conflict_policy,
    unique_destination,
    resolve_conflict,
    report_error,
):
    if not destination_dir.is_dir():
        report_error(f"Destination directory does not exist:\n{destination_dir}")
        return []
    actions = []
    for source in sources:
        destination = destination_dir / source.name
        if (
            operation == "copy"
            and conflict_policy == "keep_both"
            and source.parent == destination_dir
        ):
            destination = unique_destination(destination)
        if source == destination:
            report_error(f"Source and destination are the same:\n{source}")
            continue
        replace_existing = False
        if os.path.lexists(destination):
            destination, replace_existing = resolve_conflict(
                source_path=source,
                destination_path=destination,
                conflict_policy=conflict_policy,
                operation=operation,
            )
            if destination is None:
                continue
        actions.append(FileJobAction(operation, source, destination, replace_existing))
    return actions
