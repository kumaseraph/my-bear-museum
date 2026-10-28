#!/usr/bin/env python3
"""
熊熊每日配送計畫 - 自動化配送腳本

步驟：
1. 檢查 ComfyUI 狀態
2. 取得熊熊名字與風格（最近 3 天不抽 / 14 天降權 / 同日不重複）
3. 準備目錄
4. 產生 metadata → Hermes API 產英文 prompt → 生圖（ComfyUI + MiniMax，Comfy 失敗改 MiniMax）
   - 提示詞生成失敗時：寫錯誤紀錄 + 發通知，該隻不產圖（不使用模板 C 補位）
   - 全部失敗時：中止配送，不寫 bears.json、不 commit、不 deploy，非 0 exit
5. 複製圖片並更新 bears.json
6. Git commit + push
7. 部署 Cloudflare Pages
"""

import argparse
import ast
import base64
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
import requests
import urllib.request
import urllib.error
from datetime import datetime, date, timedelta
from pathlib import Path
import random

# ===== 設定 =====
PROJECT_DIR = Path("/home/fjj04/my-bear-museum")
BEARS_JSON = PROJECT_DIR / "bears.json"
DEFAULT_TEMP_DIR = PROJECT_DIR / "bears"
DEFAULT_DEST_DIR = PROJECT_DIR / "bears"
VOCAB_DIR = PROJECT_DIR / "vocabulary"
LOG_DIR = VOCAB_DIR / "logs"
ERROR_LOG_DIR = LOG_DIR / "errors"
BEAR_NAMING = VOCAB_DIR / "bear-naming.json"
STYLE_ROTATION = VOCAB_DIR / "style-rotation.json"
BEAR_QUOTES = VOCAB_DIR / "bear-quotes.json"
WORLD_BUILDING = VOCAB_DIR / "world-building.json"
VOCABULARY = VOCAB_DIR / "vocabulary.json"
BEAR_FRIENDS = VOCAB_DIR / "bear-friends.json"
BEAR_CONDITIONS = VOCAB_DIR / "bear-conditions.json"
BEAR_TEXTURES = VOCAB_DIR / "bear-textures.json"
BEAR_BACKGROUNDS_PATH = VOCAB_DIR / "bear-backgrounds.json"

COMFYUI_URL = "http://fjjhomei9.fjj.home:8188"
COMFY_WORKFLOW = Path("/home/fjj04/comfyui/Flux.2-Klein-文生图_API.json")
COMFY_SCRIPT_DIR = Path("/home/fjj04/.hermes/skills_custom/comfyui-gen-image/scripts")

# ===== 提示詞生成後端（本機 Hermes API Server）=====
HERMES_API_URL = "http://127.0.0.1:8642/v1/chat/completions"
HERMES_MODEL = "hermes-agent"
HERMES_TIMEOUT = 300

# 金鑰來源（依序合併，後者覆寫前者）
HERMES_ENV_FILES = [
    Path("/home/fjj04/.hermes/.env"),
    Path("/home/fjj04/my-bear-museum/.env"),
]

# Discord 通知目標：熊熊博物館 thread（cron deliver 同一個）
DISCORD_API_BASE = "https://discord.com/api/v10"
NOTIFY_CHANNEL_ID = "1512439251940151397"

MINIMAX_IMAGE_URL = "https://api.minimax.io/v1/image_generation"

# ===== 選樣參數 =====
RECENT_EXCLUDE_DAYS = 3      # 最近 N 天用過的風格 → 不抽
RECENT_DOWNWEIGHT_DAYS = 14  # 最近 N 天用過的風格 → 降權
DOWNWEIGHT_FACTOR = 0.35     # 降權後的權重倍率
PROMPT_MAX_ATTEMPTS = 2      # 提示詞生成/驗證失敗的重試上限
PROMPT_RETRY_DELAY = 2       # 重試間隔（秒）

# ===== 品質尾綴（移除 soft kawaii style，其餘保留）=====
PROMPT_QUALITY_SUFFIX = (
    "wild animal anatomy, four-legged stance, horizontal composition 16:9, "
    "high quality illustration, detailed fur texture, "
    "absolutely no text, absolutely no letters, absolutely no words, "
    "absolutely no writing, no readable characters, no alphabet, "
    "no labels on jars, no signs, no book titles, no posters, "
    "no newspaper, no menu text, no scroll text, no card text, "
    "decorative shapes and symbols only, not actual letters"
)

MIN_PROMPT_WORDS = 150       # 最少英文單字數（非字元數）
MIN_PROMPT_LENGTH = 80       # 最少字元數（粗略的截斷檢查）

# 四隻腳難以驗證的構圖（腳不入鏡或只見剪影）
FOUR_LEGS_UNVERIFIABLE_COMPOSITIONS = {
    "close-up portrait",
    "macro detail shot of paws and face",
    "silhouette against bright light",
}

# 新增構圖的英文描述片段（避免直接拼接英文名造成語意奇怪）
COMPOSITION_DESCRIPTIONS = {
    "top-down bird's eye view":
        "seen from directly above, the bear small on the ground below, the "
        "surrounding terrain spreading out into a patterned field of shapes",
    "worm's eye view looking up":
        "seen from a low angle looking up, the bear looming large against the "
        "open sky, the clouds and treetops curving away overhead",
    "silhouette against bright light":
        "darkly silhouetted against a brilliant backlight, the outline of a "
        "four-legged bear clearly readable",
    "split-panel story sequence":
        "arranged as a split-panel story sequence, the same bear appearing in "
        "several separate moments of one continuous adventure",
    "over-the-shoulder shot":
        "seen over the bear's shoulder, the animal at the near edge of the "
        "frame with the wider scene unfolding in the distance",
    "reflection mirrored in water":
        "mirrored in still water, the whole scene repeated as a soft inverted "
        "reflection beneath the bank",
    "macro detail shot of paws and face":
        "extreme close detail of the bear's paws, claws and face, individual "
        "fur strands filling the frame",
    "vignette framed portrait":
        "framed by a dark oval vignette, the bear at the centre of an old "
        "painted portrait",
}

PROMPT_SYSTEM = """You are an expert at writing English text-to-image prompts for a museum of characterful wild bears.

Given bear metadata in Traditional Chinese, write ONE detailed English image generation prompt.

Rules:
- Infer fur color and scene from the bear name, personality, series, and title
- Translate the art style to English (e.g. 油畫=oil painting, 霓虹燈=neon light, 水彩=watercolor, 故障藝術=glitch art)
- Describe a vivid scene with atmosphere and magical lighting
- Write as a single flowing English paragraph, at least 150 words, ideally 180-250 words
- Do NOT include Chinese characters or the raw Chinese bear name
- Do NOT include quality tags like "16:9", "detailed fur texture" or "wild animal anatomy" (added separately)
- NEVER use the words "kawaii", "mascot", "chibi", "cute" or "anthropomorphic" anywhere in the prompt - they push the image toward a humanised standing character
- Output ONLY the prompt text, no quotes, no explanation, no markdown, no thinking

HARD CONSTRAINTS - the bear must read as a bear and as a quadruped:
- The bear MUST have exactly FOUR legs (two front paws + two hind legs) - never five legs, never three legs
- The bear must look like a bear: round bear ears, round teddy bear face, fluffy bear paws - not a rabbit, cat, fox, or other animal
- The image must contain NO readable text: no letters, no words, no writing, no readable characters, no alphabet, no signs, no book titles, no posters, no newspaper, no menu text, no scroll text, no card text, no labels. Use decorative shapes, symbols, glyphs, runes, ornamental patterns or abstract designs instead of actual letters

ANTI-ANTHROPOMORPHIC POSE RULES - these matter as much as the four-leg rule:
- The bear is a QUADRUPED animal. It is always on all four legs - standing, walking, resting or crouching on all fours. Never two legs, never a bipedal mascot pose
- NEVER describe the bear as standing upright, sitting upright, perching, waving, holding an object in its paws like a human, presenting an object, hugging, clapping, pointing, or carrying something on two legs
- Do not use the verbs stand, sit, perch, hold, carry, wave, reach, lift, offer, present, hug, clap, point, peer, gaze or crouch for the bear
- When the bear interacts with a prop, describe it as carried in its mouth, worn on its body, or lying on the ground beside it
- Use four-legged wording instead: "on all four paws", "on all fours", "walks on all fours", "rests on all fours", "nuzzles the...", "sniffs the...", "paws at the..."
- The four-legged animal and the bear-face features must be stated together in the same paragraph so the model cannot read one without the other

COMPOSITION - the provided composition describes the camera angle:
- Close-up portrait: the face and shoulders fill the frame
- Mid-shot: the bear fills most of the frame, head to knees visible
- Full body: the entire bear is visible from nose to paws
- Environmental wide shot: a wide view where the landscape dominates and the bear is small
- "bear as observer in vast scene": the bear is the supporting character and the scene is the subject
  - the bear occupies roughly one eighth to one fifth of the frame and is not the focal point
  - the scenery takes up most of the image (grand landscape, wide-angle viewpoint)
  - example elements:
    - "a small bear on all four paws at a cliff edge, vast misty mountains beyond"
    - "a tiny bear silhouette against a brilliant sunset over the ocean"
    - "a small bear resting on all fours on a windowsill, magical forest visible through the window"
    - "a tiny bear walking on all fours through an endless lavender field under starry sky"
    - "a small bear on all four paws on a giant flower petal, surrounded by a dreamy garden"
  - the bear must still read clearly as a bear (four legs, round ears, bear face), never as an ambiguous blob
  - it is still "one clearly drawn bear" inside a larger scene
- Top-down bird's eye view: the camera looks straight down from above
- Worm's eye view looking up: the camera is on the ground looking up at the bear against the sky
- Silhouette against bright light: the bear is a dark shape in front of a brilliant light source
- Split-panel story sequence: the image is divided into panels showing successive moments
- Over-the-shoulder shot: the bear is at the near edge of the frame and the scene opens up beyond it
- Reflection mirrored in water: the scene is mirrored in still water
- Macro detail shot of paws and face: an extreme close-up of paws and face, no legs in frame
- Vignette framed portrait: an oval dark frame surrounds the bear like an old portrait
- Vary foreground/background elements: avoid repetitive elements (e.g. always having two trees on both sides)
- Rotate between different scene types: indoor (cozy attic, library, kitchen, cafe, treehouse, art studio), outdoor (city rooftop, harbor, mountain summit, forest path, beach cliff, train window, autumn park), abstract (floating cloud island, inside music box, on giant book page, candy kingdom, between stars, inside snow globe, giant teacup)
- Use provided background and composition metadata to create unique scenes

TEXT-FREE SCENE CRAFT:
- Default: PREFER scenes WITHOUT text elements (no signs, no readable books, no posters with words, no newspapers)
- If a text-like element is essential for the scene (book, signboard, scroll, note, label, menu, letter, card):
  - Use decorative symbols, shapes, glyphs, runes, or abstract markings INSTEAD of actual letters
  - Phrase as: "with a weathered signboard showing decorative symbols", "an open book with rune-like markings", "a parchment with abstract glyphs", "a card with decorative illustrations"
  - The prop lies on the ground beside the bear, is worn on its body, or is carried in its mouth
  - NEVER include these words in the prompt: "text", "letters", "words", "writing", "alphabet", "readable text", "book title", "sign text" - these trigger gibberish attempts
  - Safe alternatives to use: "symbols", "markings", "glyphs", "runes", "decorative pattern", "abstract design", "ornamental shapes", "illustrations"

LAYERING:
- 50% of the time, add a texture layer (glass, metal, wood, stone, plush, cotton, silk, wool, clay, gold leaf, etc.) provided in the metadata
- Texture should be combined with style naturally: e.g. "oil painting style with gold leaf texture", "watercolor painting with rough stone surface", "3D rendered style with glass-like translucent quality"
- Texture describes material/tactile quality (how it FEELS), style describes atmosphere/mood (how it LOOKS) - both should layer harmoniously
- 60% of the time, add 1-3 friends to the scene based on the bear's personality and quote
- Friends can be: human child, small dog, cat, rabbit, hamster, duckling, teddy bear toy, or small doll
- Scenarios for friends: adventure (forest, beach, mountain camping, cave, stargazing), play (bubbles, kite, swings, soccer, snowman), outing (picnic, market, train, boat, blossoms, skiing)
- The bear stays on all four legs beside its friends; the friends may stand or sit, the bear does not
- Describe the friendship and interaction between characters without making the bear human
- Optional conditions can be added based on probability:
  - Weather: sunny, rainy, snowy, typhoon, rainbow, foggy morning, thunderstorm, sandstorm, drizzle, frost, aurora
  - Time: dawn, morning, noon, sunset, starry night, moonlight, blue hour, midnight, weekend afternoon
  - Holiday: New Year, Lunar New Year, Mid-Autumn, Halloween, Christmas, Valentine's, Birthday, Thanksgiving
  - Props: glasses, balloons, umbrella, crown, backpack, guitar, scarf, microphone, kite, book, lantern, knitted hat
  - Emotions: laughing, shy smile, curious, surprised, thoughtful, excited, eager, content, mischievous, tender
- Multiple conditions can combine: e.g. "in snowy weather at dusk, a small guitar lying on the ground beside it"
- When conditions are present, weave them naturally into the scene description (weather sets atmosphere, time affects lighting, props lie beside the bear or are worn on its body, emotions shape facial expression)
- The image should reflect all provided conditions as a coherent whole, not as a checklist

QUOTE LINKAGE:
- The metadata includes the bear's own words (the quote), written in Traditional Chinese
- Do not quote those words and do not write any Chinese characters in the prompt
- Instead, translate the feeling of the quote into the scene: the bear's expression, the light, the weather and the atmosphere must express the mood of that quote
- The picture and the quote must feel like they belong to the same bear"""


class PromptGenerationError(Exception):
    """提示詞生成或驗證失敗 — 必須寫入錯誤紀錄並通知，不可靜默退回模板 C。"""


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
        dry_run=False,
        allow_fallback=False,
        notify=True,
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
        self.dry_run = dry_run
        self.allow_fallback = allow_fallback
        self.notify = notify

    @property
    def total_count(self):
        return self.comfy_count + self.minimax_count


_log_file = None


def init_log_file(today, dry_run=False):
    """dry-run 使用獨立 log 檔，避免污染正式配送歷史。"""
    global _log_file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log_file = LOG_DIR / (f"dryrun-{today}.log" if dry_run else f"{today}.log")


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if _log_file is not None:
        with open(_log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def log_block(title, body):
    """在當日 log 印出醒目區塊。"""
    bar = "!" * 72
    text = f"\n{bar}\n!!! {title}\n{body}\n{bar}"
    print(text, flush=True)
    if _log_file is not None:
        with open(_log_file, "a", encoding="utf-8") as f:
            f.write(text + "\n")


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


def load_bear_backgrounds():
    """載入 bear-backgrounds.json，提供背景池與構圖/背景機率表。

    缺少檔案或欄位時回傳安全預設值，避免影響生圖流程。
    """
    if BEAR_BACKGROUNDS_PATH.exists():
        with open(BEAR_BACKGROUNDS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"backgrounds": {}, "composition_probability": {}, "background_probability": {}}


BEAR_BACKGROUNDS = load_bear_backgrounds()


def check_comfyui(config):
    try:
        resp = requests.get(f"{config.comfyui_url}/system_stats", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def get_today():
    return date.today().strftime("%Y-%m-%d")


# ===== 金鑰管理（§3.3）=====

def load_env_file(path):
    """讀取 KEY=VALUE 格式的 .env 檔，回傳 dict。

    純 Python 解析：支援 # 註解與空行，value 保留原字串不做 shell 展開。
    """
    result = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return result

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            result[key] = value
    return result


_SECRET_CACHE = {}


def get_secret(name):
    """依優先序取得金鑰。

    來源順序：/home/fjj04/.hermes/.env → /home/fjj04/my-bear-museum/.env
    （後者作為覆寫來源）。找不到回傳 None。

    ⚠ 不可印出金鑰的值、長度或前綴。
    """
    if name in _SECRET_CACHE:
        return _SECRET_CACHE[name]

    merged = {}
    for env_path in HERMES_ENV_FILES:
        merged.update(load_env_file(env_path))

    value = merged.get(name) or None
    _SECRET_CACHE[name] = value
    return value


# ===== 提示詞驗證（§3.6）=====

FORBIDDEN_ZH = re.compile(r"[一-鿿]")

# 四隻腳偵測：模型不一定用 "four legs"，常見三種等義表述：
#   (a) "exactly FOUR legs" / "all four paws"
#   (b) "two front paws ... two hind legs"
#   (c) "on all four paws"
FOUR_LEGS = re.compile(
    r"\b(?:all\s+)?four(?:\s+\w+){0,3}?\s+(?:legs?|paws?|limbs?)\b"
    r"|\b(?:legs?|paws?|limbs?)\b[^.]{0,30}?\bexactly\s+four\b"
    r"|\bexactly\s+four\b"
    r"|\b(?:two|both|all)\s+(?:front\s+|hind\s+|back\s+|rear\s+)?(?:legs?|paws?|limbs?)\b"
    r"[^.]{0,140}?\b(?:two|both|all)\s+(?:front\s+|hind\s+|back\s+|rear\s+)?(?:legs?|paws?|limbs?)\b",
    re.I,
)

# 熊臉特徵偵測
BEAR_FACE = re.compile(
    r"round\w*\s+(?:bear\s+)?(?:teddy[- ]bear\s+)?(?:ears?|face|muzzle|snout)"
    r"|round[- ]eared"
    r"|fluffy\s+bear\s+paws?"
    r"|soft\s+teddy[- ]bear\s+face"
    r"|bear\s+(?:ears?|muzzle|paws?|snout)",
    re.I,
)


def clean_model_text(text):
    """去除 thinking 區塊、markdown 包裝、引號與多餘標籤。"""
    if not text:
        return ""

    t = text
    t = re.sub(r"<think>.*?</think>\s*", "", t, flags=re.S | re.I)
    t = re.sub(r"^.*?</think>\s*", "", t, flags=re.S | re.I)
    t = re.sub(r"^```[a-zA-Z]*[ \t]*\r?\n?", "", t)
    t = re.sub(r"\r?\n?```\s*$", "", t)
    t = t.strip()

    if len(t) >= 2 and t[0] in "\"'" and t[-1] in "\"'":
        t = t[1:-1].strip()

    t = re.sub(r"^(prompt|image prompt|text)\s*:\s*", "", t, flags=re.I)
    return t.strip()


def validate_prompt(text):
    """檢查模型輸出的提示詞是否可用。

    回傳 (ok, reasons, warnings)。reasons 非空 → 需重試；
    warnings 只記錄不阻擋（四隻腳未命中時）。
    """
    reasons, warnings = [], []

    if not text or not text.strip():
        return False, ["空白輸出"], warnings

    if FORBIDDEN_ZH.search(text):
        reasons.append("輸出含中文字元")
    if "<think>" in text or "</think>" in text:
        reasons.append("輸出含 thinking 區塊")
    if "```" in text:
        reasons.append("輸出含 markdown 程式碼區塊")

    blocks = [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    if len(blocks) > 1:
        reasons.append(f"輸出為 {len(blocks)} 段，應為單一段落")

    words = len(text.split())
    if words < MIN_PROMPT_WORDS:
        reasons.append(f"英文單字數不足 {MIN_PROMPT_WORDS}（{words}）")
    if len(text) < MIN_PROMPT_LENGTH:
        reasons.append(f"長度不足 {MIN_PROMPT_LENGTH} 字元（{len(text)}）")
    if "bear" not in text.lower():
        reasons.append("輸出未提及 bear")
    if not BEAR_FACE.search(text):
        reasons.append("輸出未寫出熊臉特徵（round bear ears / teddy bear face / fluffy bear paws）")
    if not FOUR_LEGS.search(text):
        warnings.append("未明確寫出四隻腳（four legs / four paws）")

    return (not reasons), reasons, warnings


def ensure_prompt_suffix(content):
    """補上標準品質尾綴（避免重複附加）。"""
    lower = content.lower()
    if (
        "wild animal anatomy" in lower
        and "16:9" in lower
        and "detailed fur texture" in lower
    ):
        return content
    return f"{content.rstrip('., ')}, {PROMPT_QUALITY_SUFFIX}"


def ensure_four_legs_clause(content, composition=None):
    """四隻腳未命中時，補一句四足描述（特寫/剪影構圖除外）。"""
    if composition in FOUR_LEGS_UNVERIFIABLE_COMPOSITIONS:
        return content
    if FOUR_LEGS.search(content):
        return content
    return (
        f"{content.rstrip('., ')}, the bear is a quadruped on all four legs, "
        "two front paws and two hind legs"
    )


# ===== 提示詞生成後端（§3.2）=====

def call_hermes_prompt(system, user, timeout=None):
    """呼叫本機 Hermes API Server，回傳 (content, usage)。

    失敗時拋出 PromptGenerationError，訊息中不含金鑰。
    """
    api_key = get_secret("API_SERVER_KEY")
    if not api_key:
        raise PromptGenerationError(
            "ERROR: 找不到 API_SERVER_KEY（檢查 /home/fjj04/.hermes/.env）"
        )

    payload = json.dumps({
        "model": HERMES_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 2048,
        "temperature": 0.8,
    }).encode("utf-8")

    request = urllib.request.Request(
        HERMES_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout or HERMES_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:200]
        raise PromptGenerationError(f"HTTP {e.code}: {detail}") from e
    except Exception as e:
        raise PromptGenerationError(f"{type(e).__name__}: {e}") from e

    try:
        message = body["choices"][0]["message"]
    except Exception as e:
        raise PromptGenerationError(
            f"回應格式異常: {str(body)[:200]}"
        ) from e

    return message.get("content") or "", body.get("usage", {})


def build_user_content(name, style, series, personality, title, quote=None,
                       friend_info=None, conditions=None, texture=None,
                       background_scene=None, composition=None):
    """組裝送給模型的 user content。"""
    if isinstance(style, dict):
        style_zh = style.get("zh", "")
        style_en = style.get("en", "")
    else:
        style_zh = style
        style_en = style

    lines = [
        f"Bear name: {name}",
        f"Art style: {style_zh} ({style_en})",
        f"Series: {series}",
        f"Title: {title}",
        f"Personality: {personality}",
    ]

    if quote:
        lines.append(
            "Quote (the bear's own words in Traditional Chinese; do not write "
            "these words in the prompt, but let the picture express this mood): "
            f"{quote}"
        )

    if texture:
        texture_zh = texture.get("zh", "") if isinstance(texture, dict) else texture
        texture_en = texture.get("en", "") if isinstance(texture, dict) else texture
        lines.append(f"Texture: {texture_zh} ({texture_en})")

    if friend_info:
        friend_list = [f["en"] for f in friend_info["friends"]]
        lines.append("Friend info: " + ", ".join(friend_list))
        lines.append(f"Scenario: {friend_info['scenario']}")

    if conditions:
        cond_lines = []
        for key, cond in conditions.items():
            if cond:
                cond_lines.append(f"- {key}: {cond['zh']} ({cond['en']})")
        if cond_lines:
            lines.append("Optional conditions:\n" + "\n".join(cond_lines))

    if background_scene:
        lines.append(f"Background scene: {background_scene}")
    if composition:
        lines.append(f"Composition: {composition}")

    return "\n".join(lines)


def generate_prompt_via_model(name, style, series, personality, title, quote=None,
                              friend_info=None, conditions=None, texture=None,
                              background_scene=None, composition=None,
                              allow_fallback=False):
    """用 Hermes API 依 metadata 產生英文生圖 prompt。

    回傳 (prompt, info)。info 含 attempts / warnings / fallback_used / elapsed。
    失敗時（且未允許 fallback）拋出 PromptGenerationError。
    """
    user_content = build_user_content(
        name, style, series, personality, title, quote,
        friend_info, conditions, texture, background_scene, composition,
    )
    log(f"  Hermes 產生 prompt: {name}")

    last_error = None
    elapsed = 0.0
    started = time.time()

    for attempt in range(1, PROMPT_MAX_ATTEMPTS + 1):
        t0 = time.time()
        try:
            raw, usage = call_hermes_prompt(PROMPT_SYSTEM, user_content)
            elapsed = time.time() - t0
        except PromptGenerationError as e:
            elapsed = time.time() - t0
            last_error = str(e)
            log(f"    ✗ Hermes 呼叫失敗（第 {attempt}/{PROMPT_MAX_ATTEMPTS} 次，{elapsed:.1f}s）：{last_error}")
        else:
            text = clean_model_text(raw)
            ok, reasons, warnings = validate_prompt(text)
            if ok:
                for warning in warnings:
                    log(f"    ⚠ 提示詞提醒：{warning}")
                text = ensure_four_legs_clause(text, composition)
                text = ensure_prompt_suffix(text)
                text = re.sub(r"\s*\n+\s*", " ", text)
                return text, {
                    "attempts": attempt,
                    "warnings": warnings,
                    "fallback_used": False,
                    "elapsed": elapsed,
                    "usage": usage,
                }
            last_error = "; ".join(reasons)
            log(f"    ✗ 提示詞驗證未通過（第 {attempt}/{PROMPT_MAX_ATTEMPTS} 次，{elapsed:.1f}s）：{last_error}")

        if attempt < PROMPT_MAX_ATTEMPTS:
            time.sleep(PROMPT_RETRY_DELAY)

    info = {
        "attempts": PROMPT_MAX_ATTEMPTS,
        "fallback_used": False,
        "elapsed": elapsed,
        "error": last_error,
    }

    if allow_fallback:
        log("WARNING: 使用模板 C fallback（四隻腳規則不受保證）")
        fallback = build_prompt_fallback(
            name, style, series, personality, title,
            friend_info, conditions, texture,
            background_scene, composition,
        )
        info["fallback_used"] = True
        info["elapsed"] = time.time() - started
        return fallback, info

    raise PromptGenerationError(last_error or "未知錯誤")


# ===== 模板 C（僅在明確允許時使用）=====

FALLBACK_SCENE_DETAIL = (
    "The scene is built in layers of natural light and material: a warm glow brushes across "
    "the foreground, cooler tones settle into the middle distance, and fine detail gathers in "
    "the corners of the frame. Fur is rendered strand by strand with soft shadow, the ground "
    "shows believable weight and grain, and the air drifts with a faint sense of dust or "
    "spattered moisture depending on the weather. Every element stays true to the material it "
    "represents, the palette stays restrained and deliberate, and the whole image reads as one "
    "coherent painted photograph rather than a collage of separate ideas. The bear remains the "
    "clear subject of the frame, placed low and forward so that distance and scale stay "
    "believable, with the environment supporting the animal instead of competing with it for "
    "attention. No lettering appears anywhere in the picture: any object that might normally "
    "bear words is shown only as blank surfaces, carved ornament, woven pattern or abstract "
    "symbol, so the image stays entirely free of readable characters."
)


def build_prompt_fallback(name, style, series, personality, title, friend_info=None,
                          conditions=None, texture=None, background_scene=None,
                          composition=None):
    """模板 C prompt。

    ⚠ 只在明確允許（--allow-fallback）時使用；不得自動呼叫。
    完全英文、無擬人化動詞、含四隻腳與熊臉規則、長度 ≥ 150 詞。
    """
    if isinstance(style, dict):
        style_en = style.get("en", style.get("zh", ""))
        style_mood = style.get("mood", "warm and gentle")
    else:
        style_en = style
        style_mood = "warm and gentle"

    style_lower = style_en.lower()
    if "style" in style_lower or len(style_en) > 20 or " " in style_en.strip():
        style_clause = style_en
    else:
        style_clause = f"{style_en} art style"

    parts = [
        "A round teddy bear character with round bear ears, a round teddy bear face and "
        "fluffy bear paws, on all four paws in a horizontal sixteen-by-nine frame",
        style_clause,
    ]

    if background_scene:
        parts.append(f"set in {background_scene}")

    if composition:
        if composition == "bear as observer in vast scene":
            parts.append(
                "the bear is a small figure within the vast scene, on all four paws among the "
                "immense landscape, the environment dominating the frame while the animal "
                "remains a distinct and clearly readable four-legged bear, wide-angle "
                "panoramic view"
            )
        else:
            description = COMPOSITION_DESCRIPTIONS.get(composition)
            if description:
                parts.append(description)
            else:
                parts.append(f"{composition} composition")

    if texture:
        texture_en = texture.get("en", "") if isinstance(texture, dict) else texture
        if texture_en:
            parts.append(texture_en)

    if conditions:
        cond_descs = [cond["en"] for cond in conditions.values() if cond]
        if cond_descs:
            parts.append(", ".join(cond_descs))

    if friend_info:
        friend_descs = [f["en"] for f in friend_info["friends"]]
        scenario = friend_info["scenario"]
        parts.append(
            f"on all four paws beside {', '.join(friend_descs)}, {scenario}, "
            "the friends beside it while the bear stays on all fours"
        )

    parts.append(f"{style_mood} atmosphere")
    parts.append(FALLBACK_SCENE_DETAIL)
    parts.append(
        "exactly four legs, two front paws and two hind legs, the anatomy of a real wild bear"
    )

    prompt = ", ".join(p for p in parts if p)
    prompt = re.sub(r"\s*\n+\s*", " ", prompt)
    return f"{prompt.rstrip('., ')}, {PROMPT_QUALITY_SUFFIX}"


# ===== 失敗紀錄與通知（§3.4 / §3.5）=====

def notify_discord(message, enabled=True):
    """發 Discord 通知。失敗不讓程式崩潰，回傳 True/False。"""
    if not enabled:
        log("  （--no-notify）略過 Discord 通知")
        return False

    token = get_secret("DISCORD_BOT_TOKEN")
    if not token:
        err = "ERROR: 找不到 DISCORD_BOT_TOKEN"
        print(err, file=sys.stderr, flush=True)
        log(f"  Discord 通知失敗：{err}")
        return False

    try:
        response = requests.post(
            f"{DISCORD_API_BASE}/channels/{NOTIFY_CHANNEL_ID}/messages",
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
            },
            json={"content": message[:2000]},
            timeout=20,
        )
        response.raise_for_status()
        body = response.json()
        log(f"  Discord 通知已送出（message id={body.get('id')}）")
        return True
    except Exception as e:
        print(f"ERROR: Discord 通知失敗: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        log(f"  Discord 通知失敗: {type(e).__name__}: {e}")
        return False


def record_prompt_failure(date_str, collection_no, bear_name, attempts, error,
                          stage="prompt_generation", notify=True):
    """寫 JSONL 錯誤紀錄 + 通知檔 + 發 Discord + 印醒目 log。"""
    ts = datetime.now()
    ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)

    err_path = ERROR_LOG_DIR / f"prompt-error-{date_str}.jsonl"
    record = {
        "timestamp": ts.isoformat(timespec="seconds"),
        "stage": stage,
        "backend": "hermes-api",
        "date": date_str,
        "collection_no": collection_no,
        "bear_name": bear_name,
        "attempts": attempts,
        "error": str(error)[:500],
        "fallback_used": False,
    }
    with open(err_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary = (
        f"時間：{ts.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"熊熊：No.{collection_no} {bear_name}（{date_str}）\n"
        f"階段：{stage}\n"
        f"後端：hermes-api\n"
        f"嘗試次數：{attempts}\n"
        f"錯誤摘要：{str(error)[:300]}\n"
        f"錯誤紀錄檔：{err_path}\n"
        f"處理：本隻未產圖，未使用模板 C 補位。"
    )

    npath = ERROR_LOG_DIR / f"notification-{ts.strftime('%Y%m%d-%H%M%S')}-{collection_no}.md"
    npath.write_text(f"🚨 熊熊提示詞生成失敗\n{summary}\n", encoding="utf-8")

    with open(ERROR_LOG_DIR / "NOTIFICATIONS.md", "a", encoding="utf-8") as f:
        f.write(f"## {ts.strftime('%Y-%m-%d %H:%M:%S')} — No.{collection_no} {bear_name}\n\n")
        f.write(f"- 階段：{stage}\n- 後端：hermes-api\n- 嘗試次數：{attempts}\n")
        f.write(f"- 錯誤：`{str(error)[:300]}`\n")
        f.write(f"- 後備行為：**無**（未退回模板 C，`fallback_used: false`）\n")
        f.write(f"- 錯誤紀錄：`{err_path.name}`\n- 通知檔：`{npath.name}`\n\n")

    log_block("PROMPT GENERATION FAILED", summary)

    if not notify:
        log("  （--no-notify）略過 Discord 通知")
        return err_path, npath

    discord_ok = notify_discord(f"🚨 熊熊提示詞生成失敗\n{summary}", enabled=True)
    if not discord_ok:
        with open(err_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(
                {"timestamp": ts.isoformat(timespec="seconds"), "stage": "discord_notification",
                 "backend": "discord-bot", "date": date_str, "collection_no": collection_no,
                 "bear_name": bear_name, "attempts": attempts,
                 "error": "Discord 通知發送失敗（詳見 stderr）", "fallback_used": False},
                ensure_ascii=False) + "\n")

    return err_path, npath


# ===== 風格與場景選樣（§7）=====

def load_style_history():
    """從 logs/*.log 擷取「日期 → 當日風格清單」，回傳 dict[str, list[str]]。"""
    history = {}
    if not LOG_DIR.exists():
        return history

    for f in sorted(LOG_DIR.glob("*.log")):
        try:
            date.fromisoformat(f.stem)
        except ValueError:
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"風格: (\[.*?\])", txt)
        if not m:
            continue
        try:
            history[f.stem] = list(ast.literal_eval(m.group(1)))
        except Exception:
            try:
                history[f.stem] = list(json.loads(m.group(1).replace("'", '"')))
            except Exception:
                continue
    return history


def _style_weights(styles, exclude, downweight):
    weights = {}
    for s in styles:
        zh = s["zh"]
        if zh in exclude:
            weights[zh] = 0.0
        elif zh in downweight:
            weights[zh] = DOWNWEIGHT_FACTOR
        else:
            weights[zh] = 1.0
    return weights


def _weighted_pick(pool, weights, n, rng):
    picked, bag = [], list(pool)
    while bag and len(picked) < n:
        names = [s["zh"] for s in bag]
        w = [max(weights.get(z, 1.0), 1e-9) for z in names]
        chosen = rng.choices(names, weights=w, k=1)[0]
        bag = [s for s in bag if s["zh"] != chosen]
        picked.append(next(s for s in pool if s["zh"] == chosen))
    return picked


def select_styles(n, target_date, history=None, extra_exclude=None, rng=None):
    """套用「最近 3 天不抽 / 14 天降權 / 同日不重複」規則選出 n 個風格。"""
    rng = rng or random
    rotation = load_json(STYLE_ROTATION)
    styles = rotation.get("styles", [])
    if not styles or n <= 0:
        return []

    if history is None:
        history = load_style_history()

    d = date.fromisoformat(target_date)
    exclude, downweight = set(), set()
    for offset in range(1, RECENT_EXCLUDE_DAYS + 1):
        exclude.update(history.get((d - timedelta(days=offset)).isoformat(), []))
    for offset in range(RECENT_EXCLUDE_DAYS + 1, RECENT_DOWNWEIGHT_DAYS + 1):
        downweight.update(history.get((d - timedelta(days=offset)).isoformat(), []))
    if extra_exclude:
        exclude.update(extra_exclude)

    weights = _style_weights(styles, exclude, downweight)
    pool = [s for s in styles if weights[s["zh"]] > 0]

    if len(pool) < n:
        # 退讓 1：放寬降權（仍不放寬 3 天禁抽）
        weights = _style_weights(styles, exclude, set())
        pool = [s for s in styles if weights[s["zh"]] > 0]

    if len(pool) < n:
        # 退讓 2：放寬禁抽（最後手段）
        weights = {s["zh"]: 1.0 for s in styles}
        pool = list(styles)

    return _weighted_pick(pool, weights, n, rng)


def select_day_scenes(n, rng=None):
    """為當天抽 n 組不重複的背景 + 不重複的構圖。"""
    rng = rng or random
    backgrounds = BEAR_BACKGROUNDS.get("backgrounds", {})
    bg_probs = BEAR_BACKGROUNDS.get("background_probability", {})
    comp_probs = BEAR_BACKGROUNDS.get("composition_probability", {})

    cats = [c for c in backgrounds if backgrounds.get(c)]
    if not cats:
        return [{"background_category": "", "background_scene": "", "composition": "mid-shot"}
                for _ in range(n)]

    used_bg, used_comp = set(), set()
    scenes = []

    for _ in range(n):
        avail_cats = [c for c in cats if not (set(backgrounds[c]) & used_bg)]
        if not avail_cats:
            avail_cats = cats
        cat = rng.choices(
            avail_cats,
            weights=[bg_probs.get(c, 1.0 / len(avail_cats)) for c in avail_cats],
            k=1,
        )[0]
        pool = [s for s in backgrounds[cat] if s not in used_bg] or backgrounds[cat]
        scene = rng.choice(pool)
        used_bg.add(scene)

        avail_comps = [c for c in comp_probs if c not in used_comp]
        if not avail_comps:
            avail_comps = list(comp_probs)
        if avail_comps:
            comp = rng.choices(
                avail_comps,
                weights=[comp_probs[c] for c in avail_comps],
                k=1,
            )[0]
        else:
            comp = "mid-shot"
        used_comp.add(comp)

        scenes.append({
            "background_category": cat,
            "background_scene": scene,
            "composition": comp,
        })

    return scenes


# ===== 熊熊 metadata =====

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
    """預覽即將配送的風格（套用選樣規則，不重複）。"""
    today = get_today()
    history = load_style_history()
    return select_styles(n, today, history=history)


def get_next_styles(n=8):
    """選出 n 個不重複的風格，並更新 style-rotation.json 的 last_updated。"""
    today = get_today()
    history = load_style_history()
    selected = select_styles(n, today, history=history)
    rotation = load_json(STYLE_ROTATION)
    rotation["last_updated"] = today
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

    num_friends = random.randint(1, 3)
    friend_types = friends_data["friend_types"]
    selected_friends = random.sample(friend_types, min(num_friends, len(friend_types)))

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
    """根據 condition_probability 隨機決定要加入哪些條件。"""
    if conditions_data is None:
        conditions_data = load_conditions()

    probability = conditions_data.get("condition_probability", {})

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


def prepare_bear_metadata(name, style, scene=None):
    """生圖前先產生熊熊 metadata，供 prompt 與 bears.json 共用。

    Args:
        name: 熊熊中文名字
        style: 風格 dict {"zh": ..., "en": ..., "mood": ...} 或字串（向後相容）
        scene: 當天抽好的 {"background_category", "background_scene", "composition"}
    """
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

    friend_info = get_friend_info()
    if friend_info:
        metadata["friend_info"] = friend_info

    texture = get_random_texture()
    if texture:
        metadata["texture"] = texture

    conditions = select_conditions()
    active_conditions = {k: v for k, v in conditions.items() if v}
    if active_conditions:
        metadata["conditions"] = active_conditions

    if scene:
        metadata["background_category"] = scene.get("background_category", "")
        metadata["background_scene"] = scene.get("background_scene", "")
        metadata["composition"] = scene.get("composition", "")
    else:
        bg_categories = list(BEAR_BACKGROUNDS.get("backgrounds", {}).keys())
        if bg_categories:
            bg_probs = BEAR_BACKGROUNDS.get("background_probability", {})
            bg_weights = [bg_probs.get(cat, 1.0 / len(bg_categories)) for cat in bg_categories]
            bg_cat = random.choices(bg_categories, weights=bg_weights, k=1)[0]
            metadata["background_category"] = bg_cat
            metadata["background_scene"] = random.choice(BEAR_BACKGROUNDS["backgrounds"][bg_cat])

            comp_options = list(BEAR_BACKGROUNDS.get("composition_probability", {}).keys())
            if comp_options:
                comp_weights = [BEAR_BACKGROUNDS["composition_probability"][c] for c in comp_options]
                metadata["composition"] = random.choices(comp_options, weights=comp_weights, k=1)[0]
            else:
                metadata["composition"] = "mid-shot"

    return metadata


def make_bear_record(metadata, today, collection_no, daily_index, config):
    img_path = bear_img_path(config, today, collection_no, metadata["name"])
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
    if "style_zh" in metadata:
        record["style"] = metadata["style_zh"]
    if "style" in metadata and isinstance(metadata["style"], dict):
        record["style_en"] = metadata["style"].get("en", "")
    if metadata.get("texture"):
        tex = metadata["texture"]
        if isinstance(tex, dict):
            record["texture"] = tex.get("zh", "")
            record["texture_en"] = tex.get("en", "")
        else:
            record["texture"] = str(tex)
    return record


# ===== MiniMax 生圖 =====

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

    api_key = get_secret("MINIMAX_API_KEY")
    if not api_key:
        log("  ERROR: 找不到 MINIMAX_API_KEY")
        return False

    try:
        response = requests.post(
            MINIMAX_IMAGE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
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


# ===== ComfyUI 生圖 =====

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
    """生成小圖和中圖縮圖"""
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


# ===== 配送步驟 =====

def step_generate_prompts(metadata_list, today, collection_no_start, config):
    """為每隻熊熊產生 prompt。

    回傳 (results, failed_count)。results 每筆含 metadata / prompt / info。
    失敗的熊熊不產圖，且不使用模板 C 補位。
    """
    results = []
    failed = 0
    collection_no = collection_no_start

    for metadata in metadata_list:
        try:
            prompt, info = generate_prompt_via_model(
                metadata["name"],
                metadata["style"],
                metadata["series"],
                metadata["personality"],
                metadata["title"],
                metadata.get("quote"),
                metadata.get("friend_info"),
                metadata.get("conditions"),
                metadata.get("texture"),
                metadata.get("background_scene"),
                metadata.get("composition"),
                allow_fallback=config.allow_fallback,
            )
        except PromptGenerationError as e:
            failed += 1
            record_prompt_failure(
                today, collection_no, metadata["name"],
                PROMPT_MAX_ATTEMPTS, e, notify=config.notify,
            )
            results.append({
                "metadata": metadata,
                "collection_no": collection_no,
                "prompt": None,
                "failed": True,
            })
            continue

        log(f"  prompt: {prompt}")
        results.append({
            "metadata": metadata,
            "collection_no": collection_no,
            "prompt": prompt,
            "info": info,
            "failed": False,
        })
        collection_no += 1

    return results, failed


def step_generate_images(prompt_results, today, config, comfyui_online):
    """步驟 4：依已產生的 prompt 生圖到暫存目錄。

    回傳 (generated, failed_count)。failed 的熊熊已在上一步被標記，
    此處直接略過（不使用模板 C 補位）。
    """
    today_dir = config.temp_dir / today
    today_dir.mkdir(parents=True, exist_ok=True)

    log(
        f"配送計畫: ComfyUI {config.comfy_count} 張 + MiniMax {config.minimax_count} 張 "
        f"（ComfyUI {'在線' if comfyui_online else '離線'}）"
    )

    generated = []
    failed = 0
    slot = 0
    for entry in prompt_results:
        if entry["failed"]:
            failed += 1
            continue

        metadata = entry["metadata"]
        name = metadata["name"]
        style = metadata["style"]
        collection_no = entry["collection_no"]
        prompt = entry["prompt"]
        filename = bear_filename(collection_no, name)
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
            slot += 1

    log(f"共生成 {len(generated)} 張圖片於 {today_dir}")
    return generated, failed


def step_update_museum(generated, today, config):
    """步驟 5：複製圖片到博物館並更新 bears.json"""
    museum_dir = config.dest_dir / today
    museum_dir.mkdir(parents=True, exist_ok=True)

    new_bears = []

    for item in generated:
        filename = item["filename"]
        dest = museum_dir / filename
        temp_path = Path(item["temp_path"])
        if temp_path.resolve() != dest.resolve():
            shutil.copy2(temp_path, dest)
            log(f"已複製: {filename} → {dest}")
        else:
            log(f"已生成: {filename} (temp=dest, 略過複製)")

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


def dump_dryrun_report(metadata_list, prompt_results, today, config):
    """把 dry-run 的 metadata 與提示詞寫檔，供驗收。"""
    out_dir = PROJECT_DIR / "trial-20261028"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "dryrun-prompts.txt"

    lines = [
        f"# 熊熊博物館 dry-run 提示詞報告（{today}）",
        f"# 產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# 後端：hermes-api / {HERMES_MODEL}",
        "",
    ]

    for entry in prompt_results:
        metadata = entry["metadata"]
        lines.append("=" * 78)
        lines.append(f"No.{entry['collection_no']} {metadata['name']}")
        lines.append("=" * 78)
        lines.append(f"  風格      : {metadata['style'].get('zh')} ({metadata['style'].get('en')})")
        lines.append(f"  mood      : {metadata['style'].get('mood', '')}")
        lines.append(f"  稱號      : {metadata['title']}")
        lines.append(f"  語錄      : {metadata['quote']}")
        lines.append(f"  背景      : {metadata.get('background_scene', '')} ({metadata.get('background_category', '')})")
        lines.append(f"  構圖      : {metadata.get('composition', '')}")
        lines.append(f"  條件      : {metadata.get('conditions')}")
        lines.append(f"  質感      : {metadata.get('texture')}")
        lines.append(f"  朋友      : {metadata.get('friend_info')}")
        if entry["failed"]:
            lines.append("  狀態      : ✗ 提示詞生成失敗（未使用模板 C 補位）")
        else:
            prompt = entry["prompt"]
            words = len(prompt.split())
            zh = len(FORBIDDEN_ZH.findall(prompt))
            legs = bool(FOUR_LEGS.search(prompt))
            face = bool(BEAR_FACE.search(prompt))
            lines.append(f"  單字數    : {words}")
            lines.append(f"  中文字元  : {zh}")
            lines.append(f"  四隻腳    : {'命中' if legs else '未命中'}")
            lines.append(f"  熊臉特徵  : {'命中' if face else '未命中'}")
            lines.append("")
            lines.append("PROMPT:")
            lines.append(prompt)
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log(f"dry-run 報告已輸出：{out_path}")
    return out_path


def main(config):
    today = get_today()
    init_log_file(today, dry_run=config.dry_run)

    log("===== 熊熊每日配送計畫 =====")
    if config.mode:
        log(f"模式: {config.mode}")
    if config.dry_run:
        log("模式: dry-run（不生圖、不寫 bears.json、不 commit、不 deploy）")
    if config.allow_fallback:
        log("模式: 允許模板 C fallback（--allow-fallback）")
    log(f"今日日期: {today}")
    log(f"暫存目錄: {config.temp_dir / today}")
    log(f"目的目錄: {config.dest_dir / today}")

    log("\n--- 步驟 1: 檢查系統狀態 ---")
    comfyui_online = check_comfyui(config)
    log(f"ComfyUI: {'✓ 在線' if comfyui_online else '✗ 離線'}")

    log("\n--- 步驟 2: 取得熊熊名字和風格 ---")
    num_bears = config.total_count
    bear_names = get_next_bear_names(num_bears)

    history = load_style_history()
    if config.dry_run:
        styles = select_styles(num_bears, today, history=history)
    else:
        styles = get_next_styles(num_bears)
    style_zhs = [s.get("zh", str(s)) if isinstance(s, dict) else s for s in styles]
    log(f"熊熊: {bear_names}")
    log(f"風格: {style_zhs}")

    if config.mode == "step2":
        log(f"配送隻數: ComfyUI {config.comfy_count} + MiniMax {config.minimax_count} = {num_bears}")
        for i, (name, style) in enumerate(zip(bear_names, styles), start=1):
            kind = "ComfyUI" if i <= config.comfy_count else "MiniMax"
            style_zh = style.get("zh", str(style)) if isinstance(style, dict) else style
            log(f"  #{i} [{kind}]: {name} / {style_zh}")
        log("\n[step2] 預覽完成，未生圖、未更新詞彙輪流")
        return 0

    log("\n--- 步驟 3: 準備目錄 ---")
    if not config.dry_run:
        (config.temp_dir / today).mkdir(parents=True, exist_ok=True)
        (config.dest_dir / today).mkdir(parents=True, exist_ok=True)

    # 當天不重複的背景與構圖
    scenes = select_day_scenes(num_bears)
    metadata_list = [
        prepare_bear_metadata(name, style, scene=scenes[i])
        for i, (name, style) in enumerate(zip(bear_names, styles))
    ]

    log("\n--- 步驟 4: 生成提示詞 ---")
    collection_no_start = get_max_collection_no() + 1
    prompt_results, failed = step_generate_prompts(
        metadata_list, today, collection_no_start, config
    )

    if config.dry_run:
        dump_dryrun_report(metadata_list, prompt_results, today, config)
        total = len(metadata_list)
        log("")
        log(f"dry-run 統計：共 {total} 隻，成功 {total - failed} 隻，失敗 {failed} 隻")
        log(f"fallback_used: {any(r.get('info', {}).get('fallback_used') for r in prompt_results)}")
        if failed == total:
            log("!!! 全部失敗")
            notify_discord(
                f"🚨 熊熊配送失敗：{today} 全部 {total} 隻提示詞生成失敗，未產生任何圖片，未寫入 bears.json。",
                enabled=config.notify,
            )
            return 1
        log("dry-run 完成：未生圖、未寫 bears.json、未 commit、未 deploy")
        return 0

    if failed and failed == len(metadata_list):
        log("")
        log("!!! 全部失敗，中止配送")
        notify_discord(
            f"🚨 熊熊配送失敗：{today} 全部 {len(metadata_list)} 隻提示詞生成失敗，"
            "配送已中止，未寫入 bears.json、未 commit、未 deploy。",
            enabled=config.notify,
        )
        return 1

    log("\n--- 步驟 4b: 生成圖片 ---")
    if failed:
        log(f"（{failed} 隻因提示詞生成失敗而跳過，不使用模板 C 補位）")
    generated, failed = step_generate_images(prompt_results, today, config, comfyui_online)

    if config.mode == "step4":
        log("\n[step4] 生圖完成，圖片保留於暫存目錄，未複製、未更新 bears.json")
        return 0

    log("\n--- 步驟 5: 更新熊熊博物館 ---")
    new_bears = step_update_museum(generated, today, config)

    if config.mode == "step5":
        log("\n[step5] 博物館更新完成，未 commit、未部署")
        return 0

    if not new_bears:
        log("\n沒有新增熊熊，跳過 commit 與部署")
        return 0

    if failed:
        message = (
            f"⚠️ 熊熊配送部分失敗：{today} 共 {len(metadata_list)} 隻中 {failed} 隻"
            "提示詞生成失敗（未使用模板 C 補位），已成功產生 "
            f"{len(new_bears)} 隻。"
        )
        log(message)
        notify_discord(message, enabled=config.notify)

    log("\n--- 步驟 6: Git Commit ---")
    run_cmd(f"cd {PROJECT_DIR} && git add bears.json bears/ vocabulary/style-rotation.json vocabulary/daily-delivery.py vocabulary/bear-conditions.json vocabulary/bear-textures.json vocabulary/bear-backgrounds.json vocabulary/bear-friends.json")
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
    return 0


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
    parser.add_argument("--allow-fallback", action="store_true",
                        help="允許使用模板 C fallback（預設關閉；模板 C 不保證四隻腳規則）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只產生提示詞並印出，不生圖、不寫 bears.json、不 commit、不 deploy")
    parser.add_argument("--no-notify", action="store_true",
                        help="跳過 Discord 通知（測試用）")
    parser.add_argument("--hermes-api-url", default=HERMES_API_URL,
                        help="覆寫 Hermes 端點（供失敗路徑測試用）")
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
        dry_run=args.dry_run,
        allow_fallback=args.allow_fallback,
        notify=not args.no_notify,
    )

    globals()["HERMES_API_URL"] = args.hermes_api_url

    sys.exit(main(config))
