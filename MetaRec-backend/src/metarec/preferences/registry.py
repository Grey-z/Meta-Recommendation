from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class PreferenceSpec(BaseModel):
    #e.g. restaurant.dining_purpose
    key: str 

    description: Optional[str] = None

    # 'range', 'text', 'choice',
    data_type: str 

    # map <purpose>.<language_code> - string
    localizations: Dict[str, Dict[str, str]]

    # map language_code: option display value
    options: Optional[Dict[str, Dict[str, str]]] = None
    
    # for range etc
    default_value: Optional[Any] = None

class PreferenceRegistry:
    def __init__(self):
        # domain -> group -> spec
        self._specs: Dict[str, PreferenceSpec] = {}
    
    def register(self, spec: PreferenceSpec):
        print(f'Registered PreferenceSpec {spec.key}')
        self._specs[spec.key] = spec
    
    def get_domain_specs(self, domain: str) -> List[PreferenceSpec]:
        return [
            val 
            for key, val in self._specs.items()
            if key.startswith(f'{domain}.')
        ]
