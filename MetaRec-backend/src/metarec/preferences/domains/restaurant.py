from ..registry import PreferenceSpec
from typing import List

RESTAURANT_LOCATION_SPEC = PreferenceSpec(
    key="restaurant.location",
    data_type="location",
    description="Restaurant location",
    localizations={
        "en": {
            "label": "Location",
        },
        "zh": {
            "label": "位置",
        }
    }
)

RESTAURANT_TYPE_SPEC = PreferenceSpec(
    key="restaurant.types",
    data_type="choice",
    localizations={
        "en": {
            "label": "restaurant type",
            "extract_preference_prompt": "Extract the type of restaurant (e.g., cafe, fine-dining).",
            "display_preference_template": "a {value} spot"
        },
        "zh": {
            "label": "餐厅类型",
            "extract_preference_prompt": "识别餐厅类型（如：咖啡厅、高级餐厅）。",
            "display_preference_template": "{value}"
        }
    },
    options={
        "en": {
            "cafe": "cafe",
            "casual": "casual dining",
            "fine-dining": "fine dining",
            "fast-casual": "fast casual",
            "street-food": "street food",
            "buffet": "buffet"
        },
        "zh": {
            "casual": "休闲餐厅",
            "fine-dining": "高级餐厅",
            "cafe": "咖啡厅",
            "buffet": "自助餐",
            "fast-casual": "快休闲",
            "street-food": "街头小吃"
        }
    }
)

RESTAURANT_FLAVOR_PROFILE_SPEC = PreferenceSpec(
    key="restaurant.flavor_profiles",
    data_type="choice",
    localizations={
        "en": {
            "label": "flavor",
            "extract_preference_prompt": "Extract the preferred flavors or taste profiles.",
            "display_preference_template": "with {value} flavors"
        },
        "zh": {
            "label": "口味",
            "extract_preference_prompt": "提取偏好的口味或风味。",
            "display_preference_template": "{value}口味"
        }
    },
    options={
        "en": {
            "spicy": "spicy",
            "savory": "savory",
            "sweet": "sweet",
            "sour": "sour",
            "mild": "mild"
        },
        "zh": {
            "spicy": "辣",
            "savory": "咸香",
            "sweet": "甜",
            "sour": "酸",
            "mild": "清淡"
        }
    }
)

RESTAURANT_DINING_PURPOSE_SPEC = PreferenceSpec(
    key="restaurant.dining_purpose",
    data_type="choice",
    localizations={
        "en": {
            "label": "dining purpose",
            "extract_preference_prompt": "Determine the occasion or purpose for dining.",
            "display_preference_template": "for {value}"
        },
        "zh": {
            "label": "用餐目的",
            "extract_preference_prompt": "确定用餐的场合或目的。",
            "display_preference_template": "用于{value}"
        }
    },
    options={
        "en": {
            "date-night": "a romantic date",
            "family": "family dining",
            "friends": "dining with friends",
            "business": "business meeting",
            "solo": "solo dining",
            "celebration": "celebration"
        },
        "zh": {
            "date-night": "浪漫约会",
            "family": "家庭聚餐",
            "friends": "朋友聚会",
            "business": "商务用餐",
            "solo": "独自用餐",
            "celebration": "庆祝活动"
        }
    }
)

RESTAURANT_BUDGET_SPEC = PreferenceSpec(
    key="restaurant.budget",
    data_type="range",
    localizations={
        "en": {
            "label": "budget",
            "extract_preference_prompt": "Extract the minimum and maximum budget per person in SGD. If only one is mentioned, estimate the other.",
            "display_preference_template": "around {min}-{max} {currency} per person"
        },
        "zh": {
            "label": "预算",
            "extract_preference_prompt": "提取每人的最低和最高预算（单位：新币）。如果只提到一个，请估算另一个。",
            "display_preference_template": "人均预算约 {min}-{max} {currency}"
        }
    },
    options={
        "en": {
            "currency": "SGD",
            "min_label": "min",
            "max_label": "max"
        },
        "zh": {
            "currency": "新币",
            "min_label": "最低",
            "max_label": "最高"
        }
    },
    default_values={
        'min': 20,
        'max': 60,
    }
)

def get_restaurant_preference_specs() -> List[PreferenceSpec]:
    return [
        RESTAURANT_TYPE_SPEC,
        RESTAURANT_FLAVOR_PROFILE_SPEC,
        RESTAURANT_DINING_PURPOSE_SPEC,
        RESTAURANT_BUDGET_SPEC,
        RESTAURANT_LOCATION_SPEC,
    ]
