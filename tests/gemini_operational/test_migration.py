from .test_governor import checkpoint, reserve


def test_old_rows_and_four_column_usage_insert_still_work(op_env):
    r = reserve(op_env)
    checkpoint(op_env, r)
    with op_env.store.work_store.extension_transaction() as c:
        columns = c.execute("PRAGMA table_info(paid_fallback_usage_events)").fetchall()
        assert len(columns) == 4
        c.execute(
            "INSERT INTO paid_fallback_usage_events VALUES (?,?,?,?)",
            (
                "legacy-event",
                r.reservation_id,
                "legacy",
                op_env.store.work_store.encode_extension_json({}),
            ),
        )
    assert op_env.governor.status().reserved_inr_minor == 1000
