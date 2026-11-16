"""
AFE_AssetApproval - Asset Approval Node

Client selects one asset from the 9 generated options.
Fill in:
  - asset_index: which number they selected (1-9)
  - approved_seed: the seed shown in the filename

Outputs the approved asset info for downstream use
(video generation, IPAdapter, consistency nodes).
"""
from __future__ import annotations
import json
import logging

logger = logging.getLogger("AFE_AssetApproval")


def _asset_name(asset: dict) -> str:
    for key in ("name", "character_name", "description"):
        v = asset.get(key, "")
        if v:
            return str(v)
    return f"asset_{asset.get('index', '?')}"


class AFE_AssetApproval:
    """
    资产确认节点。

    客户看完 9 张图之后，在这里填入：
      asset_index   = 选第几号资产（角色/场景/服装/道具）
      approved_seed = 满意图片的 seed（从文件名 _sXXXX 获取）

    输出已确认的资产信息，供分镜视频生成使用。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "assets_json": ("STRING", {
                    "multiline": True,
                    "default": "[]",
                    "tooltip": "来自 Cast/Scene/Costume/Props Analyzer 的 JSON 输出",
                }),
                "asset_index": ("INT", {
                    "default": 1, "min": 1, "max": 500,
                    "tooltip": "选第几号资产（从1开始，对应 BatchImageGenerator 输出的顺序）",
                }),
                "approved_seed": ("INT", {
                    "default": 0, "min": 0, "max": 2**31 - 1,
                    "tooltip": "满意那张图片的 seed（从文件名 _sXXXX 中找到）\n0 = 不锁定 seed",
                }),
            },
            "optional": {
                "notes": ("STRING", {
                    "multiline": False,
                    "default": "",
                    "tooltip": "备注，例如：胖叔定案 第3版",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT", "STRING")
    RETURN_NAMES = (
        "approved_prompt",    # 已确认的正向提示词 → 接视频生成
        "approved_name",      # 资产名称（角色名/场景名等）
        "approved_json",      # 完整资产 JSON（含外貌/服装等）
        "approved_seed",      # 锁定的 seed → 接 SingleAssetGenerator
        "approval_report",    # 确认报告
    )
    FUNCTION = "approve"
    CATEGORY = "AI Film Editor/Analyzers"
    OUTPUT_NODE = True

    def approve(
        self,
        assets_json: str,
        asset_index: int,
        approved_seed: int,
        notes: str = "",
    ):
        # 解析资产列表
        try:
            assets = json.loads(assets_json)
        except Exception as exc:
            msg = f"❌ JSON 解析失败：{exc}"
            return {"ui": {"text": [msg]},
                    "result": ("", "", "{}", 0, msg)}

        if not isinstance(assets, list) or not assets:
            msg = "⚠️ 资产列表为空，请先连接分析器节点"
            return {"ui": {"text": [msg]},
                    "result": ("", "", "{}", 0, msg)}

        # 选取资产
        idx = max(1, min(asset_index, len(assets)))
        asset = assets[idx - 1]

        name   = _asset_name(asset)
        prompt = str(asset.get("positive_prompt", "")).strip()
        neg    = str(asset.get("negative_prompt", "")).strip()

        # 加入 seed 信息到资产副本
        approved_asset = dict(asset)
        approved_asset["approved_seed"]  = approved_seed
        approved_asset["approved_index"] = idx
        if notes.strip():
            approved_asset["approval_notes"] = notes.strip()

        approved_json_str = json.dumps(approved_asset, ensure_ascii=False, indent=2)

        # 生成确认报告
        seed_str = f"seed {approved_seed}" if approved_seed > 0 else "seed 未锁定（下次生成会变）"
        lines = [
            "✅ 资产已确认",
            "━" * 28,
            f"  资产编号：{idx} / {len(assets)}",
            f"  名称：    {name}",
            f"  Seed：    {seed_str}",
            f"  正向提示：{prompt[:80]}{'...' if len(prompt) > 80 else ''}",
        ]
        if notes.strip():
            lines.append(f"  备注：    {notes.strip()}")
        lines += [
            "━" * 28,
            "💡 将 approved_prompt 接到视频生成节点",
            "   将 approved_seed 接到 Single Asset Generator 可精确复现此图",
        ]

        report = "\n".join(lines)

        logger.info(
            "AssetApproval: approved index=%d name=%s seed=%d",
            idx, name, approved_seed,
        )

        return {
            "ui":    {"text": [report]},
            "result": (prompt, name, approved_json_str, approved_seed, report),
        }
