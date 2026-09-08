from __future__ import annotations

from jarvis.memory.query_plan import (
    MemoryFacetCatalog,
    MemoryFacetKey,
    MemoryQueryIntent,
    MemoryQueryPlanDisposition,
    MemoryQueryPolicy,
    MemoryQueryProposal,
    MemoryTemporalScope,
)


def _catalog() -> MemoryFacetCatalog:
    return MemoryFacetCatalog(
        facets=(
            MemoryFacetKey("owner", "Aquila", "archive_destination"),
            MemoryFacetKey("owner", "Aquila", "signin_method"),
            MemoryFacetKey("owner", "Boreal", "archive_destination"),
        )
    )


def test_exact_current_fact_must_match_existing_canonical_facet() -> None:
    decision = MemoryQueryPolicy().evaluate(
        MemoryQueryProposal(
            intent=MemoryQueryIntent.EXACT_FACT,
            subject_scope="owner",
            subject="Aquila",
            predicate="archive_destination",
            temporal_scope=MemoryTemporalScope.CURRENT,
            requested_relation="archive destination",
        ),
        _catalog(),
    )

    assert decision.disposition is MemoryQueryPlanDisposition.ALLOW_CURRENT_FACT
    assert decision.reason_code == "validated_current_exact_fact"
    assert decision.plan is not None
    assert decision.plan.facet == MemoryFacetKey(
        "owner", "Aquila", "archive_destination"
    )
    assert decision.plan.temporal_scope is MemoryTemporalScope.CURRENT


def test_unspecified_temporal_scope_defaults_to_current_only_after_validation() -> None:
    decision = MemoryQueryPolicy().evaluate(
        MemoryQueryProposal(
            intent=MemoryQueryIntent.EXACT_FACT,
            subject_scope="owner",
            subject="Aquila",
            predicate="signin_method",
        ),
        _catalog(),
    )

    assert decision.disposition is MemoryQueryPlanDisposition.ALLOW_CURRENT_FACT
    assert decision.plan is not None
    assert decision.plan.temporal_scope is MemoryTemporalScope.CURRENT


def test_provider_cannot_invent_a_canonical_facet() -> None:
    decision = MemoryQueryPolicy().evaluate(
        MemoryQueryProposal(
            intent=MemoryQueryIntent.EXACT_FACT,
            subject_scope="owner",
            subject="Aquila",
            predicate="secondary_archive_destination",
        ),
        _catalog(),
    )

    assert decision.disposition is MemoryQueryPlanDisposition.ABSTAIN
    assert decision.reason_code == "unknown_canonical_facet"
    assert decision.plan is None


def test_historical_query_never_falls_through_to_current_memory() -> None:
    decision = MemoryQueryPolicy().evaluate(
        MemoryQueryProposal(
            intent=MemoryQueryIntent.EXACT_FACT,
            subject_scope="owner",
            subject="Aquila",
            predicate="archive_destination",
            temporal_scope=MemoryTemporalScope.HISTORICAL,
        ),
        _catalog(),
    )

    assert decision.disposition is MemoryQueryPlanDisposition.ABSTAIN
    assert decision.reason_code == "historical_query_requires_separate_path"
    assert decision.plan is None


def test_as_of_query_never_falls_through_to_current_memory() -> None:
    decision = MemoryQueryPolicy().evaluate(
        MemoryQueryProposal(
            intent=MemoryQueryIntent.EXACT_FACT,
            subject_scope="owner",
            subject="Aquila",
            predicate="archive_destination",
            temporal_scope=MemoryTemporalScope.AS_OF,
            as_of_text="last year",
        ),
        _catalog(),
    )

    assert decision.disposition is MemoryQueryPlanDisposition.ABSTAIN
    assert decision.reason_code == "as_of_query_requires_separate_path"
    assert decision.plan is None


def test_broad_ambiguous_and_unsupported_queries_fail_closed() -> None:
    policy = MemoryQueryPolicy()

    for intent, reason in (
        (MemoryQueryIntent.BROAD_RECALL, "broad_recall_not_auto_release_eligible"),
        (MemoryQueryIntent.AMBIGUOUS, "ambiguous_query"),
        (MemoryQueryIntent.UNSUPPORTED, "unsupported_query"),
    ):
        decision = policy.evaluate(MemoryQueryProposal(intent=intent), _catalog())
        assert decision.disposition is MemoryQueryPlanDisposition.ABSTAIN
        assert decision.reason_code == reason
        assert decision.plan is None


def test_incomplete_exact_fact_query_fails_closed() -> None:
    decision = MemoryQueryPolicy().evaluate(
        MemoryQueryProposal(
            intent=MemoryQueryIntent.EXACT_FACT,
            subject_scope="owner",
            subject="Aquila",
            predicate=None,
        ),
        _catalog(),
    )

    assert decision.disposition is MemoryQueryPlanDisposition.ABSTAIN
    assert decision.reason_code == "incomplete_exact_fact_query"
    assert decision.plan is None


def test_catalog_is_sorted_and_rejects_duplicates() -> None:
    facet_a = MemoryFacetKey("owner", "Boreal", "archive_destination")
    facet_b = MemoryFacetKey("owner", "Aquila", "archive_destination")
    catalog = MemoryFacetCatalog((facet_a, facet_b))

    assert catalog.facets == (facet_b, facet_a)

    try:
        MemoryFacetCatalog((facet_a, facet_a))
    except ValueError as exc:
        assert "duplicates" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("duplicate facets should be rejected")
