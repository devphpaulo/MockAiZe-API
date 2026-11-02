"""Adapter for the versioned catalogue copied from Site dev c5410a3.

Update the vendored catalogue and cross-product fixture together when the Site
catalogue changes. The service never imports the Site at runtime.
"""
from . import faker_catalog as catalog

LEGACY = {
    'person': {'name': 'person.name', 'firstName': 'person.first_name', 'lastName': 'person.last_name', 'email': 'internet.email'},
    'company': {'legalName': 'company.company', 'tradeName': 'company.trade_name', 'email': 'internet.company_email'},
    'address': {'street': 'address.street_address', 'number': 'address.building_number', 'district': 'address.bairro', 'city': 'address.city', 'state': 'address.state_abbr', 'zip': 'address.postcode', 'full': 'address.address'},
}
DEFAULTS = {'person': 'name', 'company': 'legalName', 'address': 'street'}


def resolve(formula, context):
    kind = formula.get('type')
    if kind in LEGACY:
        field = formula.get('field') or DEFAULTS[kind]
        if field not in LEGACY[kind]:
            raise ValueError('Dado de perfil inválido.')
        formula = {'type': 'faker', 'catalogVersion': 1, 'catalogId': LEGACY[kind][field],
                   'group': formula.get('group') or 'principal',
                   'params': {'state': formula.get('state') or 'any'} if kind == 'address' else {}}
    item = catalog.validate_formula(formula)
    params = formula.get('params', {})
    key = (context.get('recordIndex', 0), catalog._profile_family(item),
           formula.get('group') or 'principal', params.get('state', 'any'))
    generator = context.get('_faker_generator')
    if generator is None:
        generator = catalog._generator()
        context['_faker_generator'] = generator
    return catalog.to_text(catalog._resolved_value(generator, item, key, context.setdefault('profiles', {}), params))
