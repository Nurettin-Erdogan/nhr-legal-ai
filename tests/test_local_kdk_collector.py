from datetime import UTC, datetime, timedelta

from scripts.collect_kdk_local import due
from worker.models import Checkpoint


def test_local_kdk_obeys_checkpoint_cooldown_and_blocked_state():
    now = datetime(2026, 9, 17, tzinfo=UTC)
    checkpoint = Checkpoint(source_name="kdk", next_run_at=now + timedelta(hours=3))
    assert not due(checkpoint, now=now)
    checkpoint.next_run_at = now
    assert due(checkpoint, now=now)
    checkpoint.health_state = "blocked"
    assert not due(checkpoint, now=now)
