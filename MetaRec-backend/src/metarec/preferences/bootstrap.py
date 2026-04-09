from .registry import PreferenceRegistry
from .domains.restaurant import get_restaurant_preference_specs
from .domains.books import get_books_preference_specs

registry = PreferenceRegistry()

for spec in get_restaurant_preference_specs():
    registry.register(spec)

for spec in get_books_preference_specs():
    registry.register(spec)

for domain in [
    'restaurant',
    'books',
]:
    print("")
    domain_specs = registry.get_domain_specs(domain)
    print(f'Enumerate {domain} PreferenceSpecs')
    for spec in domain_specs:
        print(spec.model_dump_json(indent=2))


