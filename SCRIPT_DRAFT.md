# 迷雾港口 (Mist Harbor) - 扩充剧本草案

## 总体结构
游戏将分为四个独立的剧本文件，通过关键节点进行跳转。

## 第一章：迷雾中的异客 (chapter1.json)
**核心目标**：收集物资，获取情报，选择第二章的路线。

### 新增地点与支线
1.  **鱼市 (Fish Market)**
    *   **描述**：遍地是腐烂的鱼内脏，极其滑腻。
    *   **遭遇**：一只正在啃食尸体的“大狗”（其实是小型深潜者混种）。
    *   **获得**：【剔骨刀】 (Weapon) - 增加战斗选项。
    *   **分支**：战斗 or 潜行。

2.  **暗巷与乞丐 (Dark Alley)**
    *   **描述**：两个建筑之间的狭窄缝隙。
    *   **互动**：一个疯疯癫癫的乞丐。
    *   **选择**：
        *   给点吃的/酒（如果有） -> 获得【奇怪的硬币】（用于开启某种机关）。
        *   恐吓他 -> 他会尖叫引来敌人。
        *   无视。

### 流程图
- **Start (Arrival)**
  - -> **Town Square (Hub)**
    - -> **Tavern** (Social Path) -> Get *Amulet* or *Info*. -> Unlock **Church Route**.
    - -> **General Store** (Investigation Path) -> Get *Diary* or *Supplies*. -> Unlock **Asylum Route**.
    - -> **Fish Market** (Combat Path) -> Get *Knife*. (Optional side quest).
    - -> **Dark Alley** (Lore Path) -> Get *Coin*. (Optional side quest).

- **Exit Points**:
  - To **Church** (Requires knowing location from Tavern or Alley).
  - To **Asylum** (Requires knowing location from Store or Map).

---

## 第二章 A：深渊圣歌 (chapter2_church.json)
**核心目标**：找到死灵之书残页。

### 新增机制：伪装与解谜
1.  **前厅 (Vestibule)**
    *   **谜题**：大门紧锁，需要放入【奇怪的硬币】或者强行撬开（需撬棍）。
2.  **大堂 (Nave)**
    *   **互动**：如果持有【达贡护身符】，可以伪装成信徒参加仪式，避免战斗。
    *   **仪式**：如果 Sanity 过低，会不自觉地跟着唱颂歌，导致 Sanity 进一步下降但获得【狂乱知识】。
3.  **忏悔室 (Confessional)**
    *   **剧情**：隔壁传来神父的低语，透露了灯塔的弱点（需要特定咒语）。

- **Exit Point**: To **Lighthouse**.

---

## 第二章 B：白色噩梦 (chapter2_asylum.json)
**核心目标**：找到解药/毒药。

### 新增机制：潜行与惊悚
1.  **接待处 (Reception)**
    *   **搜集**：找到【访客名单】，发现主角的名字赫然在列（暗示主角曾是这里的病人）。
2.  **走廊 (Corridor)**
    *   **遭遇**：巡逻的“护士”（变异体）。
    *   **选择**：
        *   躲进病房（需要 Sanity 检定，失败会惊叫）。
        *   正面战斗（需要 剔骨刀/撬棍/枪）。
3.  **档案室 (Archives)**
    *   **Lore**：主角的病历。原来主角是回来“完成治疗”的。
    *   **获得**：【旧照片】（Sanity 恢复）。

- **Exit Point**: To **Lighthouse**.

---

## 第三章：终焉之塔 (chapter3.json)
**核心目标**：多重结局。

### 扩展结局
1.  **结局：旧日支配者 (The Great Old One)**
    *   条件：Sanity < 10, 持有【狂乱知识】, 在灯塔顶端选择“呼唤它”。
2.  **结局：逃避 (The Escape)**
    *   条件：在灯塔下不想上去了，试图找船离开。需要【剔骨刀】割断缆绳。
3.  **结局：同归于尽 (The Sacrifice)**
    *   原有结局的细化。

---

## 数据结构变更
在 Choice 中增加 `next_chapter` 字段。
```json
{
  "text": "前往教堂",
  "next_chapter": "chapter2_church",
  "next_node": "start"
}
```
