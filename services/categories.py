"""综合素质测评的六大类，全站共用。"""
SCORING_CATEGORIES = [
    {"slug": "behavior", "label": "行为规范", "claimable": False},
    {"slug": "growth", "label": "成才意识", "claimable": True},
    {"slug": "innovation", "label": "科技创新与学科竞赛", "claimable": True},
    {"slug": "service", "label": "社会工作", "claimable": True},
    {"slug": "culture", "label": "文体活动", "claimable": True},
    {"slug": "honor", "label": "荣誉称号", "claimable": True},
]
CATEGORY_MAP = {item["slug"]: item["label"] for item in SCORING_CATEGORIES}
CLAIMABLE_CATEGORIES = [item for item in SCORING_CATEGORIES if item["claimable"]]
