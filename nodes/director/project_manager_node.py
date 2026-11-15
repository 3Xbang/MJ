"""项目管理节点 — 创建或加载 AI 电影项目目录结构。

负责初始化项目目录、读取项目元数据，并输出各子目录路径，
方便下游节点直接使用标准路径。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from ai_film_editor_nodes.lib.utils.logger import get_logger

logger = get_logger(__name__)


class AFE_ProjectManager:
    """项目管理节点。

    支持创建新项目、加载现有项目、或仅获取项目路径。
    自动创建标准目录结构，输出各子目录路径供后续节点使用。
    """

    CATEGORY = "AI Film Editor/Director"
    OUTPUT_NODE = True

    PROJECT_DIRS = [
        "assets/characters",
        "assets/outfits",
        "assets/scenes",
        "assets/props",
        "shots/pass1",
        "shots/pass2",
        "shots/pass3",
        "tail_frames",
        "audio",
        "export",
    ]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "action": (["create_new", "load_existing", "get_paths"],),
                "project_name": ("STRING", {"default": "my_film_project"}),
            },
            "optional": {
                "projects_root": ("STRING", {"default": "./projects"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "project_root",
        "assets_dir",
        "shots_dir",
        "audio_dir",
        "project_status",
    )
    FUNCTION = "manage_project"

    def manage_project(
        self,
        action: str,
        project_name: str,
        projects_root: str = "./projects",
    ):
        project_root = os.path.join(projects_root, project_name)
        assets_dir = os.path.join(project_root, "assets")
        shots_dir = os.path.join(project_root, "shots")
        audio_dir = os.path.join(project_root, "audio")
        project_json = os.path.join(project_root, "project.json")

        if action == "create_new":
            for subdir in self.PROJECT_DIRS:
                os.makedirs(os.path.join(project_root, subdir), exist_ok=True)
            if not os.path.exists(project_json):
                meta = {
                    "project_name": project_name,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "version": "1.0",
                    "shots": [],
                }
                try:
                    with open(project_json, "w", encoding="utf-8") as f:
                        json.dump(meta, f, ensure_ascii=False, indent=2)
                except Exception as exc:
                    logger.warning("无法写入 project.json: %s", exc)
            project_status = f"✅ 项目已创建：{project_name}\n📁 路径：{project_root}"

        elif action == "load_existing":
            if not os.path.exists(project_root):
                project_status = f"❌ 项目不存在：{project_root}"
            else:
                missing = [
                    d
                    for d in self.PROJECT_DIRS
                    if not os.path.exists(os.path.join(project_root, d))
                ]
                if missing:
                    project_status = (
                        f"⚠️ 项目加载：{project_name}（缺少目录：{', '.join(missing)}）"
                    )
                else:
                    created = "未知"
                    if os.path.exists(project_json):
                        try:
                            with open(project_json, "r", encoding="utf-8") as f:
                                meta = json.load(f)
                            created = meta.get("created_at", "未知")
                        except Exception as exc:
                            logger.warning("无法读取 project.json: %s", exc)
                    project_status = (
                        f"✅ 项目已加载：{project_name}\n"
                        f"📅 创建时间：{created}\n"
                        f"📁 路径：{project_root}"
                    )

        else:  # get_paths
            exists_str = "存在" if os.path.exists(project_root) else "不存在"
            project_status = f"ℹ️ 项目路径：{project_root}（{exists_str}）"

        return (project_root, assets_dir, shots_dir, audio_dir, project_status)
