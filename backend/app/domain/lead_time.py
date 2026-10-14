"""Explicit synthetic township policy for new demo planning, not trip history."""

DEMO_LEAD_TIME_POLICY_VERSION = "demo-township-v1"


def demo_township_lead_time_days(
    source_township: str | None, destination_township: str | None,
) -> int | None:
    """One calendar day within a township, two across distinct townships.

    Normalize case and whitespace only. Do not infer areas from distances or
    similar names. Missing township information yields unknown lead time so the
    evaluator requires review. A later route-specific policy can replace this.
    """
    if not isinstance(source_township, str) or not isinstance(destination_township, str):
        return None
    source = " ".join(source_township.split()).casefold()
    destination = " ".join(destination_township.split()).casefold()
    if not source or not destination:
        return None
    return 1 if source == destination else 2
