// AFE Character Card Workbench
// 角色多视图编辑卡 — ComfyUI Web Extension

import { app } from "../../scripts/app.js";

const SLOT_CONFIGS = [
  { key:"front_full",    name:"正面全身",   cat:"全身", col:0, row:0 },
  { key:"right_full",    name:"右侧面全身", cat:"全身", col:1, row:0 },
  { key:"back_full",     name:"背面全身",   cat:"全身", col:2, row:0 },
  { key:"left_full",     name:"左侧面全身", cat:"全身", col:3, row:0 },
  { key:"smile",         name:"温柔微笑",   cat:"表情", col:0, row:1 },
  { key:"surprised",     name:"惊讶张嘴",   cat:"表情", col:1, row:1 },
  { key:"contemplating", name:"闭眼沉思",   cat:"表情", col:2, row:1 },
  { key:"angry",         name:"嗔怒",       cat:"表情", col:3, row:1 },
  { key:"front_closeup", name:"正面特写",   cat:"特写", col:0, row:2 },
  { key:"side_closeup",  name:"侧面特写",   cat:"特写", col:1, row:2 },
  { key:"diag_closeup",  name:"斜侧特写",   cat:"特写", col:2, row:2 },
  { key:"costume_detail",name:"服装细节",   cat:"细节", col:3, row:2 },
];

class CharacterCardWorkbench {
  constructor() {
    this.slots = SLOT_CONFIGS.map((s, i) => ({
      ...s, index: i + 1,
      image: null, visible: true, desc: "", seed: 0
    }));
    this.selectedSlot = null;
    this.characterDesc = "";
    this.styleSuffix = "3D CG animation, Pixar style";
    this.panel = null;
    this.createPanel();
  }

  createPanel() {
    // Main panel
    const panel = document.createElement("div");
    panel.id = "afe-char-card-panel";
    panel.style.cssText = `
      position:fixed; top:60px; right:20px; width:900px;
      background:#1a1a2e; border:1px solid #444; border-radius:12px;
      display:none; z-index:9999; font-family:sans-serif; color:#eee;
      box-shadow:0 8px 32px rgba(0,0,0,0.6);
    `;

    // Header
    const header = document.createElement("div");
    header.style.cssText = `
      background:#0f3460; padding:12px 16px; border-radius:12px 12px 0 0;
      display:flex; align-items:center; justify-content:space-between;
    `;
    header.innerHTML = `
      <span style="font-size:16px;font-weight:bold;">🎭 角色卡工作台</span>
      <div style="display:flex;gap:8px;">
        <button id="afe-cc-generate-all" style="
          background:#e94560;border:none;color:#fff;padding:6px 14px;
          border-radius:6px;cursor:pointer;font-size:13px;">
          一键生成全部
        </button>
        <button id="afe-cc-close" style="
          background:transparent;border:1px solid #666;color:#aaa;
          padding:6px 10px;border-radius:6px;cursor:pointer;">✕</button>
      </div>`;
    panel.appendChild(header);

    // Body: left canvas + right settings
    const body = document.createElement("div");
    body.style.cssText = "display:flex; height:520px;";

    // Left canvas
    const canvas = document.createElement("div");
    canvas.style.cssText = `
      flex:1; padding:16px; overflow-y:auto;
      display:grid; grid-template-columns:repeat(4,1fr);
      grid-template-rows:repeat(3,1fr); gap:8px;
    `;
    canvas.id = "afe-cc-canvas";

    // Right settings panel
    const settings = document.createElement("div");
    settings.style.cssText = `
      width:260px; background:#16213e; border-left:1px solid #333;
      padding:16px; overflow-y:auto;
    `;
    settings.id = "afe-cc-settings";
    settings.innerHTML = `
      <div style="color:#888;font-size:13px;margin-bottom:12px;">
        点击槽位查看/编辑设置
      </div>
      <div id="afe-cc-slot-settings" style="display:none;">
        <div style="margin-bottom:10px;">
          <label style="font-size:12px;color:#aaa;">槽位名称</label>
          <div id="afe-cc-slot-name" style="font-size:15px;font-weight:bold;color:#e94560;"></div>
        </div>
        <div style="margin-bottom:10px;">
          <label style="font-size:12px;color:#aaa;">类别</label>
          <div id="afe-cc-slot-cat" style="font-size:13px;color:#88aaff;"></div>
        </div>
        <div style="margin-bottom:10px;">
          <label style="font-size:12px;color:#aaa;">镜头描述（修改要求）</label>
          <textarea id="afe-cc-slot-desc" placeholder="可选：输入修改要求&#10;例：把鞋子换成白色运动鞋" style="
            width:100%;height:80px;background:#0d1b2a;border:1px solid #444;
            color:#eee;border-radius:6px;padding:6px;font-size:12px;
            resize:none;margin-top:4px;box-sizing:border-box;"></textarea>
        </div>
        <div style="margin-bottom:10px;">
          <label style="font-size:12px;color:#aaa;">已用 Seed</label>
          <div id="afe-cc-slot-seed" style="font-size:12px;color:#ffaa44;font-family:monospace;"></div>
        </div>
        <div style="display:flex;gap:8px;margin-top:12px;">
          <button id="afe-cc-regen-slot" style="
            flex:1;background:#e94560;border:none;color:#fff;
            padding:8px;border-radius:6px;cursor:pointer;font-size:13px;">
            🔄 重新生成
          </button>
          <button id="afe-cc-hide-slot" style="
            background:#333;border:1px solid #555;color:#aaa;
            padding:8px 10px;border-radius:6px;cursor:pointer;font-size:13px;">
            👁
          </button>
        </div>
      </div>`;

    body.appendChild(canvas);
    body.appendChild(settings);
    panel.appendChild(body);

    // Footer: char description input
    const footer = document.createElement("div");
    footer.style.cssText = `
      border-top:1px solid #333; padding:12px 16px;
      display:flex; gap:8px; align-items:flex-start;
    `;
    footer.innerHTML = `
      <div style="flex:1;">
        <label style="font-size:12px;color:#aaa;">角色外貌描述</label>
        <textarea id="afe-cc-char-desc" placeholder="输入角色外貌描述（将用于所有槽位）&#10;例：25-year-old Chinese male, messy dark hair, white T-shirt, gold necklace" style="
          width:100%;height:50px;background:#0d1b2a;border:1px solid #444;
          color:#eee;border-radius:6px;padding:6px;font-size:12px;
          resize:none;margin-top:4px;box-sizing:border-box;"></textarea>
      </div>
      <div style="width:200px;">
        <label style="font-size:12px;color:#aaa;">风格后缀</label>
        <input id="afe-cc-style" value="3D CG animation, Pixar style" style="
          width:100%;background:#0d1b2a;border:1px solid #444;color:#eee;
          border-radius:6px;padding:6px;font-size:12px;margin-top:4px;
          box-sizing:border-box;">
        <button id="afe-cc-export" style="
          width:100%;margin-top:8px;background:#0f3460;border:1px solid #446;
          color:#88aaff;padding:6px;border-radius:6px;cursor:pointer;font-size:12px;">
          📋 复制配置 JSON
        </button>
      </div>`;
    panel.appendChild(footer);

    document.body.appendChild(panel);
    this.panel = panel;

    // Build slots
    this.slots.forEach(slot => this.createSlotCard(slot, canvas));

    // Event listeners
    document.getElementById("afe-cc-close").addEventListener("click", () => this.hide());
    document.getElementById("afe-cc-generate-all").addEventListener("click", () => this.generateAll());
    document.getElementById("afe-cc-regen-slot").addEventListener("click", () => this.regenSlot());
    document.getElementById("afe-cc-hide-slot").addEventListener("click", () => this.toggleSlotVisible());
    document.getElementById("afe-cc-export").addEventListener("click", () => this.exportJSON());
    document.getElementById("afe-cc-slot-desc").addEventListener("change", (e) => {
      if (this.selectedSlot !== null) {
        this.slots[this.selectedSlot].desc = e.target.value;
      }
    });
  }

  createSlotCard(slot, canvas) {
    const card = document.createElement("div");
    card.id = `afe-slot-${slot.index}`;
    card.style.cssText = `
      background:#0d1b2a; border:2px solid #333; border-radius:8px;
      position:relative; cursor:pointer; overflow:hidden;
      aspect-ratio:1; display:flex; flex-direction:column;
      align-items:center; justify-content:center;
      transition:border-color 0.2s;
    `;
    card.innerHTML = `
      <div class="slot-placeholder" style="
        display:flex;flex-direction:column;align-items:center;
        color:#555;font-size:12px;gap:4px;">
        <span style="font-size:24px;">+</span>
        <span>${slot.name}</span>
      </div>
      <img class="slot-img" style="
        display:none;width:100%;height:100%;object-fit:cover;
        position:absolute;top:0;left:0;" />
      <div class="slot-label" style="
        position:absolute;bottom:0;left:0;right:0;
        background:rgba(0,0,0,0.7);font-size:11px;color:#ccc;
        padding:3px 6px;text-align:center;">${slot.name}</div>
      <div class="slot-controls" style="
        position:absolute;top:4px;right:4px;display:none;
        gap:3px;flex-direction:row;">
        <button class="slot-regen" data-idx="${slot.index-1}" title="重新生成" style="
          background:rgba(233,69,96,0.9);border:none;color:#fff;
          width:22px;height:22px;border-radius:4px;cursor:pointer;font-size:11px;">↺</button>
        <button class="slot-hide" data-idx="${slot.index-1}" title="显示/隐藏" style="
          background:rgba(50,50,70,0.9);border:none;color:#aaa;
          width:22px;height:22px;border-radius:4px;cursor:pointer;font-size:11px;">👁</button>
      </div>`;

    card.addEventListener("mouseenter", () => {
      card.style.borderColor = "#e94560";
      card.querySelector(".slot-controls").style.display = "flex";
    });
    card.addEventListener("mouseleave", () => {
      card.style.borderColor = this.selectedSlot === slot.index-1 ? "#e94560" : "#333";
      card.querySelector(".slot-controls").style.display = "none";
    });
    card.addEventListener("click", (e) => {
      if (!e.target.classList.contains("slot-regen") &&
          !e.target.classList.contains("slot-hide")) {
        this.selectSlot(slot.index - 1);
      }
    });
    card.querySelector(".slot-regen").addEventListener("click", (e) => {
      e.stopPropagation();
      this.selectedSlot = slot.index - 1;
      this.regenSlot();
    });
    card.querySelector(".slot-hide").addEventListener("click", (e) => {
      e.stopPropagation();
      this.selectedSlot = slot.index - 1;
      this.toggleSlotVisible();
    });

    canvas.appendChild(card);
  }

  selectSlot(idx) {
    // Deselect previous
    if (this.selectedSlot !== null) {
      const prev = document.getElementById(`afe-slot-${this.selectedSlot + 1}`);
      if (prev) prev.style.borderColor = "#333";
    }
    this.selectedSlot = idx;
    const card = document.getElementById(`afe-slot-${idx + 1}`);
    if (card) card.style.borderColor = "#e94560";

    const slot = this.slots[idx];
    const ss = document.getElementById("afe-cc-slot-settings");
    ss.style.display = "block";
    document.getElementById("afe-cc-slot-name").textContent = slot.name;
    document.getElementById("afe-cc-slot-cat").textContent = slot.cat;
    document.getElementById("afe-cc-slot-desc").value = slot.desc;
    document.getElementById("afe-cc-slot-seed").textContent =
      slot.seed > 0 ? `${slot.seed}` : "未生成";
  }

  updateSlotImage(idx, imageUrl, seed) {
    const slot = this.slots[idx];
    slot.image = imageUrl;
    slot.seed = seed;
    slot.generated = true;

    const card = document.getElementById(`afe-slot-${idx + 1}`);
    if (!card) return;
    const img = card.querySelector(".slot-img");
    const placeholder = card.querySelector(".slot-placeholder");
    img.src = imageUrl;
    img.style.display = "block";
    placeholder.style.display = "none";

    if (this.selectedSlot === idx) {
      document.getElementById("afe-cc-slot-seed").textContent = `${seed}`;
    }
  }

  toggleSlotVisible() {
    if (this.selectedSlot === null) return;
    const slot = this.slots[this.selectedSlot];
    slot.visible = !slot.visible;
    const card = document.getElementById(`afe-slot-${this.selectedSlot + 1}`);
    if (card) card.style.opacity = slot.visible ? "1" : "0.3";
  }

  generateAll() {
    const charDesc = document.getElementById("afe-cc-char-desc").value;
    const style = document.getElementById("afe-cc-style").value;
    app.graphToPrompt().then(p => {
      console.log("[AFE CharCard] 一键生成 — 请在工作流中使用 CharacterCardBatch 节点");
      alert("请在 ComfyUI 工作流中运行 AFE_CharacterCardBatch 节点以批量生成所有槽位。\n\n角色描述已记录，请在节点的 character_description 中使用。");
    });
  }

  regenSlot() {
    if (this.selectedSlot === null) return;
    const slot = this.slots[this.selectedSlot];
    slot.desc = document.getElementById("afe-cc-slot-desc").value;
    alert(`请在 ComfyUI 工作流中运行 AFE_CharacterSlotGenerate 节点\n槽位编号：${slot.index}\n槽位名称：${slot.name}${slot.desc ? '\n修改要求：' + slot.desc : ''}`);
  }

  exportJSON() {
    const charDesc = document.getElementById("afe-cc-char-desc").value;
    const style = document.getElementById("afe-cc-style").value;
    const config = {
      character_description: charDesc,
      style_suffix: style,
      slots: this.slots.map(s => ({
        index: s.index, key: s.key, name: s.name,
        category: s.cat, slot_desc: s.desc,
        generated: s.generated, seed: s.seed, visible: s.visible,
      }))
    };
    navigator.clipboard.writeText(JSON.stringify(config, null, 2))
      .then(() => alert("✅ 配置 JSON 已复制到剪贴板"))
      .catch(() => console.log(JSON.stringify(config, null, 2)));
  }

  show() { this.panel.style.display = "block"; }
  hide() { this.panel.style.display = "none"; }
  toggle() {
    if (this.panel.style.display === "none") this.show();
    else this.hide();
  }
}

// Register ComfyUI extension
app.registerExtension({
  name: "AFE.CharacterCardWorkbench",

  async setup() {
    window._afeCharCard = new CharacterCardWorkbench();

    // Add button to ComfyUI menu
    const btn = document.createElement("button");
    btn.textContent = "🎭 角色卡";
    btn.title = "角色多视图编辑卡";
    btn.style.cssText = `
      background:#0f3460; border:1px solid #446; color:#88aaff;
      padding:4px 10px; border-radius:6px; cursor:pointer;
      font-size:13px; margin-left:8px;
    `;
    btn.addEventListener("click", () => window._afeCharCard.toggle());

    // Insert into ComfyUI toolbar
    const toolbar = document.querySelector(".comfy-menu") ||
                    document.querySelector("#queue-button")?.parentElement;
    if (toolbar) {
      toolbar.appendChild(btn);
    } else {
      // Fallback: add after DOM loads
      setTimeout(() => {
        const tb = document.querySelector(".comfyui-menu-right") ||
                   document.querySelector(".comfy-menu");
        if (tb) tb.appendChild(btn);
      }, 2000);
    }
  },

  async nodeCreated(node) {
    // Auto-link results back to character card UI
    if (node.type === "AFE_CharacterSlotGenerate") {
      node.onExecuted = function(output) {
        if (output?.images && window._afeCharCard) {
          const slotIdx = (node.widgets?.find(w => w.name === "slot_index")?.value || 1) - 1;
          const seed = output.used_seed?.[0] || 0;
          // Update slot image in workbench
          if (output.images[0]) {
            const imgData = output.images[0];
            const url = `/view?filename=${imgData.filename}&subfolder=${imgData.subfolder || ""}&type=${imgData.type || "output"}`;
            window._afeCharCard.updateSlotImage(slotIdx, url, seed);
          }
        }
      };
    }
  }
});