"""角色细分领域（对齐 agency-agents Division 分类）。"""

from __future__ import annotations

import re
from typing import Any

# agency-agents 各领域 + AuC 扩展
ROLE_DIVISIONS: dict[str, dict[str, Any]] = {
    "specialized": {
        "id": "specialized",
        "label": "专项智能体",
        "label_en": "Specialized",
        "emoji": "✨",
        "description": "法律、财务、供应链、编排等专项领域智能体",
        "order": 1,
    },
    "engineering": {
        "id": "engineering",
        "label": "工程开发",
        "label_en": "Engineering",
        "emoji": "💻",
        "description": "前端、后端、DevOps、安全与 AI 工程",
        "order": 10,
    },
    "operations": {
        "id": "operations",
        "label": "运维交付",
        "label_en": "Operations",
        "emoji": "⚙️",
        "description": "构建部署、排障、环境与流水线",
        "order": 12,
    },
    "design": {
        "id": "design",
        "label": "设计",
        "label_en": "Design",
        "emoji": "🎨",
        "description": "UX、品牌、视觉与包容性设计",
        "order": 15,
    },
    "product": {
        "id": "product",
        "label": "产品",
        "label_en": "Product",
        "emoji": "🎯",
        "description": "产品策略、研究与优先级",
        "order": 20,
    },
    "education": {
        "id": "education",
        "label": "学习辅导",
        "label_en": "Education",
        "emoji": "📚",
        "description": "概念讲解、示例答疑与学习路径",
        "order": 32,
    },
    "marketing": {
        "id": "marketing",
        "label": "市场营销",
        "label_en": "Marketing",
        "emoji": "📣",
        "description": "增长、内容、SEO 与社媒",
        "order": 25,
    },
    "sales": {
        "id": "sales",
        "label": "销售",
        "label_en": "Sales",
        "emoji": "🤝",
        "description": "销售管线、提案与客户成功",
        "order": 30,
    },
    "testing": {
        "id": "testing",
        "label": "测试",
        "label_en": "Testing",
        "emoji": "🧪",
        "description": "QA、性能、无障碍与 API 测试",
        "order": 35,
    },
    "project-management": {
        "id": "project-management",
        "label": "项目管理",
        "label_en": "Project Management",
        "emoji": "📋",
        "description": "规划、冲刺与交付管理",
        "order": 40,
    },
    "support": {
        "id": "support",
        "label": "支持运营",
        "label_en": "Support",
        "emoji": "🛟",
        "description": "分析、财务、法务与基础设施支持",
        "order": 45,
    },
    "security": {
        "id": "security",
        "label": "安全",
        "label_en": "Security",
        "emoji": "🔐",
        "description": "威胁检测、合规与身份安全",
        "order": 48,
    },
    "strategy": {
        "id": "strategy",
        "label": "战略",
        "label_en": "Strategy",
        "emoji": "♟️",
        "description": "商业战略与竞争分析",
        "order": 50,
    },
    "finance": {
        "id": "finance",
        "label": "金融",
        "label_en": "Finance",
        "emoji": "💰",
        "description": "财务分析与建模",
        "order": 55,
    },
    "academic": {
        "id": "academic",
        "label": "学术",
        "label_en": "Academic",
        "emoji": "🎓",
        "description": "人文社科与学术研究",
        "order": 60,
    },
    "gis": {
        "id": "gis",
        "label": "地理信息",
        "label_en": "GIS",
        "emoji": "🗺️",
        "description": "GIS、遥感与空间分析",
        "order": 65,
    },
    "game-development": {
        "id": "game-development",
        "label": "游戏开发",
        "label_en": "Game Development",
        "emoji": "🎮",
        "description": "Unity、Unreal、Godot 等游戏引擎",
        "order": 70,
    },
    "spatial-computing": {
        "id": "spatial-computing",
        "label": "空间计算",
        "label_en": "Spatial Computing",
        "emoji": "🥽",
        "description": "XR、VisionOS 与空间界面",
        "order": 75,
    },
    "paid-media": {
        "id": "paid-media",
        "label": "付费媒体",
        "label_en": "Paid Media",
        "emoji": "📊",
        "description": "PPC、投放与归因",
        "order": 80,
    },
    "supply-chain": {
        "id": "supply-chain",
        "label": "供应链",
        "label_en": "Supply Chain",
        "emoji": "🚚",
        "description": "供应链、采购与物流",
        "order": 52,
    },
    "hr": {
        "id": "hr",
        "label": "人力资源",
        "label_en": "HR",
        "emoji": "👥",
        "description": "招聘、入职与人才发展",
        "order": 53,
    },
    "legal": {
        "id": "legal",
        "label": "法务",
        "label_en": "Legal",
        "emoji": "⚖️",
        "description": "合规、合同与法律事务",
        "order": 54,
    },
    "business": {
        "id": "business",
        "label": "商业",
        "label_en": "Business",
        "emoji": "💼",
        "description": "商业分析、运营与内容",
        "order": 85,
    },
    "real-estate": {
        "id": "real-estate",
        "label": "房地产",
        "label_en": "Real Estate",
        "emoji": "🏠",
        "description": "房产匹配、合规与 CRM",
        "order": 88,
    },
    "custom": {
        "id": "custom",
        "label": "自定义",
        "label_en": "Custom",
        "emoji": "🎭",
        "description": "沙盒内用户自建角色",
        "order": 99,
    },
}

DEFAULT_DIVISION = "custom"
_DIVISION_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def normalize_division(raw: str | None) -> str:
    key = str(raw or "").strip().lower()
    if key in ROLE_DIVISIONS:
        return key
    if key and _DIVISION_ID_RE.match(key):
        return key
    return DEFAULT_DIVISION


def division_meta(division_id: str) -> dict[str, Any]:
    if division_id in ROLE_DIVISIONS:
        return ROLE_DIVISIONS[division_id]
    label = division_id.replace("-", " ").title()
    return {
        "id": division_id,
        "label": label,
        "label_en": label,
        "emoji": "📁",
        "description": "",
        "order": 50,
    }


def divisions_payload(*, extra_ids: list[str] | None = None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for d in sorted(ROLE_DIVISIONS.values(), key=lambda x: x.get("order", 50)):
        seen.add(d["id"])
        items.append(
            {
                "id": d["id"],
                "label": d["label"],
                "label_en": d.get("label_en", d["id"]),
                "emoji": d.get("emoji", ""),
                "description": d.get("description", ""),
                "order": d.get("order", 50),
            }
        )
    for rid in extra_ids or []:
        if rid in seen or rid in ("custom", "__auto__"):
            continue
        m = division_meta(rid)
        items.append(
            {
                "id": m["id"],
                "label": m["label"],
                "label_en": m.get("label_en", m["id"]),
                "emoji": m.get("emoji", ""),
                "description": m.get("description", ""),
                "order": m.get("order", 50),
            }
        )
    return sorted(items, key=lambda x: x.get("order", 50))
