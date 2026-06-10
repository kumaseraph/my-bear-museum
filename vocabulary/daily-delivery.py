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

COMFYUI_URL = "http://fjjhomei9.fjjhome:8188"
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

PROMPT_SYSTEM = f"""You are an expert at writing English text-to-image prompts for cute kawaii bear museum characters.

Given bear metadata in Traditional Chinese, write ONE detailed English image generation prompt.

Rules:
- Infer fur color and scene from the bear name, personality, series, and title
- Translate the art style to English (e.g. 油畫=oil painting, 霓虹燈=neon light, 水彩=watercolor)
- Describe a vivid scene with atmosphere and magical lighting
- Write as a single English paragraph
- Do NOT include Chinese characters or the raw Chinese bear name
- Must end with: {PROMPT_QUALITY_SUFFIX}
- Output ONLY the prompt text, no quotes, no explanation, no markdown"""


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
    rotation = load_json(STYLE_ROTATION)
    styles = rotation.get("styles", [])
    current_index = rotation.get("current_index", 0)
    return [styles[(current_index + i) % len(styles)] for i in range(n)], current_index


def get_next_styles(n=8):
    selected, current_index = peek_styles(n)
    rotation = load_json(STYLE_ROTATION)
    rotation["current_index"] = (current_index + n) % len(rotation["styles"])
    rotation["last_updated"] = get_today()
    save_json(STYLE_ROTATION, rotation)
    return selected


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


def bear_img_path(config, today, name):
    rel = (config.dest_dir / today / f"{name}.png").relative_to(PROJECT_DIR)
    return str(rel).replace("\\", "/")


def derive_title(name):
    """從熊熊名字推斷稱號（如 彩霞追光者 → 追光者）。"""
    naming = load_json(BEAR_NAMING)
    suffixes = naming.get("parts", {}).get("suffix", {}).get("words", [])
    for suffix in sorted(suffixes, key=len, reverse=True):
        if suffix != "熊" and name.endswith(suffix):
            return suffix
    return name


def prepare_bear_metadata(name, style):
    """生圖前先產生熊熊 metadata，供 prompt 與 bears.json 共用。"""
    return {
        "name": name,
        "style": style,
        "series": get_random_series(),
        "personality": get_random_personality(style),
        "quote": get_random_quote(),
        "title": derive_title(name),
    }


def make_bear_record(metadata, today, collection_no, daily_index, config):
    return {
        "name": metadata["name"],
        "date": today,
        "checkIn": today.replace("-", "") + f"-{daily_index:02d}",
        "collectionNo": collection_no,
        "title": metadata["title"],
        "series": metadata["series"],
        "birthday": today,
        "personality": metadata["personality"],
        "quote": metadata["quote"],
        "img": bear_img_path(config, today, metadata["name"]),
    }


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


def build_prompt_fallback(name, style, series, personality, title):
    """MiniMax 失敗時的本地 fallback prompt。"""
    return (
        f"A cute adorable bear character, {title}, "
        f"inspired by {series}, {personality}, "
        f"{style} art style, dreamy atmosphere, "
        f"{PROMPT_QUALITY_SUFFIX}"
    )


def generate_prompt_via_minimax(name, style, series, personality, title):
    """用 MiniMax Chat API 依 metadata 產生英文生圖 prompt。"""
    user_content = (
        f"Bear name: {name}\n"
        f"Art style: {style}\n"
        f"Series: {series}\n"
        f"Title: {title}\n"
        f"Personality: {personality}"
    )
    log(f"  MiniMax 產生 prompt: {name}")

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
            and "16:9" in lower
            and "detailed fur texture" in lower
        ):
            content = f"{content.rstrip('., ')}, {PROMPT_QUALITY_SUFFIX}"

        log(f"  prompt: {content}")
        return content
    except Exception as e:
        log(f"  MiniMax prompt 生成失敗: {e}，使用 fallback")
        fallback = build_prompt_fallback(name, style, series, personality, title)
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
    log(f"MiniMax #{idx+1}: {bear_name} ({style}) [{config.minimax_size}]")

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
    if str(COMFY_SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(COMFY_SCRIPT_DIR))
    from gen_image import (
        load_workflow,
        patch_workflow,
        submit_workflow,
        poll_status,
        get_output_images,
        download_image,
    )
    return load_workflow, patch_workflow, submit_workflow, poll_status, get_output_images, download_image


def generate_comfyui_image(prompt, bear_name, style, output_path, idx, config):
    log(f"ComfyUI #{idx+1}: {bear_name} ({style}) [{config.comfy_width}x{config.comfy_height}]")

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

    for i in range(config.comfy_count):
        name, style = bear_names[i], styles[i]
        metadata = prepare_bear_metadata(name, style)
        log(
            f"  metadata: title={metadata['title']}, series={metadata['series']}, "
            f"personality={metadata['personality']}"
        )
        prompt = generate_prompt_via_minimax(
            metadata["name"],
            metadata["style"],
            metadata["series"],
            metadata["personality"],
            metadata["title"],
        )
        output = today_dir / f"{name}.png"

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
                "temp_path": output,
                "source": "comfy_or_fallback",
                "metadata": metadata,
                "prompt": prompt,
            })
            slot += 1

    for i in range(config.comfy_count, config.total_count):
        name, style = bear_names[i], styles[i]
        metadata = prepare_bear_metadata(name, style)
        log(
            f"  metadata: title={metadata['title']}, series={metadata['series']}, "
            f"personality={metadata['personality']}"
        )
        prompt = generate_prompt_via_minimax(
            metadata["name"],
            metadata["style"],
            metadata["series"],
            metadata["personality"],
            metadata["title"],
        )
        output = today_dir / f"{name}.png"
        if generate_minimax_image(prompt, name, style, output, slot, config):
            generated.append({
                "name": name,
                "style": style,
                "temp_path": output,
                "source": "minimax",
                "metadata": metadata,
                "prompt": prompt,
            })
            slot += 1

    log(f"共生成 {len(generated)} 張圖片於 {today_dir}")
    return generated


def step_update_museum(generated, today, config):
    """步驟 5：複製圖片到博物館並更新 bears.json"""
    museum_dir = config.dest_dir / today
    museum_dir.mkdir(parents=True, exist_ok=True)

    new_bears = []
    collection_no = get_max_collection_no() + 1

    for item in generated:
        dest = museum_dir / f"{item['name']}.png"
        shutil.copy2(item["temp_path"], dest)
        log(f"已複製: {item['name']}.png → {dest}")
        new_bears.append(make_bear_record(
            item["metadata"], today, collection_no, len(new_bears) + 1, config
        ))
        collection_no += 1

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
        styles, current_index = peek_styles(num_bears)
        log(f"風格輪流 index: {current_index}")
        log(f"配送隻數: ComfyUI {config.comfy_count} + MiniMax {config.minimax_count} = {num_bears}")
        log(f"熊熊 ({len(bear_names)}): {bear_names}")
        log(f"風格 ({len(styles)}): {styles}")
        for i, (name, style) in enumerate(zip(bear_names, styles), start=1):
            kind = "ComfyUI" if i <= config.comfy_count else "MiniMax"
            log(f"  #{i} [{kind}]: {name} / {style}")
        log("\n[step2] 預覽完成，未生圖、未更新詞彙輪流")
        return

    styles = get_next_styles(num_bears)
    log(f"熊熊: {bear_names}")
    log(f"風格: {styles}")

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
    run_cmd(f"cd {PROJECT_DIR} && git add bears.json bears/ vocabulary/style-rotation.json vocabulary/daily-delivery.py")
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
