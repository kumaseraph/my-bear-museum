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
import io
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
BEAR_SHAPES = VOCAB_DIR / "bear-shapes.json"
BEAR_POSES = VOCAB_DIR / "bear-poses.json"

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

# Discord 通知目標：熊熊系統部 thread（cron deliver 同一個）
# thread 自身的 channel ID 就是可用的 channel_id，直送路徑 /channels/<thread_id>/messages
DISCORD_API_BASE = "https://discord.com/api/v10"
NOTIFY_CHANNEL_ID = "1560489877093482527"

MINIMAX_IMAGE_URL = "https://api.minimax.io/v1/image_generation"

# ===== 選樣參數 =====
RECENT_EXCLUDE_DAYS = 3      # 最近 N 天用過的風格 → 不抽
RECENT_DOWNWEIGHT_DAYS = 14  # 最近 N 天用過的風格 → 降權
DOWNWEIGHT_FACTOR = 0.35     # 降權後的權重倍率
PROMPT_MAX_ATTEMPTS = 2      # 提示詞生成/驗證失敗的重試上限
PROMPT_RETRY_DELAY = 2       # 重試間隔（秒）

# ===== 造型池選樣參數（與風格選樣同構）=====
SHAPE_EXCLUDE_DAYS = 3        # 最近 N 天用過的造型 → 不抽
SHAPE_DOWNWEIGHT_DAYS = 14   # 最近 N 天用過的造型 → 降權
SHAPE_DOWNWEIGHT_FACTOR = 0.35

# ===== 姿勢池選樣參數（與造型池同構）=====
POSE_EXCLUDE_DAYS = 3         # 最近 N 天用過的姿勢 → 不抽
POSE_DOWNWEIGHT_DAYS = 14    # 最近 N 天用過的姿勢 → 降權
POSE_DOWNWEIGHT_FACTOR = 0.35

# ===== 品質尾綴 =====
# 移除 `wild animal anatomy`：它會把每一隻熊熊都拉成寫實野生巨熊
# （2026-10-29 實測 6/6 同質化），造型差異因此被完全抹平。
# 熊的肢體數量與解剖一致性改由 PROMPT_SYSTEM 的 HARD CONSTRAINTS、
# ensure_anatomy_clause() 與每筆造型描述共同負責，強度不減。
# 保留完整 no-text 否定詞串，不可縮短。
PROMPT_QUALITY_SUFFIX = (
    "correct bear anatomy, horizontal composition 16:9, "
    "high quality illustration, detailed fur texture, "
    "absolutely no text, absolutely no letters, absolutely no words, "
    "absolutely no writing, no readable characters, no alphabet, "
    "no labels on jars, no signs, no book titles, no posters, "
    "no newspaper, no menu text, no scroll text, no card text, "
    "decorative shapes and symbols only, not actual letters"
)

# ===== 姿勢池（熊熊可為任何姿勢，不限定四足）=====
# 姿勢由本池指定；造型只控制體型比例與表面，不改變姿勢。
# 池內容在 bear-poses.json（與造型池同構的資料檔）。

# ===== 視覺驗圖 =====
VISION_API_URL = "https://api.minimax.io/v1/chat/completions"
VISION_MODEL = "MiniMax-M3.1-Flash"
VISION_TIMEOUT = 120
# MiniMax-M3.1-Flash 會先輸出 reasoning_content 再給答案，max_tokens 太小時
# 推理就會吃光額度、導致 content 為 None（實測 200 → 無輸出；3000 → 正常）。
VISION_MAX_TOKENS = 8000
VERIFY_REGENERATE_MAX = 2         # 驗圖失敗（熊臉／肢體數量／有文字）時的重生上限；姿勢不觸發重生


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
        "bear clearly readable",
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

PROMPT_SYSTEM = """You are an expert at writing English text-to-image prompts for a museum of characterful bears shown in many different forms.

Given bear metadata in Traditional Chinese, write ONE detailed English image generation prompt.

Rules:
- Infer fur color and scene from the bear name, personality, series, and title
- Translate the art style to English (e.g. 油畫=oil painting, 霓虹燈=neon light, 水彩=watercolor, 故障藝術=glitch art)
- Describe a vivid scene with atmosphere and magical lighting
- Write as a single flowing English paragraph, at least 150 words, ideally 180-250 words
- Do NOT include Chinese characters or the raw Chinese bear name
- Do NOT include quality tags like "16:9", "detailed fur texture" or "correct bear anatomy" (added separately)
- NEVER use the words "kawaii", "mascot", "chibi" or "anthropomorphic" anywhere in the prompt
- Output ONLY the prompt text, no quotes, no explanation, no markdown, no thinking

HARD CONSTRAINTS - the bear must read as a bear with correct anatomy:
- The bear's anatomy must be normal and complete: exactly two front paws and two hind legs, plus a clear head and tail - never an extra limb, never a missing limb, never a twisted or broken joint
- The bear must look like a bear: round bear ears, round teddy bear face, fluffy bear paws - not a rabbit, cat, fox, or other animal
- The image must contain NO readable text: no letters, no words, no writing, no readable characters, no alphabet, no signs, no book titles, no posters, no newspaper, no menu text, no scroll text, no card text, no labels. Use decorative shapes, symbols, glyphs, runes, ornamental patterns or abstract designs instead of actual letters

BEAR POSE - the metadata includes a "Bear pose" line, and it decides what the bear is doing:
- The bear may be in ANY natural animal pose: standing, sitting, lying down, lying prone, crouching, running, leaping, airborne, rolling over, curled up asleep, eating or drinking, climbing a tree, swimming, stretching, sniffing the ground, gazing into the distance
- Describe the pose exactly as it is given, using concrete physical wording ("lying on its side", "sitting upright", "bounding forward", "leaping through the air", "curled up asleep")
- The pose NEVER changes the number of limbs and NEVER changes the bear's form; a sitting bear still has two front paws and two hind legs
- Do NOT add any pose of your own and do NOT override the given pose
- The bear stays an animal: it does not wave, hold an object up like a human, present something, hug, clap or point. A prop is carried in its mouth, worn on its body, or lies on the ground beside it
- The bear's form features and the bear-face features must be stated together in the same paragraph so the model cannot read one without the other

BEAR FORM - the metadata includes a "Bear form" line, and it decides how the bear's body looks:
- The bear's body proportions, head-to-body ratio, limb length and fur surface MUST match that form exactly
- The form changes ONLY proportions and surface - it NEVER changes the number of limbs (still exactly two front paws and two hind legs) and NEVER changes the given pose
- Different bears have different forms: a chubby rounded bear, a baby cub, a plush-toy-surface bear, a big-headed cartoon-proportioned bear, a lean athletic bear, a slender elegant bear, a massive shaggy bear, a marshmallow-round bear, a low-slung short-legged bear, a silver-grey lean bear
- Describe the form with concrete physical words (chubby, oversized round head, stubby legs, velvety, shaggy, tapered muzzle) and restate it together with the bear-face features in the same sentence

COMPOSITION - the provided composition describes the camera angle:
- Close-up portrait: the face and shoulders fill the frame
- Mid-shot: the bear fills most of the frame, head to knees visible
- Full body: the entire bear is visible from nose to paws
- Environmental wide shot: a wide view where the landscape dominates and the bear is small
- "bear as observer in vast scene": the bear is the supporting character and the scene is the subject
  - the bear occupies roughly one eighth to one fifth of the frame and is not the focal point
  - the scenery takes up most of the image (grand landscape, wide-angle viewpoint)
  - example elements:
    - "a small bear at a cliff edge, vast misty mountains beyond"
    - "a tiny bear silhouette against a brilliant sunset over the ocean"
    - "a small bear resting on a windowsill, magical forest visible through the window"
    - "a tiny bear moving through an endless lavender field under starry sky"
    - "a small bear on a giant flower petal, surrounded by a dreamy garden"
  - the bear must still read clearly as a bear (round ears, bear face, correct limb count), never as an ambiguous blob
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
- The bear keeps its own given pose beside its friends; the friends may stand or sit, and the bear's own pose stays as assigned
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
        log_suffix="",
        compositions="",
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
        self.log_suffix = log_suffix
        self.compositions = compositions

    @property
    def total_count(self):
        return self.comfy_count + self.minimax_count


_log_file = None


def init_log_file(today, dry_run=False, suffix=""):
    """dry-run 使用獨立 log 檔，避免污染正式配送歷史。

    suffix 會加在檔名 stem 之後（例：-trial → logs/2026-10-29-trial.log）。
    """
    global _log_file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log_file = LOG_DIR / (f"dryrun-{today}{suffix}.log" if dry_run else f"{today}{suffix}.log")


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
        "correct bear anatomy" in lower
        and "16:9" in lower
        and "detailed fur texture" in lower
    ):
        return content
    return f"{content.rstrip('., ')}, {PROMPT_QUALITY_SUFFIX}"


def ensure_anatomy_clause(content, composition=None):
    """補一句肢體數量正確的描述（特寫/剪影構圖除外）。

    只約束「肢體數量正確、不多長不少長不畸形」，不約束姿勢。
    """
    if composition in FOUR_LEGS_UNVERIFIABLE_COMPOSITIONS:
        return content
    if FOUR_LEGS.search(content):
        return content
    return (
        f"{content.rstrip('., ')}, the bear has exactly two front paws and "
        "two hind legs, with correct normal anatomy and no extra or missing limbs"
    )


def ensure_shape_clause(content, shape=None):
    """把造型描述寫進 prompt（造型決定體型比例與表面，不改變姿勢）。"""
    if not shape:
        return content
    en = (shape.get("en") or "").strip()
    if not en:
        return content
    if en[:40].lower() in content.lower():
        return content
    return f"{content.rstrip('., ')}, {en}"


def ensure_pose_clause(content, pose=None):
    """把姿勢描述寫進 prompt（姿勢由姿勢池指定，不限定四足）。"""
    if not pose:
        return content
    en = (pose.get("en") or "").strip()
    if not en:
        return content
    if en[:40].lower() in content.lower():
        return content
    return f"{content.rstrip('., ')}, {en}"


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
                       background_scene=None, composition=None,
                       shape=None, pose=None):
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

    if shape:
        lines.append(
            f"Bear form (body proportions and surface - the bear must look exactly "
            f"like this form): {shape.get('zh', '')} ({shape.get('en', '')})"
        )

    if pose:
        lines.append(
            f"Bear pose (the bear is doing exactly this - do not choose another pose): "
            f"{pose.get('zh', '')} ({pose.get('en', '')})"
        )

    return "\n".join(lines)


def generate_prompt_via_model(name, style, series, personality, title, quote=None,
                              friend_info=None, conditions=None, texture=None,
                              background_scene=None, composition=None,
                              shape=None, pose=None, allow_fallback=False):
    """用 Hermes API 依 metadata 產生英文生圖 prompt。

    回傳 (prompt, info)。info 含 attempts / warnings / fallback_used / elapsed。
    失敗時（且未允許 fallback）拋出 PromptGenerationError。
    """
    user_content = build_user_content(
        name, style, series, personality, title, quote,
        friend_info, conditions, texture, background_scene, composition,
        shape, pose,
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
                text = ensure_shape_clause(text, shape)
                text = ensure_pose_clause(text, pose)
                text = ensure_anatomy_clause(text, composition)
                text = ensure_prompt_suffix(text)
                text = re.sub(r"\s*\n+\s*", " ", text)
                # 提醒要在補完之後才有意義：模型原始輸出常常沒寫肢體數量，
                # 但 ensure_anatomy_clause() 會補上，先前會誤報「未明確寫出四隻腳」。
                for warning in warnings:
                    if "四隻腳" in warning and FOUR_LEGS.search(text):
                        continue
                    log(f"    ⚠ 提示詞提醒：{warning}")
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
        log("WARNING: 使用模板 C fallback（肢體數量規則不受保證）")
        fallback = build_prompt_fallback(
            name, style, series, personality, title,
            friend_info, conditions, texture,
            background_scene, composition, shape, pose,
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
                          composition=None, shape=None, pose=None):
    """模板 C prompt。

    ⚠ 只在明確允許（--allow-fallback）時使用；不得自動呼叫。
    完全英文、含肢體數量與熊臉規則、長度 ≥ 150 詞。
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
        "fluffy bear paws, in a horizontal sixteen-by-nine frame",
        style_clause,
    ]

    if background_scene:
        parts.append(f"set in {background_scene}")

    if composition:
        if composition == "bear as observer in vast scene":
            parts.append(
                "the bear is a small figure within the vast scene, among the "
                "immense landscape, the environment dominating the frame while the animal "
                "remains a distinct and clearly readable bear, wide-angle "
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
            f"beside {', '.join(friend_descs)}, {scenario}, "
            "the friends beside it while the bear keeps its own pose"
        )

    if shape and shape.get("en"):
        parts.append(shape["en"])

    if pose and pose.get("en"):
        parts.append(pose["en"])

    parts.append(f"{style_mood} atmosphere")
    parts.append(FALLBACK_SCENE_DETAIL)
    parts.append(
        "exactly two front paws and two hind legs, correct normal anatomy with "
        "no extra or missing limbs"
    )

    prompt = ", ".join(p for p in parts if p)
    prompt = re.sub(r"\s*\n+\s*", " ", prompt)
    return f"{prompt.rstrip('., ')}, {PROMPT_QUALITY_SUFFIX}"


# ===== 失敗紀錄與通知（§3.4 / §3.5）=====

# 本批次失敗收集清單：執行期只記錄，收尾時由 send_failure_summary() 彙總成單一通知
FAILURE_RECORDS = []

# 最近一次生圖失敗的錯誤訊息（生圖函式無法回傳錯誤，只能透過模組變數往外傳）
LAST_IMAGE_ERROR: str = ""
LAST_IMAGE_BACKEND: str = ""

# 同一個 run 只發一次彙總通知
_FAILURE_SUMMARY_SENT = False

# 疑似金鑰失效／權限不足的錯誤特徵
_KEY_ERROR_PATTERN = re.compile(r"\b401\b|\b403\b|Unauthorized|Forbidden", re.IGNORECASE)


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


def _error_group_key(error):
    """把錯誤訊息歸類成可統計的原因標籤（例：401 Unauthorized）。"""
    err = str(error)
    # 只在明確的 HTTP 狀態語境抓碼，避免誤判（例如 URL 或 port 內的數字）
    code = None
    for pat in (
        r"\bHTTP (\d{3})\b",
        r"\bClient Error: (\d{3})\b",
        r"\bstatus_code\D{0,3}(\d{3})\b",
        r"\bStatus Code: (\d{3})\b",
    ):
        m = re.search(pat, err)
        if m:
            code = m.group(1)
            break
    if code:
        if "Unauthorized" in err or code == "401":
            return f"{code} Unauthorized"
        if "Forbidden" in err or code == "403":
            return f"{code} Forbidden"
        if "Too Many Requests" in err or code == "429":
            return f"{code} Too Many Requests"
        return f"HTTP {code}"
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*Error)\b", err)
    if m:
        return m.group(1)
    return err[:60] or "未知錯誤"


def _looks_like_key_failure(error):
    """錯誤訊息是否疑似金鑰失效或權限不足。"""
    err = str(error)
    if re.search(r"\bUnauthorized\b|\bForbidden\b", err, re.IGNORECASE):
        return True
    return bool(_KEY_ERROR_PATTERN.search(err))


def record_failure(date_str, collection_no, bear_name, attempts, error,
                   stage="prompt_generation", backend="hermes-api"):
    """寫 JSONL 錯誤紀錄 + 通知檔 + NOTIFICATIONS.md + 印醒目 log。

    執行期只記錄，不發 Discord；Discord 由收尾時的 send_failure_summary() 彙總發送。
    """
    ts = datetime.now()
    ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)

    err_path = ERROR_LOG_DIR / f"prompt-error-{date_str}.jsonl"
    record = {
        "timestamp": ts.isoformat(timespec="seconds"),
        "stage": stage,
        "backend": backend,
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
        f"後端：{backend}\n"
        f"嘗試次數：{attempts}\n"
        f"錯誤摘要：{str(error)[:300]}\n"
        f"錯誤紀錄檔：{err_path}\n"
        f"處理：本隻未產圖，未使用模板 C 補位。"
    )

    title = "🚨 熊熊提示詞生成失敗" if stage == "prompt_generation" else "🚨 熊熊生圖失敗"
    npath = ERROR_LOG_DIR / f"notification-{ts.strftime('%Y%m%d-%H%M%S')}-{collection_no}.md"
    npath.write_text(f"{title}\n{summary}\n", encoding="utf-8")

    with open(ERROR_LOG_DIR / "NOTIFICATIONS.md", "a", encoding="utf-8") as f:
        f.write(f"## {ts.strftime('%Y-%m-%d %H:%M:%S')} — No.{collection_no} {bear_name}\n\n")
        f.write(f"- 階段：{stage}\n- 後端：{backend}\n- 嘗試次數：{attempts}\n")
        f.write(f"- 錯誤：`{str(error)[:300]}`\n")
        f.write(f"- 後備行為：**無**（未退回模板 C，`fallback_used: false`）\n")
        f.write(f"- 錯誤紀錄：`{err_path.name}`\n- 通知檔：`{npath.name}`\n\n")

    log_block("DELIVERY FAILURE" if stage != "prompt_generation" else "PROMPT GENERATION FAILED",
              summary)

    FAILURE_RECORDS.append({
        "collection_no": collection_no,
        "bear_name": bear_name,
        "stage": stage,
        "backend": backend,
        "attempts": attempts,
        "error": str(error),
        "error_path": str(err_path),
        "timestamp": ts.isoformat(timespec="seconds"),
    })

    return err_path, npath


def record_prompt_failure(date_str, collection_no, bear_name, attempts, error,
                          stage="prompt_generation", notify=True):
    """記錄提示詞生成失敗（不再立即發 Discord，改由批次彙總統一發送）。"""
    return record_failure(date_str, collection_no, bear_name, attempts, error,
                          stage=stage, backend="hermes-api")


def _build_failure_summary(today, total_count, records, error_limit=200):
    """組出批次失敗彙總訊息。error_limit 為每隻錯誤摘要的字元上限。"""
    groups = {}
    for r in records:
        key = _error_group_key(r["error"])
        groups.setdefault(key, []).append(r)

    stages = {}
    for r in records:
        stages.setdefault(r["stage"], []).append(r)

    lines = ["🚨 熊熊配送失敗彙報"]
    if any(_looks_like_key_failure(r["error"]) for r in records):
        lines.append(
            "⚠️ 疑似 API 金鑰失效或額度用盡，"
            "請檢查 /home/fjj04/.hermes/.env 的 MINIMAX_API_KEY"
        )
    lines.append(f"日期：{today}")
    lines.append(f"共 {total_count} 隻中 {len(records)} 隻失敗")
    lines.append("")
    lines.append("依原因分組：")
    for key, items in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"- {key}: {len(items)} 隻")
    lines.append("")
    lines.append("依階段分組：")
    for stage, items in stages.items():
        lines.append(f"- {stage}: {len(items)} 隻")
    lines.append("")
    lines.append("失敗明細：")
    for i, r in enumerate(records, start=1):
        err = r["error"].replace("\n", " ").strip()
        if len(err) > error_limit:
            err = err[:error_limit] + "…"
        lines.append(
            f"{i}. No.{r['collection_no']} {r['bear_name']}"
            f"（{r['stage']}／{r['backend']}）— {err}"
        )
    lines.append("")
    lines.append("模板 C 補位：否（未退回簡單句型）")
    lines.append(f"錯誤紀錄：{records[0]['error_path']}")
    return "\n".join(lines)


def _fallback_used_in_batch(prompt_results):
    """本批次是否有任何一隻使用了模板 C 補位。"""
    return any(
        r.get("info", {}).get("fallback_used")
        for r in (prompt_results or [])
        if isinstance(r, dict)
    )


def send_failure_summary(today, total_count, enabled=True, prompt_results=None):
    """收尾時送出本批次的單一失敗彙總通知。沒有失敗就不發。"""
    global _FAILURE_SUMMARY_SENT

    if not FAILURE_RECORDS:
        return False
    if _FAILURE_SUMMARY_SENT:
        log("  （彙總通知已發過，本次不重複發送）")
        return False

    _FAILURE_SUMMARY_SENT = True

    # Discord 單則上限 2000 字；逐級縮短錯誤摘要直到塞得下
    summary = _build_failure_summary(today, total_count, FAILURE_RECORDS)
    for err_limit in (160, 120, 80, 40):
        if len(summary) <= 2000:
            break
        summary = _build_failure_summary(today, total_count, FAILURE_RECORDS,
                                         error_limit=err_limit)

    if _fallback_used_in_batch(prompt_results):
        summary = summary.replace(
            "模板 C 補位：否（未退回簡單句型）",
            "模板 C 補位：有（部分熊熊已退回簡單句型）",
        )

    log_block("DELIVERY FAILURE SUMMARY", summary)

    if not enabled:
        log("  （--no-notify）略過 Discord 彙總通知")
        return False

    discord_ok = notify_discord(summary, enabled=True)
    if not discord_ok:
        err_path = FAILURE_RECORDS[0].get("error_path")
        if err_path:
            try:
                with open(err_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(
                        {"timestamp": datetime.now().isoformat(timespec="seconds"),
                         "stage": "discord_notification", "backend": "discord-bot",
                         "date": today, "collection_no": None, "bear_name": None,
                         "attempts": 0, "error": "Discord 彙總通知發送失敗（詳見 stderr）",
                         "fallback_used": False},
                        ensure_ascii=False) + "\n")
            except OSError:
                pass
    return discord_ok


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
        m = re.search(r"^\[\d{2}:\d{2}:\d{2}\] 風格: (\[.*?\])$", txt, re.M)
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


def load_bear_shapes():
    """載入 bear-shapes.json 的造型池。"""
    data = load_json(BEAR_SHAPES)
    return data.get("shapes", [])


def load_bear_poses():
    """載入 bear-poses.json 的姿勢池。"""
    data = load_json(BEAR_POSES)
    return data.get("poses", [])


def load_pose_pool():
    """載入姿勢池（bear-poses.json）。"""
    return load_bear_poses()


def _load_log_history(pattern, flags=0):
    """從 logs/*.log 的指定行取得每日清單歷史，回傳 dict[str, list[str]]。

    與 load_style_history() 同構：只解析 stem 為 ISO 日期的 log 檔
    （dry-run / trial 的 log stem 不是日期，會自然被排除）。
    """
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
        m = re.search(pattern, txt, flags)
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


def load_shape_history():
    """從 logs/*.log 的「造型: [...]」行取得每日造型歷史。"""
    # 錨定開頭的行標記，避免誤抓「造型(預覽): [...]」這類預覽紀錄
    return _load_log_history(r"^\[\d{2}:\d{2}:\d{2}\] 造型: (\[.*?\])$", re.M)


def load_pose_history():
    """從 logs/*.log 的「姿勢: [...]」行取得每日姿勢歷史。"""
    return _load_log_history(r"^\[\d{2}:\d{2}:\d{2}\] 姿勢: (\[.*?\])$", re.M)


def _pool_weights(pool, exclude, downweight, downweight_factor):
    weights = {}
    for item in pool:
        zh = item["zh"]
        if zh in exclude:
            weights[zh] = 0.0
        elif zh in downweight:
            weights[zh] = downweight_factor
        else:
            weights[zh] = 1.0
    return weights


def _select_from_pool(pool, n, target_date, history, exclude_days,
                      downweight_days, downweight_factor, rng):
    """通用的「最近 N 天不抽 / 降權 / 同日不重複」選樣。

    退讓順序與 select_styles() 相同：先放寬降權、再放寬禁抽。
    """
    rng = rng or random
    if not pool or n <= 0:
        return []

    d = date.fromisoformat(target_date)
    exclude, downweight = set(), set()
    for offset in range(1, exclude_days + 1):
        exclude.update(history.get((d - timedelta(days=offset)).isoformat(), []))
    for offset in range(exclude_days + 1, downweight_days + 1):
        downweight.update(history.get((d - timedelta(days=offset)).isoformat(), []))

    weights = _pool_weights(pool, exclude, downweight, downweight_factor)
    avail = [s for s in pool if weights[s["zh"]] > 0]

    if len(avail) < n:
        # 退讓 1：放寬降權（仍不放寬禁抽）
        weights = _pool_weights(pool, exclude, set(), downweight_factor)
        avail = [s for s in pool if weights[s["zh"]] > 0]

    if len(avail) < n:
        # 退讓 2：放寬禁抽（最後手段）
        weights = {s["zh"]: 1.0 for s in pool}
        avail = list(pool)

    return _weighted_pick(avail, weights, n, rng)


def select_shapes(n, target_date, history=None, rng=None):
    """套用「最近 3 天不抽 / 14 天降權 / 同日不重複」規則選出 n 個造型。"""
    pool = load_bear_shapes()
    if history is None:
        history = load_shape_history()
    return _select_from_pool(
        pool, n, target_date, history,
        SHAPE_EXCLUDE_DAYS, SHAPE_DOWNWEIGHT_DAYS, SHAPE_DOWNWEIGHT_FACTOR, rng,
    )


def select_poses(n, target_date, history=None, rng=None):
    """套用「最近 3 天不抽 / 14 天降權 / 同日不重複」規則選出 n 個姿勢。"""
    pool = load_pose_pool()
    if history is None:
        history = load_pose_history()
    return _select_from_pool(
        pool, n, target_date, history,
        POSE_EXCLUDE_DAYS, POSE_DOWNWEIGHT_DAYS, POSE_DOWNWEIGHT_FACTOR, rng,
    )


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


def prepare_bear_metadata(name, style, scene=None, shape=None, pose=None):
    """生圖前先產生熊熊 metadata，供 prompt 與 bears.json 共用。

    Args:
        name: 熊熊中文名字
        style: 風格 dict {"zh": ..., "en": ..., "mood": ...} 或字串（向後相容）
        scene: 當天抽好的 {"background_category", "background_scene", "composition"}
        shape: 造型 dict {"zh": ..., "en": ...}（體型比例與表面，不改變姿勢）
        pose: 姿勢 dict {"zh": ..., "en": ...}（姿勢由姿勢池指定）
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

    if shape:
        metadata["shape"] = shape
    if pose:
        metadata["pose"] = pose

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
    if metadata.get("shape"):
        record["shape"] = metadata["shape"].get("zh", "")
    if metadata.get("pose"):
        record["pose"] = metadata["pose"].get("zh", "")
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


def _set_image_error(message, backend):
    """記錄最近一次生圖失敗的錯誤訊息（生圖函式只回傳 bool，錯誤靠這裡往外傳）。"""
    global LAST_IMAGE_ERROR, LAST_IMAGE_BACKEND
    LAST_IMAGE_ERROR = str(message)
    LAST_IMAGE_BACKEND = backend


def generate_minimax_image(prompt, bear_name, style, output_path, idx, config):
    style_zh = style.get("zh", str(style)) if isinstance(style, dict) else style
    log(f"MiniMax #{idx+1}: {bear_name} ({style_zh}) [{config.minimax_size}]")

    api_key = get_secret("MINIMAX_API_KEY")
    if not api_key:
        log("  ERROR: 找不到 MINIMAX_API_KEY")
        _set_image_error("ERROR: 找不到 MINIMAX_API_KEY（檢查 /home/fjj04/.hermes/.env）",
                         "minimax-api")
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
        _set_image_error(f"{type(e).__name__}: {e}", "minimax-api")
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


def generate_comfyui_image(prompt, bear_name, style, output_path, idx, config, seed=None):
    style_zh = style.get("zh", str(style)) if isinstance(style, dict) else style
    log(f"ComfyUI #{idx+1}: {bear_name} ({style_zh}) [{config.comfy_width}x{config.comfy_height}]")

    if not COMFY_WORKFLOW.exists():
        log("  ComfyUI workflow 不存在，跳過")
        _set_image_error("ERROR: ComfyUI workflow 不存在", "comfyui")
        return False

    try:
        load_workflow, patch_workflow, submit_workflow, poll_status, get_output_images, download_image = _load_comfy_helpers()
        wf = load_workflow(str(COMFY_WORKFLOW))
        client_id = str(uuid.uuid4())
        patched, _seed = patch_workflow(
            wf, prompt, width=config.comfy_width, height=config.comfy_height, seed=seed
        )
        result = submit_workflow(config.comfyui_url, patched, client_id)
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            log(f"  ComfyUI 無 prompt_id: {result}")
            _set_image_error(f"ComfyUI 無 prompt_id: {str(result)[:200]}", "comfyui")
            return False

        status = poll_status(config.comfyui_url, prompt_id)
        if status.get("status", {}).get("status_str") != "success":
            log("  ComfyUI 生成未成功")
            _set_image_error("ComfyUI 生成未成功", "comfyui")
            return False

        images = get_output_images(config.comfyui_url, status)
        if not images:
            log("  ComfyUI 無輸出圖片")
            _set_image_error("ComfyUI 無輸出圖片", "comfyui")
            return False

        download_image(images[0]["url"], str(output_path))
        log(f"  已保存: {output_path.name}")
        return True
    except Exception as e:
        log(f"  ComfyUI 生成失敗: {e}")
        _set_image_error(f"{type(e).__name__}: {e}", "comfyui")
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


# ===== 視覺驗圖（熊臉 / 肢體數量 / 無文字）=====
# ⚠ 驗圖判定只有三項（依 2026-10-29 補充 S4）：熊臉正確、肢體數量正確、無文字。
# ⚠ 姿勢不限四足；坐姿不是違規，也不觸發重生（S3：禁止「坐姿→重生」邏輯）。
# 重生的唯一觸發條件是「肢體數量錯誤」（多長／少長／畸形）。

VISION_PROMPT = """Look at the bear in this image. Answer with exactly six lines and nothing else:
LEGS=<the number of bear limbs you can actually SEE>
OCCLUDED=<yes if any limb is hidden behind the bear's own body or off-frame, so that you simply cannot count it; no if every limb is clearly visible>
LIMBS=<correct if the bear has exactly two front paws and two hind legs with nothing extra, missing, twisted or broken; wrong only if you can SEE an extra limb, a visibly missing limb, or a twisted or broken joint>
FACE=<correct if it reads as a bear with round ears, a round bear face and bear paws; wrong if it reads as a rabbit, cat, fox or another animal>
TEXT=<none if there is no readable text, letters, words, sign, book title or label in the image; some otherwise>
POSE=<one of: standing, sitting, lying, prone, crouching, running, leaping, airborne, rolling, curled_up, eating, climbing, swimming, other>
Important: a limb that is merely hidden behind the bear's body is NOT a missing limb, so if OCCLUDED=yes then LIMBS=correct unless you can actually see a wrong number of limbs or a deformed joint."""

# 肢體數量錯誤／出現文字時的重生強化句
LIMB_REGENERATE_CLAUSE = (
    "the bear has exactly two front paws and two hind legs and nothing more, "
    "all four limbs clearly separated and readable, no extra limb, no missing limb, "
    "no twisted or broken joint"
)

# 出現可讀文字時的重生強化句
TEXT_REGENERATE_CLAUSE = (
    "no readable text anywhere in the image, no letters, no words, no writing, "
    "no characters on any surface, any jar, book, sign or label carries only "
    "decorative symbols and abstract patterns, never actual letters"
)

# 熊臉不正確時的重生強化句（S4 三項失敗條件之一）
FACE_REGENERATE_CLAUSE = (
    "the animal is unmistakably a bear, with round bear ears on top of a round "
    "teddy-bear face, a short broad bear muzzle, dark round eyes and a small "
    "black nose, and fluffy bear paws, never a rabbit, cat, fox or any other species"
)


def _image_to_base64_jpeg(image_path, max_width=768):
    """縮圖到指定寬度、轉 RGB JPEG、base64 編碼（不落地寫檔）。"""
    Image = _load_pil_image()
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, max(1, int(img.height * ratio))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        return base64.b64encode(buf.getvalue()).decode("ascii")


def verify_pose_via_vision(image_path, retries=1):
    """用視覺模型檢查圖中熊熊的熊臉、肢體數量與有無文字。

    回傳 dict：
      {"ok": bool, "legs": int|None, "occluded": bool|None,
       "limbs_correct": bool|None, "face_ok": bool|None, "text_free": bool|None,
       "pose": str, "raw": str, "error": str}

    ok=False 表示無法判定（呼叫失敗）→ 呼叫端不得因此重生。
    任何例外都不得向上拋出，配送流程不可中斷。
    """
    result = {
        "ok": False,
        "legs": None,
        "occluded": None,
        "limbs_correct": None,
        "face_ok": None,
        "text_free": None,
        "pose": "unclear",
        "raw": "",
        "error": "",
    }

    try:
        api_key = get_secret("MINIMAX_API_KEY")
        if not api_key:
            result["error"] = "找不到 MINIMAX_API_KEY"
            return result

        image_b64 = _image_to_base64_jpeg(image_path)

        payload = json.dumps({
            "model": VISION_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }],
            "temperature": 0.1,
            "max_tokens": VISION_MAX_TOKENS,
        }).encode("utf-8")

        request = urllib.request.Request(
            VISION_API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=VISION_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
        message = body["choices"][0]["message"]
        raw = message.get("content") or ""
        if not raw.strip():
            # 推理吃光額度時 content 為 None；不解析 reasoning_content（內含
            # 推理散文，欄位不可靠），交由呼叫端重試。
            result["error"] = "content 為空（推理用盡額度）"
            return result
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        return result

    result["raw"] = raw

    m_legs = re.search(r"LEGS\s*=\s*(\d+)", raw, re.I)
    if m_legs:
        result["legs"] = int(m_legs.group(1))

    m_limbs = re.search(r"LIMBS\s*=\s*(\w+)", raw, re.I)
    if m_limbs:
        result["limbs_correct"] = m_limbs.group(1).lower() == "correct"

    m_occ = re.search(r"OCCLUDED\s*=\s*(\w+)", raw, re.I)
    if m_occ:
        result["occluded"] = m_occ.group(1).lower() == "yes"

    m_face = re.search(r"FACE\s*=\s*(\w+)", raw, re.I)
    if m_face:
        result["face_ok"] = m_face.group(1).lower() == "correct"

    m_text = re.search(r"TEXT\s*=\s*(\w+)", raw, re.I)
    if m_text:
        result["text_free"] = m_text.group(1).lower() == "none"

    m_pose = re.search(r"POSE\s*=\s*([^\n]+)", raw, re.I)
    if m_pose:
        result["pose"] = m_pose.group(1).strip().lower().replace(" ", "_")

    if result["limbs_correct"] is None:
        result["error"] = "無法解析 LIMBS= 欄位"
        return result

    # 機械一致性：可見腳數與 LIMBS= 互相矛盾時，以腳數為準。
    # 正常解剖最多 4 肢；>4 即多長。<4 且未被遮住即少長。
    legs = result["legs"]
    if legs is not None:
        if legs > 4:
            result["limbs_correct"] = False
        elif legs < 4 and result["occluded"] is False:
            result["limbs_correct"] = False

    result["ok"] = True
    return result


def verify_image(image_path):
    """驗圖（含一次重試）。

    第一次解析不完整時再試一次，並合併兩次的欄位（任一次解析到就採用），
    避免第二次回應缺欄位時把第一次已解析到的資訊丟掉。
    """
    first = verify_pose_via_vision(image_path)
    if first["ok"] and first["face_ok"] is not None and first["text_free"] is not None:
        return first

    log(f"    驗圖未解析完整，重試一次：{first['error'] or '缺少欄位'}")
    second = verify_pose_via_vision(image_path)

    merged = dict(second)
    for key in ("legs", "occluded", "limbs_correct", "face_ok", "text_free"):
        if merged.get(key) is None and first.get(key) is not None:
            merged[key] = first[key]
    if merged.get("pose", "unclear") == "unclear" and first.get("pose") not in (None, "unclear"):
        merged["pose"] = first["pose"]
    if not merged.get("ok"):
        return second
    return merged


def save_pose_verification(records, today):
    """寫入當日視覺驗圖結果 JSON（覆寫，不累積歷史）。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"verification-{today}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return path


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
                shape=metadata.get("shape"),
                pose=metadata.get("pose"),
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
            # 失敗的熊熊也占用一個館藏編號，避免後續成功者與前一支重號
            collection_no += 1
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


def _generate_one_image(prompt, name, style, output, slot, config, comfyui_online, seed=None):
    """生一張圖（ComfyUI 優先，失敗改 MiniMax）。

    失敗時錯誤訊息寫在 LAST_IMAGE_ERROR，由呼叫端讀取。
    """
    global LAST_IMAGE_ERROR, LAST_IMAGE_BACKEND
    LAST_IMAGE_ERROR = ""
    LAST_IMAGE_BACKEND = ""

    errors = []
    ok = False
    if comfyui_online:
        ok = generate_comfyui_image(prompt, name, style, output, slot, config, seed=seed)
        if not ok:
            errors.append(f"comfyui: {LAST_IMAGE_ERROR or '未知錯誤'}")
    if not ok:
        if comfyui_online:
            log(f"  ComfyUI 無效，改用 MiniMax: {name}")
        ok = generate_minimax_image(prompt, name, style, output, slot, config)
        if not ok:
            errors.append(f"minimax: {LAST_IMAGE_ERROR or '未知錯誤'}")

    if not ok:
        LAST_IMAGE_ERROR = "；".join(errors) or "生圖失敗（無詳細錯誤訊息）"
        LAST_IMAGE_BACKEND = "comfyui+minimax" if len(errors) > 1 else (
            "comfyui" if errors and errors[0].startswith("comfyui") else "minimax-api"
        )
    return ok


def step_generate_images(prompt_results, today, config, comfyui_online):
    """步驟 4：依已產生的 prompt 生圖到暫存目錄，並做視覺驗圖。

    回傳 (generated, failed_count)。failed 的熊熊已在上一步被標記，
    此處直接略過（不使用模板 C 補位）。

    驗圖重生的唯一觸發條件是「肢體數量錯誤」（多長／少長／畸形）。
    姿勢（坐／站／躺／跳…）一律不觸發重生（2026-10-29 補充 S3/S4）。
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
    verification_records = []

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
        composition = metadata.get("composition", "")

        ok = _generate_one_image(prompt, name, style, output, slot, config, comfyui_online)

        # 生圖失敗也要記錄（階段 image_generation），否則生圖端金鑰失效會完全靜默
        if not ok:
            failed += 1
            err_msg = LAST_IMAGE_ERROR or "生圖失敗（無詳細錯誤訊息）"
            backend = LAST_IMAGE_BACKEND or "image-api"
            record_failure(
                today, collection_no, name, 1, err_msg,
                stage="image_generation", backend=backend,
            )

        # ---- 視覺驗圖 ----
        history = []
        attempt = 1
        verification = None
        if ok:
            log(f"  視覺驗圖: {name}（構圖：{composition or '未指定'}）")
            verification = verify_image(output)
            if not verification["ok"]:
                log(f"    視覺驗圖無法判定（{verification['error']}），保留原圖不重生")
                history.append({
                    "attempt": attempt,
                    "legs": verification["legs"],
                    "occluded": verification["occluded"],
                    "pose": verification["pose"],
                    "limbs_correct": None,
                    "face_ok": None,
                    "text_free": None,
                    "regenerated": False,
                })
            else:
                history.append({
                    "attempt": attempt,
                    "legs": verification["legs"],
                    "occluded": verification["occluded"],
                    "pose": verification["pose"],
                    "limbs_correct": verification["limbs_correct"],
                    "face_ok": verification["face_ok"],
                    "text_free": verification["text_free"],
                    "regenerated": False,
                })
                log(
                    f"    驗圖結果：看得見 {verification['legs']} 隻腳 / "
                    f"被身體遮住 {'Y' if verification['occluded'] else 'N'} / "
                    f"姿勢 {verification['pose']} / "
                    f"肢體正確 {'Y' if verification['limbs_correct'] else 'N'} / "
                    f"熊臉正確 {'Y' if verification['face_ok'] else 'N'} / "
                    f"無文字 {'Y' if verification['text_free'] else 'N'}"
                )

                # 重生觸發：S4 的三項失敗條件 —— 熊臉不對 / 肢體數量錯誤 / 出現可讀文字。
                # 姿勢（坐／站／躺／跳…）一律不觸發重生（S3）。
                regen_clause = ""
                if verification["face_ok"] is False:
                    regen_clause = FACE_REGENERATE_CLAUSE
                    reason = "熊臉不正確"
                elif verification["limbs_correct"] is False:
                    regen_clause = LIMB_REGENERATE_CLAUSE
                    reason = "肢體數量錯誤"
                elif verification["text_free"] is False:
                    regen_clause = TEXT_REGENERATE_CLAUSE
                    reason = "畫面出現可讀文字"

                if regen_clause:
                    history[-1]["regenerated"] = True
                    regen_prompt = f"{prompt.rstrip('., ')}, {regen_clause}"
                    for regen in range(1, VERIFY_REGENERATE_MAX + 1):
                        log(f"    {reason} → 重生第 {regen}/{VERIFY_REGENERATE_MAX} 次")
                        seed = int(time.time() * 1000) % (2**32) + regen
                        regen_ok = _generate_one_image(
                            regen_prompt, name, style, output, slot, config,
                            comfyui_online, seed=seed,
                        )
                        if not regen_ok:
                            log("    重生失敗，保留原圖")
                            break
                        attempt += 1
                        verification = verify_image(output)
                        if not verification["ok"]:
                            log(f"    重生後視覺驗圖無法判定（{verification['error']}），保留最後一張")
                            history.append({
                                "attempt": attempt,
                                "legs": None,
                                "occluded": None,
                                "pose": "unclear",
                                "limbs_correct": None,
                                "face_ok": None,
                                "text_free": None,
                                "regenerated": False,
                            })
                            break
                        history.append({
                            "attempt": attempt,
                            "legs": verification["legs"],
                            "occluded": verification["occluded"],
                            "pose": verification["pose"],
                            "limbs_correct": verification["limbs_correct"],
                            "face_ok": verification["face_ok"],
                            "text_free": verification["text_free"],
                            "regenerated": False,
                        })
                        log(
                            f"    重生後驗圖：看得見 {verification['legs']} 隻腳 / "
                            f"被身體遮住 {'Y' if verification['occluded'] else 'N'} / "
                            f"姿勢 {verification['pose']} / "
                            f"肢體正確 {'Y' if verification['limbs_correct'] else 'N'} / "
                            f"熊臉正確 {'Y' if verification['face_ok'] else 'N'} / "
                            f"無文字 {'Y' if verification['text_free'] else 'N'}"
                        )
                        still_bad = (
                            verification["face_ok"] is False
                            or verification["limbs_correct"] is False
                            or verification["text_free"] is False
                        )
                        if not still_bad:
                            break
                    else:
                        log(f"    重生 {VERIFY_REGENERATE_MAX} 次後仍未通過，保留最後一張")

        if verification is not None:
            verification_records.append({
                "name": name,
                "composition": composition,
                "shape": metadata.get("shape", {}).get("zh", ""),
                "pose": metadata.get("pose", {}).get("zh", ""),
                "attempts": attempt,
                "final_legs": verification["legs"],
                "final_occluded": verification["occluded"],
                "final_pose": verification["pose"],
                "limbs_correct": verification["limbs_correct"],
                "face_ok": verification["face_ok"],
                "text_free": verification["text_free"],
                "history": history,
            })

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

    if verification_records:
        path = save_pose_verification(verification_records, today)
        log(f"視覺驗圖結果已寫入: {path}")

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
        lines.append(f"  造型      : {metadata.get('shape', {}).get('zh', '')} ({metadata.get('shape', {}).get('en', '')})")
        lines.append(f"  姿勢      : {metadata.get('pose', {}).get('zh', '')} ({metadata.get('pose', {}).get('en', '')})")
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
    init_log_file(today, dry_run=config.dry_run, suffix=config.log_suffix)

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

    # 預覽模式（step2）不產出圖，這一筆風格/造型/姿勢並沒有真的被使用；
    # 若寫成可解析的「風格: [...]」「造型: [...]」「姿勢: [...]」會被歷史
    # 解析器當成當天的正式紀錄（解析器取第一個匹配，預覽紀錄會蓋掉真正紀錄）。
    # 因此預覽改用不可解析的標籤。
    is_preview = config.mode == "step2"
    style_label = "風格(預覽)" if is_preview else "風格"
    shape_label = "造型(預覽)" if is_preview else "造型"
    pose_label = "姿勢(預覽)" if is_preview else "姿勢"
    log(f"{style_label}: {style_zhs}")

    # 造型池與姿勢池：與風格同構的「最近 3 天不抽 / 14 天降權 / 同日不重複」
    shapes = select_shapes(num_bears, today, history=load_shape_history())
    shape_zhs = [s.get("zh", "") for s in shapes]
    log(f"{shape_label}: {shape_zhs}")

    poses = select_poses(num_bears, today, history=load_pose_history())
    pose_zhs = [p.get("zh", "") for p in poses]
    log(f"{pose_label}: {pose_zhs}")

    if config.mode == "step2":
        log(f"配送隻數: ComfyUI {config.comfy_count} + MiniMax {config.minimax_count} = {num_bears}")
        for i, (name, style) in enumerate(zip(bear_names, styles), start=1):
            kind = "ComfyUI" if i <= config.comfy_count else "MiniMax"
            style_zh = style.get("zh", str(style)) if isinstance(style, dict) else style
            shape_zh = shapes[i - 1].get("zh", "") if i <= len(shapes) else ""
            pose_zh = poses[i - 1].get("zh", "") if i <= len(poses) else ""
            log(f"  #{i} [{kind}]: {name} / {style_zh} / {shape_zh} / {pose_zh}")
        log("\n[step2] 預覽完成，未生圖、未更新詞彙輪流")
        return 0

    log("\n--- 步驟 3: 準備目錄 ---")
    if not config.dry_run:
        (config.temp_dir / today).mkdir(parents=True, exist_ok=True)
        (config.dest_dir / today).mkdir(parents=True, exist_ok=True)

    # 當天不重複的背景與構圖
    scenes = select_day_scenes(num_bears)

    # --compositions：只覆寫每筆 scene 的 composition 欄位（背景不動）
    if config.compositions:
        overrides = [c.strip() for c in config.compositions.split(",") if c.strip()]
        for i, comp in enumerate(overrides):
            if i < len(scenes):
                scenes[i]["composition"] = comp
        log(f"構圖覆寫: {overrides}")

    metadata_list = [
        prepare_bear_metadata(
            name, style, scene=scenes[i],
            shape=shapes[i] if i < len(shapes) else None,
            pose=poses[i] if i < len(poses) else None,
        )
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
            send_failure_summary(today, total, enabled=config.notify,
                               prompt_results=prompt_results)
            return 1
        send_failure_summary(today, total, enabled=config.notify,
                               prompt_results=prompt_results)
        log("dry-run 完成：未生圖、未寫 bears.json、未 commit、未 deploy")
        return 0

    if failed and failed == len(metadata_list):
        log("")
        log("!!! 全部失敗，中止配送")
        log("配送已中止，未寫入 bears.json、未 commit、未 deploy。")
        send_failure_summary(today, len(metadata_list), enabled=config.notify,
                           prompt_results=prompt_results)
        return 1

    log("\n--- 步驟 4b: 生成圖片 ---")
    if failed:
        log(f"（{failed} 隻因提示詞生成失敗而跳過，不使用模板 C 補位）")
    generated, failed = step_generate_images(prompt_results, today, config, comfyui_online)

    if config.mode == "step4":
        log("\n[step4] 生圖完成，圖片保留於暫存目錄，未複製、未更新 bears.json")
        send_failure_summary(today, len(metadata_list), enabled=config.notify,
                           prompt_results=prompt_results)
        return 0

    log("\n--- 步驟 5: 更新熊熊博物館 ---")
    new_bears = step_update_museum(generated, today, config)

    if config.mode == "step5":
        log("\n[step5] 博物館更新完成，未 commit、未部署")
        send_failure_summary(today, len(metadata_list), enabled=config.notify,
                           prompt_results=prompt_results)
        return 0

    if not new_bears:
        log("\n沒有新增熊熊，跳過 commit 與部署")
        send_failure_summary(today, len(metadata_list), enabled=config.notify,
                           prompt_results=prompt_results)
        return 0

    if failed:
        fallback_note = (
            "有部分熊熊使用模板 C 補位" if _fallback_used_in_batch(prompt_results)
            else "未使用模板 C 補位"
        )
        log(
            f"⚠️ 熊熊配送部分失敗：{today} 共 {len(metadata_list)} 隻中 {failed} 隻失敗"
            f"（{fallback_note}），已成功產生 {len(new_bears)} 隻。"
        )

    # 在 commit/deploy 前先送彙總，避免部署失敗中斷流程時漏發通知
    send_failure_summary(today, len(metadata_list), enabled=config.notify,
                           prompt_results=prompt_results)

    log("\n--- 步驟 6: Git Commit ---")
    run_cmd(f"cd {PROJECT_DIR} && git add bears.json bears/ vocabulary/style-rotation.json vocabulary/daily-delivery.py vocabulary/bear-conditions.json vocabulary/bear-textures.json vocabulary/bear-backgrounds.json vocabulary/bear-friends.json vocabulary/bear-shapes.json vocabulary/bear-poses.json")
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
    parser.add_argument("--log-suffix", default="",
                        help="log 檔名後綴（例：-trial → logs/2026-10-29-trial.log；不影響歷史統計）")
    parser.add_argument("--compositions", default="",
                        help="以逗號分隔指定當天各隻的構圖，覆寫隨機選樣（例：a,b,c）")
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
        log_suffix=args.log_suffix,
        compositions=args.compositions,
    )

    globals()["HERMES_API_URL"] = args.hermes_api_url

    try:
        sys.exit(main(config))
    except SystemExit:
        raise
    except Exception as e:
        # 未預期的例外：仍要把已累積的失敗彙總送出去，避免靜默失敗
        print(f"ERROR: 熊熊配送未預期中止: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        try:
            send_failure_summary(get_today(), config.total_count, enabled=config.notify)
        except Exception:
            pass
        raise
