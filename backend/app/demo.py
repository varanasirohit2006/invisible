from datetime import UTC, datetime, timedelta


def sample_events() -> list[dict]:
    """Synthetic history only. These paths are never read, watched, or executed."""
    now = datetime.now(UTC)
    rows: list[dict] = []
    templates = [
        ("invoice", "pdf", 18, True),
        ("report", "csv", 9, False),
        ("screenshot", "png", 12, False),
    ]
    for group_index, (stem, extension, count, tracker) in enumerate(templates):
        for repeat in range(count):
            start = now - timedelta(days=repeat % 7, hours=group_index * 3 + 1, minutes=repeat * 11)
            original = f"C:\\Example\\Downloads\\{stem}_{repeat + 1}.{extension}"
            renamed = f"C:\\Example\\Downloads\\{stem.title()}_{repeat + 1:03}.{extension}"
            destination = f"C:\\Example\\Documents\\{stem.title()}s\\{stem.title()}_{repeat + 1:03}.{extension}"
            steps = [
                {"event_type": "file_created", "file_path": original},
                {"event_type": "file_renamed", "old_path": original, "new_path": renamed},
                {"event_type": "file_moved", "old_path": renamed, "new_path": destination},
            ]
            if tracker:
                steps.append(
                    {
                        "event_type": "file_modified",
                        "file_path": "C:\\Example\\Documents\\Invoices\\Tracker.xlsx",
                    }
                )
            for index, step in enumerate(steps):
                rows.append(
                    {
                        "event_id": f"demo-{stem}-{repeat}-{index}",
                        "timestamp": (
                            start + timedelta(seconds=index * (32 + repeat % 5 * 7))
                        ).isoformat(),
                        "is_demo": True,
                        "file_path": None,
                        "old_path": None,
                        "new_path": None,
                        **step,
                    }
                )
    return rows
