#!/usr/bin/env python3
"""
熊熊每日配送計畫 - 自動化配送腳本

步驟：
1. 檢查 ComfyUI 狀態
2. 取得熊熊名字與風格
3. 準備目錄
4. 產生 metadata → MiniMax Chat 產英文 prompt → 生圖（ComfyUI + MiniMax，Comfy 失敗改 MiniMax）
5. 複製圖片並更新 bears.json
6. Git commit + push
7. 部署 Cloudflare Pages
"""

import argparse
import base64
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import uuid
import requests
import urllib.request
from datetime import datetime, date
from pathlib import Path
import random

# ===== 設定 =====
PROJECT_DIR = Path("/home/fjj04/my-bear-museum")
BEARS_JSON = PROJECT_DIR / "bears.json"
DEFAULT_TEMP_DIR = Path("/home/fjj04/bears")
DEFAULT_DEST_DIR = PROJECT_DIR / "bears"
VOCAB_DIR = PROJECT_DIR / "vocabulary"
LOG_DIR = VOCAB_DIR / "logs"
BEAR_NAMING = VOCAB_DIR / "bear-naming.json"
STYLE_ROTATION = VOCAB_DIR / "style-rotation.json"
BEAR_QUOTES = VOCAB_DIR / "bear-quotes.json"
WORLD_BUILDING = VOCAB_DIR / "world-building.json"
VOCABULARY = VOCAB_DIR / "vocabulary.json"
BEAR_FRIENDS = VOCAB_DIR / "bear-friends.json"
BEAR_CONDITIONS = VOCAB_DIR / "bear-conditions.json"
BEAR_TEXTURES = VOCAB_DIR / "bear-textures.json"

COMFYUI_URL = "http://fjjhomei9.fjj.home:8188"
COMFY_WORKFLOW = Path("/home/fjj04/comfyui/Flux.2-Klein-文生图_API.json")
COMFY_SCRIPT_DIR = Path("/home/fjj04/.hermes/skills_custom/comfyui-gen-image/scripts")

MINIMAX_API_KEY = "sk-cp-lV21qvcemkF6vZI0d494QVJFj0oj0y7cvAjpjGACOs2H4gYBwtvAFqYjZNFyYIiv2W532ZcNwftGpfGWXzS4SkGyLpqi7vBUIrFteW72R1FGMGau8-oi_0A"
MINIMAX_IMAGE_URL = "https://api.minimax.io/v1/image_generation"
MINIMAX_CHAT_URL = "https://api.minimax.io/v1/chat/completions"
MINIMAX_CHAT_MODEL = "MiniMax-M2.5-highspeed"

PROMPT_QUALITY_SUFFIX = (
    "soft kawaii style, horizontal composition 16:9, "
    "high quality illustration, detailed fur texture"
)
MIN_PROMPT_LENGTH = 80

PROMPT_SYSTEM = """You are an expert at writing English text-to-image prompts for cute kawaii bear museum characters.

Given bear metadata in Traditional Chinese, write ONE detailed English image generation prompt.

Rules:
- Infer fur color and scene from the bear name, personality, series, and title
- Translate the art style to English (e.g. 油畫=oil painting, 霓虹燈=neon light, 水彩=watercolor, 故障藝術=glitch art)
- Describe a vivid scene with atmosphere and magical lighting
- Write as a single English paragraph, at least 2 sentences, 80+ words
- Do NOT include Chinese characters or the raw Chinese bear name
- Do NOT include quality tags like "16:9", "kawaii style", or "detailed fur texture" (added separately)
- Output ONLY the prompt text, no quotes, no explanation, no markdown, no thinking
- The bear MUST have exactly FOUR legs (two front paws + two hind legs) — never five legs, never three legs
- The bear must look like a bear: round bear ears, round teddy bear face, fluffy bear paws — not a rabbit, cat, fox, or other animal
- 50% of the time, add a texture layer (glass, metal, wood, stone, plush, cotton, silk, wool, clay, gold leaf, etc.) provided in the metadata
- Texture should be combined with style naturally: e.g. "oil painting style with gold leaf texture", "watercolor painting with rough stone surface", "3D rendered style with glass-like translucent quality"
- Texture describes material/tactile quality (how it FEELS), style describes atmosphere/mood (how it LOOKS) — both should layer harmoniously
- 60% of the time, add 1-3 friends to the scene based on the bear's personality and quote
- Friends can be: human child, small dog, cat, rabbit, hamster, duckling, teddy bear toy, or small doll
- Scenarios for friends: adventure (forest, beach, mountain camping, cave, stargazing), play (bubbles, kite, swings, soccer, snowman), outing (picnic, market, train, boat, blossoms, skiing)
- When adding friends, the bear should be the main focus (larger in foreground) OR all characters equally important
- Describe the friendship and interaction between characters
- Optional conditions can be added based on probability:
  - Weather: sunny, rainy, snowy, typhoon, rainbow, foggy morning
  - Time: dawn, morning, noon, sunset, starry night, moonlight
  - Holiday: New Year, Lunar New Year, Mid-Autumn, Halloween, Christmas, Valentine's, Birthday
  - Props: glasses, balloons, umbrella, crown, backpack, guitar, scarf, microphone
  - Emotions: laughing, shy smile, curious, surprised, thoughtful, excited
- Multiple conditions can combine: e.g. "in snowy weather at dusk playing guitar"
- When conditions are present, weave them naturally into the scene description (e.g. weather sets atmosphere, time affects lighting, props are held/worn by the bear, emotions shape facial expression and pose)
- The image should reflect all provided conditions as a coherent whole, not as a checklist"""


class DeliveryConfig:
    def __init__(
        self,
        temp_dir=DEFAULT_TEMP_DIR,
        dest_dir=DEFAULT_DEST_DIR,
        minimax_size="16:9",
        comfy_width=1600,
        comfy_height=912,
        comfy_count=3,
        minimax_count=3,
        comfyui_url=COMFYUI_URL,
        mode="",
    ):
        self.temp_dir = Path(temp_dir)
        self.dest_dir = Path(dest_dir)
        self.minimax_size = minimax_size
        self.comfy_width = comfy_width
        self.comfy_height = comfy_height
        self.comfy_count = comfy_count
        self.minimax_count = minimax_count
        self.comfyui_url = comfyui_url
        self.mode = mode

    @property
    def total_count(self):
        return self.comfy_count + self.minimax_count


_log_file = None


def init_log_file(today):
    global _log_file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log_file = LOG_DIR / f"{today}.log"


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    if _log_file is not None:
        with open(_log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def run_cmd(cmd, check=True):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise Exception(f"命令執行失敗: {cmd}\n{result.stderr}")
    return result.stdout.strip()


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def check_comfyui(config):
    try:
        resp = requests.get(f"{config.comfyui_url}/system_stats", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def get_today():
    return date.today().strftime("%Y-%m-%d")


def get_next_bear_names(n=8):
    naming = load_json(BEAR_NAMING)
    combinations = naming.get("combinations", {}).get("names", [])

    try:
        existing = load_json(BEARS_JSON)
        existing_names = {b["name"] for b in existing.get("bears", [])}
    except Exception:
        existing_names = set()

    available = [name for name in combinations if name not in existing_names]
    while len(available) < n:
        prefix = random.choice(naming["parts"]["prefix"]["words"])
        suffix = random.choice(naming["parts"]["suffix"]["words"])
        name = prefix + suffix
        if name not in existing_names and name not in available:
            available.append(name)

    return random.sample(available, min(n, len(available)))


def peek_styles(n=8):
    """預覽即將配送的風格（隨機抽選，不重複）。"""
    rotation = load_json(STYLE_ROTATION)
    styles = rotation.get("styles", [])
    if not styles:
        return [], None
    n = min(n, len(styles))
    selected = random.sample(styles, n)
    return selected, None


def get_next_styles(n=8):
    """隨機選 n 個不重複的風格（不依序輪流）。"""
    selected, _ = peek_styles(n)
    rotation = load_json(STYLE_ROTATION)
    rotation["last_updated"] = get_today()
    save_json(STYLE_ROTATION, rotation)
    return selected


def get_random_style():
    """隨機選一個風格，回傳 {zh, en} dict。"""
    rotation = load_json(STYLE_ROTATION)
    styles = rotation.get("styles", [])
    if not styles:
        return {"zh": "3D", "en": "3D rendered style with volumetric depth"}
    return random.choice(styles)


def get_random_texture():
    """根據 texture_probability 決定是否加質感，回傳 {zh, en} dict 或 None。"""
    textures_data = load_json(BEAR_TEXTURES)
    textures = textures_data.get("textures", [])
    if not textures:
        return None
    probability = textures_data.get("texture_probability", 0.5)
    if random.random() > probability:
        return None
    return random.choice(textures)


def get_random_quote():
    quotes = load_json(BEAR_QUOTES)
    categories = list(quotes.get("categories", {}).keys())
    cat = random.choice(categories)
    cat_quotes = quotes["categories"][cat].get("quotes", [])
    return random.choice(cat_quotes) if cat_quotes else "每一天都是新的開始。"


def get_random_series():
    vocab = load_json(VOCABULARY)
    series_cats = ["童話系", "夢幻系"]
    cat = random.choice(series_cats)
    word = random.choice(vocab["categories"][cat]["words"])
    return f"{word}系列"


def get_max_collection_no():
    data = load_json(BEARS_JSON)
    bears = data.get("bears", [])
    if not bears:
        return 0
    return max(b["collectionNo"] for b in bears)


def get_random_personality(style=None):
    wb = load_json(WORLD_BUILDING)
    vocab = load_json(VOCABULARY)

    traits = [t for t in wb["categories"]["熊熊個性"]["words"] if len(t) <= 8]
    trait = random.choice(traits)
    trait2 = random.choice([t for t in traits if t != trait])

    scene_cats = ["自然系", "天空系", "星空系", "甜點系", "花卉系", "海洋系", "夢幻系", "童話系"]
    scene = random.choice(vocab["categories"][random.choice(scene_cats)]["words"])

    warm_tails = [
        "是個夢幻的小精靈",
        "總是給身邊的人帶來幸福感",
        "珍惜每一個美好的瞬間",
        "熱愛大自然的美好",
        "帶來滿滿的溫暖與快樂",
        "充滿好奇與勇氣",
    ]
    actions = ["漫步", "探險", "玩耍", "小憩", "追光", "跳舞", "守護"]

    templates = [
        f"今天發現了{scene}，想分享給你！{trait}，{random.choice(warm_tails)}。",
        f"我{random.choice(['在', '於'])}{scene}中{random.choice(actions)}！{trait}，{trait2}。",
        f"{trait}，{random.choice(['喜歡', '熱愛'])}{scene}。{random.choice(warm_tails)}。",
        f"我{random.choice(['在', '於'])}{scene}裡找到了美好！{trait}，{random.choice(['喜歡收集閃閃發亮的東西', '熱愛探索未知', '珍惜每一個綻放的瞬間'])}。",
    ]
    if style:
        templates.append(
            f"我用{style}風格描繪{scene}！{trait}，{trait2}，{random.choice(warm_tails)}。"
        )
    return random.choice(templates)


def bear_filename(collection_no, name):
    """館藏圖片檔名：編號-名字.png，如 46-彩霞漫遊者.png"""
    return f"{collection_no}-{name}.png"


def bear_img_path(config, today, collection_no, name):
    rel = (config.dest_dir / today / bear_filename(collection_no, name)).relative_to(PROJECT_DIR)
    return str(rel).replace("\\", "/")


def derive_title(name):
    """從熊熊名字推斷稱號（如 彩霞追光者 → 追光者）。"""
    naming = load_json(BEAR_NAMING)
    suffixes = naming.get("parts", {}).get("suffix", {}).get("words", [])
    for suffix in sorted(suffixes, key=len, reverse=True):
        if suffix != "熊" and name.endswith(suffix):
            return suffix
    return name


def get_friend_info():
    """根據 60% 機率隨機決定是否有朋友，若有則隨機選 1-3 個朋友類型和場景。"""
    friends_data = load_json(BEAR_FRIENDS)
    prob = friends_data.get("friend_probability", 0.6)

    if random.random() > prob:
        return None  # 40% 機率只有熊熊自己

    # 有朋友：隨機選 1-3 個
    num_friends = random.randint(1, 3)
    friend_types = friends_data["friend_types"]
    selected_friends = random.sample(friend_types, min(num_friends, len(friend_types)))

    # 隨機選一個場景類型，再從中選一個具體場景
    scenario_types = friends_data["scenarios"]
    scenario_category = random.choice(list(scenario_types.keys()))
    scenario = random.choice(scenario_types[scenario_category])

    return {
        "friends": selected_friends,
        "scenario_type": scenario_category,
        "scenario": scenario,
    }


def load_conditions():
    """從 bear-conditions.json 載入條件詞彙庫。"""
    return load_json(BEAR_CONDITIONS)


def select_conditions(conditions_data=None):
    """根據 condition_probability 隨機決定要加入哪些條件。

    回傳結構：
        {
            "weather": {...} | None,
            "time_of_day": {...} | None,
            "holiday": {...} | None,
            "prop": {...} | None,
            "emotion": {...} | None,
        }
    """
    if conditions_data is None:
        conditions_data = load_conditions()

    probability = conditions_data.get("condition_probability", {})

    # 對應 JSON 鍵 → 機率表鍵 的映射：
    #   holidays (JSON)  ↔  holiday (prob)
    #   props   (JSON)   ↔  props   (prob)
    #   其他              ↔  同名
    def _pick(json_key, prob_key):
        prob = probability.get(prob_key, 0.0)
        items = conditions_data.get(json_key, [])
        if not items:
            return None
        if random.random() > prob:
            return None
        return random.choice(items)

    selected = {}
    selected["weather"] = _pick("weather", "weather")
    selected["time_of_day"] = _pick("time_of_day", "time_of_day")
    selected["holiday"] = _pick("holidays", "holiday")
    selected["prop"] = _pick("props", "props")
    selected["emotion"] = _pick("emotions", "emotion")
    return selected


def prepare_bear_metadata(name, style):
    """生圖前先產生熊熊 metadata，供 prompt 與 bears.json 共用。

    Args:
        name: 熊熊中文名字
        style: 風格 dict {"zh": ..., "en": ...} 或字串（向後相容）
    """
    # 向後相容：若 style 是字串，包成 dict
    if isinstance(style, str):
        style_obj = {"zh": style, "en": style}
    else:
        style_obj = style

    metadata = {
        "name": name,
        "style": style_obj,
        "style_zh": style_obj.get("zh", ""),
        "series": get_random_series(),
        "personality": get_random_personality(style_obj.get("zh")),
        "quote": get_random_quote(),
        "title": derive_title(name),
    }

    # 加入朋友資訊
    friend_info = get_friend_info()
    if friend_info:
        metadata["friend_info"] = friend_info

    # 加入質感（50% 機率）
    texture = get_random_texture()
    if texture:
        metadata["texture"] = texture

    # 加入 5 個獨立條件（天氣/時間/節日/道具/情緒）
    conditions = select_conditions()
    # 篩掉 None，保留實際啟用的條件
    active_conditions = {k: v for k, v in conditions.items() if v}
    if active_conditions:
        metadata["conditions"] = active_conditions

    return metadata


def make_bear_record(metadata, today, collection_no, daily_index, config):
    img_path = bear_img_path(config, today, collection_no, metadata["name"])
    # 產生縮圖路徑
    filename_prefix = f"{collection_no}-{metadata['name']}"
    small_path = f"bears/{today}/thumbs/{filename_prefix}-s.png"
    medium_path = f"bears/{today}/thumbs/{filename_prefix}-m.png"
    record = {
        "name": metadata["name"],
        "date": today,
        "checkIn": today.replace("-", "") + f"-{daily_index:02d}",
        "collectionNo": collection_no,
        "title": metadata["title"],
        "series": metadata["series"],
        "birthday": today,
        "personality": metadata["personality"],
        "quote": metadata["quote"],
        "img": img_path,
        "imgS": small_path,
        "imgM": medium_path,
    }
    # 風格（向後相容：同時存 zh 字串與 dict）
    if "style_zh" in metadata:
        record["style"] = metadata["style_zh"]
    if "style" in metadata and isinstance(metadata["style"], dict):
        record["style_en"] = metadata["style"].get("en", "")
    # 質感（如有）
    if metadata.get("texture"):
        tex = metadata["texture"]
        if isinstance(tex, dict):
            record["texture"] = tex.get("zh", "")
            record["texture_en"] = tex.get("en", "")
        else:
            record["texture"] = str(tex)
    return record


def clean_minimax_text(content):
    """移除 MiniMax thinking 區塊與多餘包裝。"""
    if not content:
        return ""

    for pattern in (r"</think>\s*", r"</thinking>\s*"):
        parts = re.split(pattern, content, flags=re.IGNORECASE)
        if len(parts) > 1:
            return parts[-1].strip().strip("\"'")

    # fallback：取最後一段像生圖 prompt 的英文段落
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    for paragraph in reversed(paragraphs):
        lower = paragraph.lower()
        if "bear" in lower and ("kawaii" in lower or "illustration" in lower):
            return paragraph.strip("\"'")

    return content.strip().strip("\"'")


def build_prompt_fallback(name, style, series, personality, title, friend_info=None, conditions=None, texture=None):
    """MiniMax 失敗時的本地 fallback prompt。"""
    # 支援 style 為 dict 或字串
    if isinstance(style, dict):
        style_en = style.get("en", style.get("zh", ""))
    else:
        style_en = style

    # 若 style_en 已經包含 "style" 字樣，不再重複
    # 否則只在短名（<20 字元且無空格）時補 " art style"，避免冗長
    style_lower = style_en.lower()
    if "style" in style_lower or len(style_en) > 20 or " " in style_en.strip():
        style_clause = style_en
    else:
        style_clause = f"{style_en} art style"

    prompt = (
        f"A cute adorable bear character, {title}, "
        f"inspired by {series}, {personality}, "
        f"{style_clause}, dreamy atmosphere"
    )

    # 若有質感，加入質感描述（與風格組合）
    if texture:
        texture_en = texture.get("en", "") if isinstance(texture, dict) else texture
        if texture_en:
            prompt += f", {texture_en}"

    # 若有朋友資訊，加入朋友描述
    if friend_info:
        friend_descs = [f["en"] for f in friend_info["friends"]]
        friends_str = ", ".join(friend_descs)
        scenario = friend_info["scenario"]
        prompt += f", together with {friends_str}, {scenario}"

    # 若有條件，加入條件描述
    if conditions:
        cond_descs = [cond["en"] for cond in conditions.values() if cond]
        if cond_descs:
            prompt += ", " + ", ".join(cond_descs)

    prompt += f", {PROMPT_QUALITY_SUFFIX}"
    return prompt


def is_valid_prompt(content):
    """檢查 MiniMax 回傳的 prompt 是否足夠完整。"""
    if not content or len(content) < MIN_PROMPT_LENGTH:
        return False
    lower = content.lower()
    if "bear" not in lower:
        return False
    # 排除被截斷的片段，如 "A cute k"
    words = content.split()
    if len(words) < 12:
        return False
    if re.search(r"\b[A-Za-z],\s*$", content):
        return False
    return True


def ensure_prompt_suffix(content):
    """補上標準品質尾綴（避免重複）。"""
    lower = content.lower()
    if (
        "soft kawaii style" in lower
        and "16:9" in lower
        and "detailed fur texture" in lower
    ):
        return content
    return f"{content.rstrip('., ')}, {PROMPT_QUALITY_SUFFIX}"


def _call_minimax_prompt(user_content, max_tokens=1024):
    """呼叫 MiniMax Chat API，回傳 (content, finish_reason)。"""
    response = requests.post(
        MINIMAX_CHAT_URL,
        headers={
            "Authorization": f"Bearer {MINIMAX_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MINIMAX_CHAT_MODEL,
            "messages": [
                {"role": "system", "content": PROMPT_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.8,
            "max_completion_tokens": max_tokens,
            "extra_body": {
                "reasoning_split": True,
                "thinking": {"type": "disabled"},
            },
        },
        timeout=60,
    )
    response.raise_for_status()
    body = response.json()

    base_resp = body.get("base_resp", {})
    if base_resp.get("status_code", 0) not in (0, None):
        raise RuntimeError(base_resp.get("status_msg", "MiniMax chat API error"))

    choices = body.get("choices", [])
    if not choices:
        raise RuntimeError("MiniMax chat 無 choices")

    choice = choices[0]
    message = choice.get("message", {})
    content = clean_minimax_text(message.get("content", ""))
    if not content and message.get("reasoning_content"):
        content = clean_minimax_text(message.get("reasoning_content", ""))

    return content, choice.get("finish_reason", "")


def generate_prompt_via_minimax(name, style, series, personality, title, friend_info=None, conditions=None, texture=None):
    """用 MiniMax Chat API 依 metadata 產生英文生圖 prompt。"""
    # 支援 style 為 dict 或字串
    if isinstance(style, dict):
        style_zh = style.get("zh", "")
        style_en = style.get("en", "")
    else:
        style_zh = style
        style_en = style

    user_content = (
        f"Bear name: {name}\n"
        f"Art style: {style_zh} ({style_en})\n"
        f"Series: {series}\n"
        f"Title: {title}\n"
        f"Personality: {personality}"
    )
    if texture:
        texture_zh = texture.get("zh", "") if isinstance(texture, dict) else texture
        texture_en = texture.get("en", "") if isinstance(texture, dict) else texture
        user_content += f"\nTexture: {texture_zh} ({texture_en})"
    if friend_info:
        friend_list = [f"{f['zh']} ({f['en']})" for f in friend_info["friends"]]
        friends_str = ", ".join(friend_list)
        user_content += (
            f"\nFriend info: {friends_str}\n"
            f"Scenario type: {friend_info['scenario_type']}\n"
            f"Scenario: {friend_info['scenario']}"
        )
    if conditions:
        cond_lines = []
        for key, cond in conditions.items():
            if cond:
                cond_lines.append(f"- {key}: {cond['zh']} ({cond['en']})")
        if cond_lines:
            user_content += "\nOptional conditions:\n" + "\n".join(cond_lines)
    log(f"  MiniMax 產生 prompt: {name}")

    try:
        content, finish_reason = _call_minimax_prompt(user_content, max_tokens=1024)

        if not is_valid_prompt(content):
            log(
                f"  MiniMax prompt 不完整 (finish={finish_reason}, "
                f"len={len(content)}): {content[:60]!r}，重試一次"
            )
            content, finish_reason = _call_minimax_prompt(user_content, max_tokens=1536)

        if not is_valid_prompt(content):
            raise RuntimeError(
                f"prompt 仍不完整 (finish={finish_reason}, len={len(content)}): "
                f"{content[:80]!r}"
            )

        content = ensure_prompt_suffix(content)
        log(f"  prompt: {content}")
        return content
    except Exception as e:
        log(f"  MiniMax prompt 生成失敗: {e}，使用 fallback")
        fallback = build_prompt_fallback(name, style, series, personality, title, friend_info, conditions, texture)
        log(f"  prompt (fallback): {fallback}")
        return fallback


def save_minimax_image(data, output_path):
    if data.get("image_urls"):
        urllib.request.urlretrieve(data["image_urls"][0], output_path)
        return
    if data.get("image_base64"):
        output_path.write_bytes(base64.b64decode(data["image_base64"][0]))
        return
    raise ValueError("回應無圖片資料")


def generate_minimax_image(prompt, bear_name, style, output_path, idx, config):
    style_zh = style.get("zh", str(style)) if isinstance(style, dict) else style
    log(f"MiniMax #{idx+1}: {bear_name} ({style_zh}) [{config.minimax_size}]")

    try:
        response = requests.post(
            MINIMAX_IMAGE_URL,
            headers={
                "Authorization": f"Bearer {MINIMAX_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "image-01",
                "prompt": prompt,
                "aspect_ratio": config.minimax_size,
                "response_format": "url",
                "n": 1,
            },
            timeout=120,
        )
        response.raise_for_status()
        body = response.json()
        base_resp = body.get("base_resp", {})
        if base_resp.get("status_code", -1) != 0:
            raise RuntimeError(base_resp.get("status_msg", f"status_code={base_resp.get('status_code')}"))

        save_minimax_image(body.get("data", {}), output_path)
        log(f"  已保存: {output_path.name}")
        return True
    except Exception as e:
        log(f"  MiniMax 生成失敗: {e}")
        return False


def _load_comfy_helpers():
    module_path = COMFY_SCRIPT_DIR / "gen_image.py"
    spec = importlib.util.spec_from_file_location("comfy_gen_image", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"無法載入 gen_image: {module_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return (
        mod.load_workflow,
        mod.patch_workflow,
        mod.submit_workflow,
        mod.poll_status,
        mod.get_output_images,
        mod.download_image,
    )


def generate_comfyui_image(prompt, bear_name, style, output_path, idx, config):
    style_zh = style.get("zh", str(style)) if isinstance(style, dict) else style
    log(f"ComfyUI #{idx+1}: {bear_name} ({style_zh}) [{config.comfy_width}x{config.comfy_height}]")

    if not COMFY_WORKFLOW.exists():
        log("  ComfyUI workflow 不存在，跳過")
        return False

    try:
        load_workflow, patch_workflow, submit_workflow, poll_status, get_output_images, download_image = _load_comfy_helpers()
        wf = load_workflow(str(COMFY_WORKFLOW))
        client_id = str(uuid.uuid4())
        patched, _seed = patch_workflow(
            wf, prompt, width=config.comfy_width, height=config.comfy_height
        )
        result = submit_workflow(config.comfyui_url, patched, client_id)
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            log(f"  ComfyUI 無 prompt_id: {result}")
            return False

        status = poll_status(config.comfyui_url, prompt_id)
        if status.get("status", {}).get("status_str") != "success":
            log("  ComfyUI 生成未成功")
            return False

        images = get_output_images(config.comfyui_url, status)
        if not images:
            log("  ComfyUI 無輸出圖片")
            return False

        download_image(images[0]["url"], str(output_path))
        log(f"  已保存: {output_path.name}")
        return True
    except Exception as e:
        log(f"  ComfyUI 生成失敗: {e}")
        return False


def _load_pil_image():
    """動態載入 Pillow（避免靜態分析器找不到 PIL 套件）。"""
    try:
        return importlib.import_module("PIL.Image")
    except ModuleNotFoundError as e:
        raise ImportError("請安裝 Pillow: pip install Pillow") from e


def generate_thumbnails(source_path, today, collection_no, name):
    """生成小圖和中圖縮圖

    Args:
        source_path: 原始圖片路徑
        today: 日期
        collection_no: 館藏編號
        name: 熊熊名字

    Returns:
        (small_path, medium_path): 小圖和中圖的路徑
    """
    Image = _load_pil_image()

    thumbs_dir = PROJECT_DIR / "bears" / today / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    small_size = (100, 100)
    medium_size = (400, 225)

    filename_prefix = f"{collection_no}-{name}"
    small_path = thumbs_dir / f"{filename_prefix}-s.png"
    medium_path = thumbs_dir / f"{filename_prefix}-m.png"

    with Image.open(source_path) as img:
        small_img = img.copy()
        small_img.thumbnail(small_size, Image.LANCZOS)
        small_img.save(small_path, "PNG")
        small_img.close()

        medium_img = img.copy()
        medium_img.thumbnail(medium_size, Image.LANCZOS)
        medium_img.save(medium_path, "PNG")
        medium_img.close()

    return (
        str(small_path.relative_to(PROJECT_DIR)).replace("\\", "/"),
        str(medium_path.relative_to(PROJECT_DIR)).replace("\\", "/"),
    )


def add_bears_to_json(new_bears):
    data = load_json(BEARS_JSON)
    data["bears"].extend(new_bears)
    data["last_updated"] = get_today()
    save_json(BEARS_JSON, data)
    log("已更新 bears.json")


def step_generate_images(bear_names, styles, today, config, comfyui_online):
    """步驟 4：先產 metadata → MiniMax 產 prompt → 生圖到暫存目錄"""
    today_dir = config.temp_dir / today
    today_dir.mkdir(parents=True, exist_ok=True)

    log(
        f"配送計畫: ComfyUI {config.comfy_count} 張 + MiniMax {config.minimax_count} 張 "
        f"（ComfyUI {'在線' if comfyui_online else '離線'}）"
    )

    generated = []
    slot = 0
    collection_no = get_max_collection_no() + 1

    for i in range(config.comfy_count):
        name, style = bear_names[i], styles[i]
        metadata = prepare_bear_metadata(name, style)
        filename = bear_filename(collection_no, name)
        log(
            f"  No.{collection_no} metadata: title={metadata['title']}, series={metadata['series']}, "
            f"personality={metadata['personality']}, texture={metadata.get('texture')}, "
            f"conditions={metadata.get('conditions')}"
        )
        prompt = generate_prompt_via_minimax(
            metadata["name"],
            metadata["style"],
            metadata["series"],
            metadata["personality"],
            metadata["title"],
            metadata.get("friend_info"),
            metadata.get("conditions"),
            metadata.get("texture"),
        )
        output = today_dir / filename

        ok = False
        if comfyui_online:
            ok = generate_comfyui_image(prompt, name, style, output, slot, config)
        if not ok:
            if comfyui_online:
                log(f"  ComfyUI 無效，改用 MiniMax: {name}")
            ok = generate_minimax_image(prompt, name, style, output, slot, config)

        if ok:
            generated.append({
                "name": name,
                "style": style,
                "collection_no": collection_no,
                "filename": filename,
                "temp_path": output,
                "source": "comfy_or_fallback",
                "metadata": metadata,
                "prompt": prompt,
            })
            collection_no += 1
            slot += 1

    for i in range(config.comfy_count, config.total_count):
        name, style = bear_names[i], styles[i]
        metadata = prepare_bear_metadata(name, style)
        filename = bear_filename(collection_no, name)
        log(
            f"  No.{collection_no} metadata: title={metadata['title']}, series={metadata['series']}, "
            f"personality={metadata['personality']}, texture={metadata.get('texture')}, "
            f"conditions={metadata.get('conditions')}"
        )
        prompt = generate_prompt_via_minimax(
            metadata["name"],
            metadata["style"],
            metadata["series"],
            metadata["personality"],
            metadata["title"],
            metadata.get("friend_info"),
            metadata.get("conditions"),
            metadata.get("texture"),
        )
        output = today_dir / filename
        if generate_minimax_image(prompt, name, style, output, slot, config):
            generated.append({
                "name": name,
                "style": style,
                "collection_no": collection_no,
                "filename": filename,
                "temp_path": output,
                "source": "minimax",
                "metadata": metadata,
                "prompt": prompt,
            })
            collection_no += 1
            slot += 1

    log(f"共生成 {len(generated)} 張圖片於 {today_dir}")
    return generated


def step_update_museum(generated, today, config):
    """步驟 5：複製圖片到博物館並更新 bears.json"""
    museum_dir = config.dest_dir / today
    museum_dir.mkdir(parents=True, exist_ok=True)

    new_bears = []

    for item in generated:
        filename = item["filename"]
        dest = museum_dir / filename
        shutil.copy2(item["temp_path"], dest)
        log(f"已複製: {filename} → {dest}")
        
        # 生成縮圖
        try:
            small_path, medium_path = generate_thumbnails(
                dest, today, item["collection_no"], item["metadata"]["name"]
            )
            log(f"  已生成縮圖: {small_path}, {medium_path}")
        except Exception as e:
            log(f"  縮圖生成失敗: {e}")
        
        new_bears.append(make_bear_record(
            item["metadata"], today, item["collection_no"], len(new_bears) + 1, config
        ))

    if new_bears:
        add_bears_to_json(new_bears)
        log(f"新增 {len(new_bears)} 隻熊熊")
    else:
        log("沒有新增熊熊")

    return new_bears


def parse_size(value):
    if "x" in value.lower():
        w, h = value.lower().split("x", 1)
        return int(w), int(h)
    raise argparse.ArgumentTypeError("尺寸格式應為 WIDTHxHEIGHT，例如 1600x912")


def main(config):
    today = get_today()
    init_log_file(today)

    log("===== 熊熊每日配送計畫 =====")
    if config.mode:
        log(f"模式: {config.mode}")
    log(f"今日日期: {today}")
    log(f"暫存目錄: {config.temp_dir / today}")
    log(f"目的目錄: {config.dest_dir / today}")

    log("\n--- 步驟 1: 檢查系統狀態 ---")
    comfyui_online = check_comfyui(config)
    log(f"ComfyUI: {'✓ 在線' if comfyui_online else '✗ 離線'}")

    log("\n--- 步驟 2: 取得熊熊名字和風格 ---")
    num_bears = config.total_count
    bear_names = get_next_bear_names(num_bears)

    if config.mode == "step2":
        styles, _ = peek_styles(num_bears)
        log(f"風格隨機抽選（不輪流）")
        log(f"配送隻數: ComfyUI {config.comfy_count} + MiniMax {config.minimax_count} = {num_bears}")
        log(f"熊熊 ({len(bear_names)}): {bear_names}")
        log(f"風格 ({len(styles)}): {[s.get('zh', s) if isinstance(s, dict) else s for s in styles]}")
        for i, (name, style) in enumerate(zip(bear_names, styles), start=1):
            kind = "ComfyUI" if i <= config.comfy_count else "MiniMax"
            style_zh = style.get("zh", str(style)) if isinstance(style, dict) else style
            log(f"  #{i} [{kind}]: {name} / {style_zh}")
        log("\n[step2] 預覽完成，未生圖、未更新詞彙輪流")
        return

    styles = get_next_styles(num_bears)
    style_zhs = [s.get("zh", str(s)) if isinstance(s, dict) else s for s in styles]
    log(f"熊熊: {bear_names}")
    log(f"風格: {style_zhs}")

    log("\n--- 步驟 3: 準備目錄 ---")
    (config.temp_dir / today).mkdir(parents=True, exist_ok=True)
    (config.dest_dir / today).mkdir(parents=True, exist_ok=True)

    log("\n--- 步驟 4: 生成圖片 ---")
    generated = step_generate_images(bear_names, styles, today, config, comfyui_online)

    if config.mode == "step4":
        log("\n[step4] 生圖完成，圖片保留於暫存目錄，未複製、未更新 bears.json")
        return

    log("\n--- 步驟 5: 更新熊熊博物館 ---")
    new_bears = step_update_museum(generated, today, config)

    if config.mode == "step5":
        log("\n[step5] 博物館更新完成，未 commit、未部署")
        return

    if not new_bears:
        log("\n沒有新增熊熊，跳過 commit 與部署")
        return

    log("\n--- 步驟 6: Git Commit ---")
    run_cmd(f"cd {PROJECT_DIR} && git add bears.json bears/ vocabulary/style-rotation.json vocabulary/daily-delivery.py vocabulary/bear-conditions.json vocabulary/bear-textures.json")
    run_cmd(f'cd {PROJECT_DIR} && git commit -m "新增 {today} 熊熊"')
    run_cmd(f"cd {PROJECT_DIR} && git push")
    log("Git push 完成")

    log("\n--- 步驟 7: 部署到 Cloudflare Pages ---")
    run_cmd(
        f"cd {PROJECT_DIR} && npx wrangler pages deploy . "
        f"--project-name kumaweb --branch main --no-install-skills --commit-dirty=true"
    )

    log("\n===== 完成 =====")
    log("到 https://kumaweb.pages.dev 觀看結果")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="熊熊每日配送")
    parser.add_argument(
        "--mode",
        default="",
        choices=["", "step2", "step4", "step5"],
        help="step2=僅預覽, step4=僅生圖, step5=到更新博物館",
    )
    parser.add_argument("--temp-dir", default=str(DEFAULT_TEMP_DIR), help="圖片暫存目錄")
    parser.add_argument("--dest-dir", default=str(DEFAULT_DEST_DIR), help="博物館圖片目的目錄")
    parser.add_argument("--minimax-size", default="16:9", help="MiniMax 圖片比例，如 16:9 或 1:1")
    parser.add_argument("--comfy-size", default="1600x912", type=parse_size, help="ComfyUI 圖片尺寸 WIDTHxHEIGHT")
    parser.add_argument("--comfy-count", type=int, default=3, help="ComfyUI 配送隻數")
    parser.add_argument("--minimax-count", type=int, default=3, help="MiniMax 配送隻數")
    parser.add_argument("--comfyui-url", default=COMFYUI_URL, help="ComfyUI server URL")
    args = parser.parse_args()

    comfy_w, comfy_h = args.comfy_size
    config = DeliveryConfig(
        temp_dir=args.temp_dir,
        dest_dir=args.dest_dir,
        minimax_size=args.minimax_size,
        comfy_width=comfy_w,
        comfy_height=comfy_h,
        comfy_count=args.comfy_count,
        minimax_count=args.minimax_count,
        comfyui_url=args.comfyui_url,
        mode=args.mode,
    )
    main(config)
