#!/usr/bin/env python3
"""
喵時光每日配送計畫 - 自動化配送腳本

步驟：
1. 檢查 ComfyUI 狀態
2. 取得風格（從 meow-style-rotation.json）
3. 準備目錄
4. 產生 metadata → MiniMax Chat 產英文 prompt → 生圖
5. 複製圖片並更新 cats.json
6. Git commit + push
7. 部署 Cloudflare Pages
"""

import argparse
import base64
import json
import os
import re
import shutil

import subprocess
import sys
import uuid
import requests
import urllib.request
from datetime import datetime, date
from pathlib import Path


# ===== 故事類型配置 =====
STORY_TYPES = ["日常生活", "冒險", "探險", "悠閒生活", "炸毛生活"]
STORY_TYPE_FILE = None  # 稍後在 setup_variables() 中設定


def setup_variables():
    """延遲初始化需要 PROJECT_DIR 的變數"""
    global STORY_TYPE_FILE
    STORY_TYPE_FILE = PROJECT_DIR / "cats-images" / "story-type-tracker.json"


def load_story_tracker():
    """載入故事類型追蹤"""
    if STORY_TYPE_FILE.exists():
        with open(STORY_TYPE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"used_types": [], "last_index": -1}


def save_story_tracker(tracker):
    """保存故事類型追蹤"""
    with open(STORY_TYPE_FILE, 'w', encoding='utf-8') as f:
        json.dump(tracker, f, ensure_ascii=False, indent=2)


def get_next_story_type():
    """取得下一個故事類型，14天內每種至少一次"""
    tracker = load_story_tracker()
    used = tracker.get("used_types", [])
    last_idx = tracker.get("last_index", -1)
    
    # 找出還沒用過的類型
    available = [t for t in STORY_TYPES if t not in used]
    
    if available:
        # 有還沒用過的，隨機選一個
        story_type = random.choice(available)
    else:
        # 都用過了，從全部類型中選（排除上一個）
        candidates = [t for t in STORY_TYPES if t != STORY_TYPES[last_idx] % len(STORY_TYPES)]
        story_type = random.choice(candidates)
    
    # 更新追蹤
    idx = STORY_TYPES.index(story_type)
    tracker["used_types"] = used[-13:]  # 保留最近14種
    tracker["last_index"] = idx
    tracker["last_date"] = get_today()
    save_story_tracker(tracker)
    
    return story_type


def generate_story_from_vocab(story_type):
    """從詞彙庫生成50字內的小故事（本地 fallback）"""
    return generate_story_fallback(story_type)


def split_story_to_frames(story_text):
    """將故事切割為4個分鏡"""
    # 簡單切割：根據句號、頓號、或直接均分
    if "、" in story_text:
        parts = story_text.split("、")
        if len(parts) >= 4:
            return [p.strip() + "。" for p in parts[:4]]

    # 均分為4句
    words = story_text.replace("的", "的 ").split()
    if len(words) >= 4:
        frame_size = len(words) // 4
        frames = []
        for i in range(4):
            start = i * frame_size
            end = start + frame_size if i < 3 else len(words)
            frame = "".join(words[start:end])
            frames.append(frame + "。")
        return frames

    # 回退：如果無法切割，返回4個相同的框架描述
    return [
        story_text + "的開始。",
        story_text + "的發展。",
        story_text + "的高潮。",
        story_text + "的結局。"
    ]

import random

# ===== 故事生成系統 =====

STORY_GENERATION_PROMPT = """你是喵喵故事的創作者。

任務：為橘貓妹妹「喵喵公主」創作一個50字以內的小故事。

故事類型：{story_type}

要求：
- 故事要溫暖、療癒
- 適合小貓咪的日常生活場景
- 50字以內（中文）
- 不需要標點符號結尾
- 只需要輸出故事文字，不需要任何說明

直接輸出故事："""


def read_story_from_file(story_type, today):
    """從 story-today.txt 讀取故事（熊熊創作）"""
    story_file = PROJECT_DIR / "cats-images" / "story-today.txt"
    if not story_file.exists():
        return None
    content = story_file.read_text(encoding="utf-8").strip()
    
    # 跳過前三行 metadata（故事類型、日期、空行）
    lines = content.split('\n')
    story_lines = []
    in_poem = False
    for i, line in enumerate(lines):
        # 跳過前3行的 metadata
        if i < 3:
            continue
        # 跳過空行
        if line.strip() == '' and not in_poem:
            continue
        # 跳過詩的標題行（以《》包圍）
        if line.strip().startswith('《') and line.strip().endswith('》'):
            in_poem = True
            continue
        if line.strip():
            story_lines.append(line.strip())
    
    if story_lines:
        story_text = '\n'.join(story_lines)
        log(f"  熊熊故事: {story_text[:50]}...")
        return story_text
    return None


def generate_story_via_minimax(story_type):
    """用 MiniMax Chat API 生成故事"""
    today = get_today()
    
    # 優先讀取熊熊寫的故事
    bear_story = read_story_from_file(story_type, today)
    if bear_story:
        return bear_story
    
    prompt = STORY_GENERATION_PROMPT.format(story_type=story_type)
    log(f"  MiniMax 生成故事 (類型: {story_type})")

    try:
        response = requests.post(
            MINIMAX_CHAT_URL,
            headers={
                "Authorization": f"Bearer {MINIMAX_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MINIMAX_CHAT_MODEL,
                "messages": [
                    {"role": "system", "content": "你是喵喵故事的創作者，擅長創作溫暖療癒的小貓咪故事。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.9,
                "max_completion_tokens": 100,
                "extra_body": {
                    "reasoning_split": True,
                    "thinking": {"type": "disabled"},
                },
            },
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()

        base_resp = body.get("base_resp", {})
        if base_resp.get("status_code", 0) not in (0, None):
            raise RuntimeError(base_resp.get("status_msg", "MiniMax chat API error"))

        choices = body.get("choices", [])
        if not choices:
            raise RuntimeError("MiniMax chat 無 choices")

        content = choices[0].get("message", {}).get("content", "").strip()
        # 清理可能的引號
        content = content.strip("\"'\"\"")
        log(f"  生成故事: {content}")
        return content
    except Exception as e:
        log(f"  MiniMax 故事生成失敗: {e}，使用 fallback")
        return generate_story_fallback(story_type)


def generate_story_fallback(story_type):
    """故事生成失敗時的本地 fallback"""
    vocab = load_json(VOCABULARY)
    categories = list(vocab["categories"].keys())
    selected_cats = random.sample(categories, min(2, len(categories)))
    words = []
    for cat in selected_cats:
        cat_words = vocab["categories"][cat].get("words", [])
        if cat_words:
            words.extend(random.sample(cat_words, min(3, len(cat_words))))
    if "情緒系" in vocab["categories"]:
        emotion_words = vocab["categories"]["情緒系"].get("words", [])
        if emotion_words:
            words.append(random.choice(emotion_words))
    story_words = random.sample(words, min(5, len(words)))
    story = "、".join(story_words[:4]) + "的" + random.choice(["日常", "時光", "物語"])
    if len(story) > 50:
        story = story[:47] + "..."
    return story


def generate_story_from_vocab(story_type):
    """從詞彙庫生成50字內的小故事（本地 fallback）"""
    return generate_story_fallback(story_type)


def split_story_to_frames(story_text):
    """將故事切割為4個分鏡"""
    # 簡單切割：根據句號、頓號、或直接均分
    if "、" in story_text:
        parts = story_text.split("、")
        if len(parts) >= 4:
            return [p.strip() + "。" for p in parts[:4]]

    # 均分為4句
    words = story_text.replace("的", "的 ").split()
    if len(words) >= 4:
        frame_size = len(words) // 4
        frames = []
        for i in range(4):
            start = i * frame_size
            end = start + frame_size if i < 3 else len(words)
            frame = "".join(words[start:end])
            frames.append(frame + "。")
        return frames

    # 回退：如果無法切割，返回4個相同的框架描述
    return [
        story_text + "的開始。",
        story_text + "的發展。",
        story_text + "的高潮。",
        story_text + "的結局。"
    ]


import random


# =====設定 =====
PROJECT_DIR = Path("/home/fjj04/my-bear-museum")
CATS_JSON = PROJECT_DIR / "cats-images" / "cats.json"
DEFAULT_TEMP_DIR = Path("/home/fjj04/cats")
DEFAULT_DEST_DIR = PROJECT_DIR / "cats-images"
VOCAB_DIR = PROJECT_DIR / "vocabulary"
LOG_DIR = VOCAB_DIR / "logs"
MEOW_CHARACTER = PROJECT_DIR / "cats-images" / "meow-character.json"
MEOW_STYLE_ROTATION = PROJECT_DIR / "cats-images" / "meow-style-rotation.json"
VOCABULARY = VOCAB_DIR / "vocabulary.json"

COMFYUI_URL = "http://fjjhomei9.fjjhome:8188"
COMFY_WORKFLOW = Path("/home/fjj04/comfyui/Flux.2-Klein-文生图_API.json")
COMFY_SCRIPT_DIR = Path("/home/fjj04/.hermes/skills_custom/comfyui-gen-image/scripts")

MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", os.popen("grep MINIMAX_API_KEY /home/fjj04/.hermes/.env | cut -d'=' -f2").read().strip())
MINIMAX_IMAGE_URL = "https://api.minimax.io/v1/image_generation"
MINIMAX_CHAT_URL = "https://api.minimax.io/v1/chat/completions"
MINIMAX_CHAT_MODEL = "MiniMax-M2.5-highspeed"

PROMPT_QUALITY_SUFFIX = (
    "soft kawaii style, cute cat illustration, "
    "high quality illustration, detailed fur texture"
)

PROMPT_SYSTEM = """You are an expert at writing English text-to-image prompts for cute kawaii cat characters.

Given cat metadata in Traditional Chinese, write ONE detailed English image generation prompt.

Rules:
- Character description (MUST include in every prompt):
  * Orange tabby cat with fluffy orange fur
  * Gold bell collar with a small golden bell
  * Milk tea colored eyes (light brown/hazel)
- Translate the art style to English (e.g. 油畫=oil painting, 水墨=ink wash painting, 黏土=clay art)
- Describe a vivid scene with atmosphere and magical lighting
- Write as a single English paragraph
- Do NOT include Chinese characters or the raw Chinese cat name
- Must end with: soft kawaii style, cute cat illustration, high quality illustration, detailed fur texture
- Output ONLY the prompt text, no quotes, no explanation, no markdown"""


class DeliveryConfig:
    def __init__(
        self,
        temp_dir=DEFAULT_TEMP_DIR,
        dest_dir=DEFAULT_DEST_DIR,
        minimax_size="1:1",
        comfy_width=1024,
        comfy_height=1024,
        comfy_count=0,
        minimax_count=7,
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
    _log_file = LOG_DIR / f"meow-{today}.log"


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


def peek_styles(n=7):
    """取得接下來 n 個風格，但不更新 index"""
    rotation = load_json(MEOW_STYLE_ROTATION)
    styles = rotation.get("styles", [])
    current_index = rotation.get("current_index", 0)
    return [styles[(current_index + i) % len(styles)] for i in range(n)], current_index


def get_next_styles(n=7):
    """取得接下來 n 個風格，並更新 index"""
    selected, current_index = peek_styles(n)
    rotation = load_json(MEOW_STYLE_ROTATION)
    rotation["current_index"] = (current_index + n) % len(rotation["styles"])
    rotation["last_updated"] = get_today()
    save_json(MEOW_STYLE_ROTATION, rotation)
    return selected


def get_random_breed():
    """取得隨機貓咪品種"""
    character = load_json(MEOW_CHARACTER)
    breeds = character.get("breeds", [])
    return random.choice(breeds) if breeds else "橘貓"


def get_random_scene(scene_type="4grid"):
    """取得隨機場景"""
    character = load_json(MEOW_CHARACTER)
    if scene_type == "4grid":
        scenes = character.get("4grid_scenes", [])
    else:
        scenes = character.get("single_scenes", [])
    return random.choice(scenes) if scenes else "日常時光"


def get_random_theme():
    """從 vocabulary 取得隨機主題"""
    vocab = load_json(VOCABULARY)
    categories = ["自然系", "天空系", "甜點系", "花卉系", "夢幻系", "童話系"]
    cat = random.choice(categories)
    words = vocab.get("categories", {}).get(cat, {}).get("words", [])
    return random.choice(words) if words else "日常"


def get_random_mode():
    """取得喵喵公主的隨機模式"""
    modes = ["公主", "日常", "Just貓", "神秘"]
    return random.choice(modes)


def meow_filename(type_name, today, index, frame_num=None):
    """喵喵圖片檔名：miaomiao_類型_日期_序號.jpg"""
    if frame_num is not None:
        return f"miaomiao_{type_name}_{today.replace('-', '')}_{index:02d}_{frame_num:02d}.jpg"
    return f"miaomiao_{type_name}_{today.replace('-', '')}_{index:02d}.jpg"


def cat_filename(today, index, style):
    """多元內容圖片檔名：cat_風格_日期_序號.jpg"""
    style_key = style.replace(" ", "_").replace("風", "").replace("類", "")
    return f"cat_{style_key}_{today.replace('-', '')}_{index:02d}.jpg"


def meow_img_path(config, today, filename):
    rel = (config.dest_dir / today / filename).relative_to(PROJECT_DIR)
    return str(rel).replace("\\", "/")


def prepare_meow_metadata(type_name, style, story_text=None, story_type=None, frame_num=None):
    """產生喵喵的 metadata"""
    character = load_json(MEOW_CHARACTER)
    scene = get_random_scene(type_name)
    mode = get_random_mode()
    result = {
        "name": character["固定角色"]["name"],
        "type": type_name,
        "style": style,
        "mode": mode,
        "scene": scene,
    }
    if story_text is not None:
        result["story_text"] = story_text
    if story_type is not None:
        result["story_type"] = story_type
    if frame_num is not None:
        result["frame_num"] = frame_num
    return result


def prepare_cat_metadata(breed, style, theme):
    """產生多元內容的 metadata"""
    return {
        "name": f"{breed}的日常",
        "breed": breed,
        "style": style,
        "theme": theme,
    }


def make_meow_record(metadata, today, index, config, filename):
    record = {
        "name": metadata["name"],
        "type": metadata["type"],
        "date": today,
        "checkIn": today.replace("-", "") + f"-{index:02d}",
        "title": metadata.get("scene", metadata.get("story_text", "")),
        "style": metadata["style"],
        "mode": metadata.get("mode", ""),
        "img": meow_img_path(config, today, filename),
    }
    if metadata.get("story_text"):
        record["story_text"] = metadata["story_text"]
    if metadata.get("story_type"):
        record["story_type"] = metadata["story_type"]
    if metadata.get("frame_num"):
        record["frame_num"] = metadata["frame_num"]
    return record


def make_cat_record(metadata, today, index, config, filename):
    return {
        "name": metadata["name"],
        "breed": metadata["breed"],
        "date": today,
        "checkIn": today.replace("-", "") + f"-{index:02d}",
        "title": metadata["theme"],
        "style": metadata["style"],
        "breed": metadata["breed"],
        "img": meow_img_path(config, today, filename),
    }


def clean_minimax_text(content):
    """移除 MiniMax thinking 區塊與多餘包裝。"""
    if not content:
        return ""

    for pattern in (r"\s*", r"</thinking>\s*"):
        parts = re.split(pattern, content, flags=re.IGNORECASE)
        if len(parts) > 1:
            return parts[-1].strip().strip("\"'")

    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    for paragraph in reversed(paragraphs):
        lower = paragraph.lower()
        if "cat" in lower and ("kawaii" in lower or "illustration" in lower):
            return paragraph.strip("\"'")

    return content.strip().strip("\"'")


def build_prompt_fallback(name, type_name, style, mode, scene):
    """MiniMax 失敗時的本地 fallback prompt。"""
    return (
        f"A cute adorable orange cat, {name}, {mode} mode, "
        f"scene: {scene}, {style} art style, dreamy atmosphere, "
        f"{PROMPT_QUALITY_SUFFIX}"
    )


def generate_prompt_via_minimax(name, type_name, style, mode, scene):
    """用 MiniMax Chat API 依 metadata 產生英文生圖 prompt。"""
    user_content = (
        f"Cat name: {name}\n"
        f"Type: {type_name}\n"
        f"Mode: {mode}\n"
        f"Style: {style}\n"
        f"Scene: {scene}"
    )
    log(f"  MiniMax 產生 prompt: {name} ({type_name})")

    try:
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
                "max_completion_tokens": 512,
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

        content = clean_minimax_text(choices[0].get("message", {}).get("content", ""))
        if not content:
            raise RuntimeError("MiniMax chat 回傳空 prompt")

        lower = content.lower()
        if not (
            "soft kawaii style" in lower
            and "cat" in lower
            and "illustration" in lower
        ):
            content = f"{content.rstrip('., ')}, {PROMPT_QUALITY_SUFFIX}"

        log(f"  prompt: {content}")
        return content
    except Exception as e:
        log(f"  MiniMax prompt 生成失敗: {e}，使用 fallback")
        fallback = build_prompt_fallback(name, type_name, style, mode, scene)
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


def generate_minimax_image(prompt, title, style, output_path, idx, config):
    log(f"MiniMax #{idx+1}: {title} ({style}) [{config.minimax_size}]")

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


def add_cats_to_json(new_cats):
    data = load_json(CATS_JSON)
    data["cats"].extend(new_cats)
    data["last_updated"] = get_today()
    save_json(CATS_JSON, data)
    log("已更新 cats.json")


def step_generate_images(items, today, config, comfyui_online):
    """步驟 4：產生圖片到暫存目錄"""
    today_dir = config.temp_dir / today
    today_dir.mkdir(parents=True, exist_ok=True)

    log(f"配送計畫: MiniMax {len(items)} 張（ComfyUI {'在線' if comfyui_online else '離線'}）")

    generated = []
    slot = 0

    for item in items:
        metadata = item["metadata"]
        output = today_dir / item["filename"]

        prompt = generate_prompt_via_minimax(
            metadata.get("name", "喵喵"),
            metadata.get("type", "single"),
            metadata.get("style", "水彩"),
            metadata.get("mode", "日常"),
            metadata.get("scene", metadata.get("theme", "日常")),
        )

        if generate_minimax_image(prompt, metadata.get("name", "喵喵"), metadata.get("style", "水彩"), output, slot, config):
            generated.append({
                "metadata": metadata,
                "filename": item["filename"],
                "temp_path": output,
                "prompt": prompt,
            })
            slot += 1

    log(f"共生成 {len(generated)} 張圖片於 {today_dir}")
    return generated


def step_update_meow_time(generated, today, config):
    """步驟 5：複製圖片到目錄並更新 cats.json"""
    meow_dir = config.dest_dir / today
    meow_dir.mkdir(parents=True, exist_ok=True)

    new_cats = []

    for item in generated:
        filename = item["filename"]
        dest = meow_dir / filename
        shutil.copy2(item["temp_path"], dest)
        log(f"已複製: {filename} → {dest}")

        metadata = item["metadata"]
        if metadata.get("type") in ("4grid", "single"):
            new_cats.append(make_meow_record(metadata, today, len(new_cats) + 1, config, filename))
        else:
            new_cats.append(make_cat_record(metadata, today, len(new_cats) + 1, config, filename))

    if new_cats:
        add_cats_to_json(new_cats)
        log(f"新增 {len(new_cats)} 筆記錄")
    else:
        log("沒有新增記錄")

    return new_cats


def parse_size(value):
    if "x" in value.lower():
        w, h = value.lower().split("x", 1)
        return int(w), int(h)
    raise argparse.ArgumentTypeError("尺寸格式應為 WIDTHxHEIGHT，例如 1024x1024")


def main(config):
    setup_variables()  # 初始化需要 PROJECT_DIR 的變數
    today = get_today()
    init_log_file(today)

    log("===== 喵時光每日配送計畫 =====")
    if config.mode:
        log(f"模式: {config.mode}")
    log(f"今日日期: {today}")
    log(f"暫存目錄: {config.temp_dir / today}")
    log(f"目的目錄: {config.dest_dir / today}")

    log("\n--- 步驟 1: 檢查系統狀態 ---")
    comfyui_online = check_comfyui(config)
    log(f"ComfyUI: {'✓ 在線' if comfyui_online else '✗ 離線'}")

    log("\n--- 步驟 2: 取得風格 ---")
    styles = get_next_styles(9)  # 4 story + 1 single + 4 diverse = 9張圖
    log(f"風格 ({len(styles)}): {styles}")

    # 建立配送項目：三種配送
    # 1. 喵漫配送（story）- 4張分鏡圖
    # 2. 喵圖配送（single）- 1張圖片
    # 3. 多元內容配送（multi）- 4張圖片
    log("\n--- 步驟 3: 準備配送項目 ---")
    items = []

    # 取得故事類型
    story_type = get_next_story_type()
    log(f"  今日故事類型: {story_type}")
    
    # 生成故事（使用 MiniMax Chat API）
    story_text = generate_story_via_minimax(story_type)
    story_frames = split_story_to_frames(story_text)
    log(f"  故事內容: {story_text}")
    log(f"  分鏡數: {len(story_frames)}")

    # ===== 1. 喵漫配送（story）- 4張分鏡圖 =====
    for i, frame_text in enumerate(story_frames):
        metadata_story = prepare_meow_metadata(
            "story", 
            styles[i], 
            story_text=story_text,
            story_type=story_type,
            frame_num=i+1
        )
        filename_story = meow_filename("story", today, 1, frame_num=i+1)
        items.append({
            "metadata": metadata_story,
            "filename": filename_story,
            "story_text": story_text,
            "story_type": story_type,
            "frame_num": i+1
        })
        log(f"  喵漫{i+1}: {filename_story} ({styles[i]})")

    # ===== 2. 喵圖配送（single）- 1張圖片 =====
    metadata_single = prepare_meow_metadata("single", styles[4])
    filename_single = meow_filename("single", today, 1)
    items.append({
        "metadata": metadata_single,
        "filename": filename_single,
    })
    log(f"  喵圖: {filename_single} ({styles[4]})")

    # ===== 3. 多元內容配送（multi）- 4張圖片 =====
    breeds = ["英國短毛貓", "布偶貓", "黑貓", "三花貓"]
    for i in range(4):
        breed = breeds[i] if i < len(breeds) else get_random_breed()
        theme = get_random_theme()
        metadata = prepare_cat_metadata(breed, styles[5 + i], theme)
        # 使用新的多元內容命名
        filename = f"cat_{styles[5 + i].replace(' ', '')[:4]}_{today.replace('-', '')}_0{i+1}.jpg"
        items.append({
            "metadata": metadata,
            "filename": filename,
            "type": "multi"
        })
        log(f"  多元{i+1}: {filename} ({breed}/{styles[5 + i]})")

    if config.mode == "step2":
        log("\n[step2] 預覽完成，未生圖")
        return

    log("\n--- 步驟 4: 生成圖片 ---")
    generated = step_generate_images(items, today, config, comfyui_online)

    if config.mode == "step4":
        log("\n[step4] 生圖完成，圖片保留於暫存目錄，未複製、未更新 cats.json")
        return

    log("\n--- 步驟 5: 更新喵時光 ---")
    new_cats = step_update_meow_time(generated, today, config)

    if config.mode == "step5":
        log("\n[step5] 更新完成，未 commit、未部署")
        return

    if not new_cats:
        log("\n沒有新增記錄，跳過 commit 與部署")
        return

    log("\n--- 步驟 6: Git Commit ---")
    run_cmd(f"cd {PROJECT_DIR} && git add cats-images/cats.json cats-images/ vocabulary/meow-style-rotation.json vocabulary/story-type-tracker.json cats-images/daily-meow-delivery.py")
    run_cmd(f'cd {PROJECT_DIR} && git commit -m "新增 {today} 喵時光"')
    run_cmd(f"cd {PROJECT_DIR} && git push")
    log("Git push 完成")

    log("\n--- 步驟 7: 部署到 Cloudflare Pages ---")
    run_cmd(
        f"cd {PROJECT_DIR} && npx wrangler pages deploy . "
        f"--project-name kumaweb --branch main --no-install-skills --commit-dirty=true"
    )

    log("\n===== 完成 =====")
    log("到 https://kumaweb.pages.dev/cats.html 觀看結果")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="喵時光每日配送")
    parser.add_argument(
        "--mode",
        default="",
        choices=["", "step2", "step4", "step5"],
        help="step2=僅預覽, step4=僅生圖, step5=到更新資料庫",
    )
    parser.add_argument("--temp-dir", default=str(DEFAULT_TEMP_DIR), help="圖片暫存目錄")
    parser.add_argument("--dest-dir", default=str(DEFAULT_DEST_DIR), help="圖片目的目錄")
    parser.add_argument("--minimax-size", default="1:1", help="MiniMax 圖片比例，如 16:9 或 1:1")
    parser.add_argument("--comfy-size", default="1024x1024", type=parse_size, help="ComfyUI 圖片尺寸 WIDTHxHEIGHT")
    parser.add_argument("--comfy-count", type=int, default=0, help="ComfyUI 配送數量")
    parser.add_argument("--minimax-count", type=int, default=7, help="MiniMax 配送數量")
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