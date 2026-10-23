"""Identity projection for detached same-model draft reuse; originals stay intact."""
import copy


def remap_refs(value, mapping):
    if isinstance(value, list):
        return [remap_refs(item, mapping) for item in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    result = {key:remap_refs(item, mapping) for key,item in value.items()}
    if result.get('kind') == 'PROPOSED' and result.get('id') in mapping:
        result['id'] = mapping[result['id']]
    return result


def review_namespace(batch, run, review):
    """Map current owned proposal IDs to already-reviewed ancestor IDs only."""
    known = {entity.proposal.id for entity in review.entities}
    lineage = {new:old for comparison in batch.comparisons for candidate in comparison.runs
               if (candidate.model_slot,candidate.model_id) == (run.model_slot,run.model_id)
               for new,old in candidate.proposal_lineage.items()}
    mapping = {}
    for proposal in run.proposals:
        current, seen = proposal.id, set()
        while current not in known and current in lineage and current not in seen:
            seen.add(current);current = lineage[current]
        if current in known:
            mapping[proposal.id] = current
        else:
            # Fresh analysis after a context reset has no inherited IDs. Only a
            # unique exact typed proposal can share an existing review identity;
            # never guess semantic equivalence or combine differing specs.
            candidates = [entity.proposal.id for entity in review.entities if
                entity.proposal.kind == proposal.kind and any(
                    original is not None and original.kind == proposal.kind and original.attributes == proposal.attributes
                    for original in (entity.original, entity.proposal))]
            if len(candidates) == 1:
                mapping[proposal.id] = candidates[0]
    detached = run.model_copy(deep=True)
    for proposal in detached.proposals:
        proposal.id = mapping.get(proposal.id,proposal.id)
    for file in detached.files:
        if file.draft:
            file.draft = type(file.draft).model_validate(remap_refs(file.draft.model_dump(mode='json'),mapping))
    return detached, mapping
