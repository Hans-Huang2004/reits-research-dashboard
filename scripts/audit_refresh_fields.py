"""Reconcile reviewed values and their evidence across a daily list refresh."""
from copy import deepcopy


def audit_retention(previous, current, population):
    records, removed = [], []
    for container in (('items',) if population == 'institutional' else ('funds', 'events')):
        latest = {row['id']: row for row in current.get(container, [])}
        for old in previous.get(container, []):
            new = latest.get(old['id'])
            if new is None:
                removed.append(old['id'])
                continue
            for field, evidence in old.get('research_field_sources', {}).items():
                before, after = old.get(field), new.get(field)
                if before in (None, '', []):
                    continue
                outcome = 'retained' if before == after else 'updated_from_current_source'
                if after in (None, '', []):
                    raise ValueError(f'Reviewed value lost: {container}/{old["id"]}/{field}')
                if before == after and not new.get('research_field_sources', {}).get(field):
                    raise ValueError(f'Reviewed evidence lost: {container}/{old["id"]}/{field}')
                records.append({'container': container, 'id': old['id'], 'field': field,
                                'outcome': outcome, 'before': deepcopy(before), 'after': deepcopy(after),
                                'previous_evidence': evidence,
                                'current_evidence': new.get('research_field_sources', {}).get(field, []),
                                'current_source_url': new.get('source_url'),
                                'current_source_date': new.get('up') or new.get('updated_date')})
    return {'population': population, 'checked_fields': len(records), 'records': records,
            'missing_ids_in_complete_current_list': removed}
