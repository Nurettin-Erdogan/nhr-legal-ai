"""Offline inspection of an explicitly supplied claim/source fixture.

Passing mechanical checks is NOT semantic approval. This tool does not fetch
sources, declare input text official, create providers or publish answers.
"""
from hashlib import sha256

from api.ai import synthesis


def inspect_binding(text, evidence, contexts):
    views = synthesis._source_views(contexts, 36000)
    if not views:
        return {'status': 'source_shape', 'semantic_support': 'not_determined'}
    units = []
    for item in evidence:
        source, unit = item.get('source'), item.get('unit')
        if type(source) is int and 1 <= source <= len(views) and type(unit) is int:
            available = views[source - 1]['units']
            if 1 <= unit <= len(available):
                context = contexts[source - 1]
                units.append({'source': source, 'unit': unit, 'text': available[unit - 1],
                    'chunk_id': str(context.chunk_id), 'source_id': str(context.source_id),
                    'source_version': context.source_version, 'revision': context.revision,
                    'content_sha256': sha256(context.content.encode('utf-8')).hexdigest()})
    try:
        claim = synthesis._checked_claim(1, text, evidence, contexts, views, lenient=True,
                                         conclusion=False)
    except synthesis._Rejected as rejection:
        return {'status': 'mechanical_rejection', 'reason': rejection.reason,
                'checks': list(rejection.checks), 'bound_units': units,
                'semantic_support': 'not_determined'}
    except (ValueError, TypeError, KeyError, IndexError):
        return {'status': 'invalid_fixture', 'bound_units': units,
                'semantic_support': 'not_determined'}
    return {'status': 'requires_semantic_review', 'notes': list(claim.notes),
            'bound_units': units, 'semantic_support': 'not_determined'}
