from typing import Dict, Iterable, Optional
from uuid import UUID


def count_documents_by_ticket(
    meta_data_values: Iterable[Optional[str]], ticket_ids: Iterable[UUID]
) -> Dict[UUID, int]:
    """Per-ticket document counts from Document.meta_data.

    Documents link to a ticket via a raw ``'{"ticket_id": "<uuid>"}'`` string
    in meta_data (no real foreign key), so counting is substring matching
    rather than a GROUP BY. Takes the already-fetched meta_data column values
    for a single bulk query, so listing N tickets costs one round trip
    instead of N.
    """
    ids = list(ticket_ids)
    counts = {tid: 0 for tid in ids}
    needles = {tid: f'"ticket_id": "{tid}"' for tid in ids}
    for md in meta_data_values:
        if not md:
            continue
        for tid, needle in needles.items():
            if needle in md:
                counts[tid] += 1
    return counts
