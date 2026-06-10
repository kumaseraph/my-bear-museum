#!/usr/bin/env python3
"""
熊熊每日配送計畫 - 自動化配送腳本
克勞熊使用說明：
1. 檢查系統狀態 (ComfyUI + MiniMax)
2. 讀取今日風格
3. 生成圖片 (MiniMax 5張 16:9，若 ComfyUI 在線則再生成 3張)
4. 更新 bears.json
5. Commit + 部署
"""

import argparse
import os
import json
import shutil
import subprocess
import requests
import urllib.request
from datetime import datetime, date
from pathlib import Path
import random
import sys

# ===== 設定 =====
PROJECT_DIR = Path("/home/fjj04/my-bear-museum")
BEARS_JSON = PROJECT_DIR / "bears.json"
TEMP_DIR = Path("/home/fjj04/bears")
VOCAB_DIR = PROJECT_DIR / "vocabulary"
BEAR_NAMING = VOCAB_DIR / "bear-naming.json"
STYLE_ROTATION = VOCAB_DIR / "style-rotation.json"
BEAR_QUOTES = VOCAB_DIR / "bear-quotes.json"
WORLD_BUILDING = VOCAB_DIR / "world-building.json"
VOCABULARY = VOCAB_DIR / "vocabulary.json"

# API 設定
COMFYUI_URL = "http://fjjhomei9.fjjhome:8188"
MINIMAX_API_KEY = "sk-cp-lV21qvcemkF6vZI0d494QVJFj0oj0y7cvAjpjGACOs2H4gYBwtvAFqYjZNFyYIiv2W532ZcNwftGpfGWXzS4SkGyLpqi7vBUIrFteW72R1FGMGau8-oi_0A"

MINIMAX_SIZE = "16:9"
BEAR_COLORS = ["白熊", "棕熊", "灰熊", "黑熊", "粉熊", "藍熊", "紫熊", "綠熊", "紅熊", "橘熊"]


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


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


def check_comfyui():
    try:
        resp = requests.get(f"{COMFYUI_URL}/system_stats", timeout=5)
        return resp.status_code == 200
    except:
        return False


def get_today():
    return date.today().strftime("%Y-%m-%d")


def get_next_bear_names(n=8):
    naming = load_json(BEAR_NAMING)
    combinations = naming.get("combinations", {}).get("names", [])
    
    try:
        existing = load_json(BEARS_JSON)
        existing_names = {b["name"] for b in existing.get("bears", [])}
    except:
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
    """預覽風格輪流（不寫入 style-rotation.json）"""
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
    """從詞彙庫組合個性描述（描述詞 + 溫暖風格）"""
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


def make_bear_record(name, style, today, collection_no, daily_index):
    return {
        "name": name,
        "date": today,
        "checkIn": today.replace("-", "") + f"-{daily_index:02d}",
        "collectionNo": collection_no,
        "title": f"{name} ({style})",
        "series": get_random_series(),
        "birthday": today,
        "personality": get_random_personality(style),
        "quote": get_random_quote(),
        "img": f"bears/{today}/{name}.png",
    }


def generate_minimax_image(prompt, bear_name, style, color, output_path, idx):
    full_prompt = f"A cute {color.lower()} bear character named {bear_name}, {style} art style, adorable kawaii style, soft colors, high quality, horizontal composition"
    
    log(f"MiniMax #{idx+1}: {bear_name} ({style})")
    
    try:
        response = requests.post(
            "https://api.minimax.io/v1/images/generations",
            headers={
                "Authorization": f"Bearer {MINIMAX_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "MiniMax-Image-01",
                "prompt": full_prompt,
                "size": MINIMAX_SIZE,
                "n": 1,
            },
            timeout=120,
        )
        response.raise_for_status()
        image_url = response.json()["data"][0]["url"]
        urllib.request.urlretrieve(image_url, output_path)
        log(f"  已保存: {output_path.name}")
        return True
    except Exception as e:
        log(f"  MiniMax 生成失敗: {e}")
        return False


def generate_comfyui_image(prompt, bear_name, output_path, idx):
    log(f"ComfyUI #{idx+1}: {bear_name}")
    log(f"  (ComfyUI 需要預設 workflow，請手動生成)")
    return False


def add_bears_to_json(new_bears):
    """只更新 bears.json"""
    data = load_json(BEARS_JSON)
    data["bears"].extend(new_bears)
    data["last_updated"] = get_today()
    save_json(BEARS_JSON, data)
    log(f"已更新 bears.json")


def step_generate_images(bear_names, styles, today, comfyui_online):
    """步驟 4：生成圖片到暫存目錄（不複製到博物館）"""
    today_dir = TEMP_DIR / today
    today_dir.mkdir(parents=True, exist_ok=True)

    if comfyui_online:
        log("ComfyUI 在線: MiniMax 5張 + ComfyUI 3張")
    else:
        log("ComfyUI 離線: MiniMax 5張")

    generated = []
    for i in range(5):
        name, style = bear_names[i], styles[i]
        color = random.choice(BEAR_COLORS)
        output = today_dir / f"{name}.png"
        if generate_minimax_image(f"A {color} bear", name, style, color, output, i):
            generated.append({"name": name, "style": style, "temp_path": output})

    log(f"共生成 {len(generated)} 張圖片於 {today_dir}")
    return generated


def step_update_museum(generated, today):
    """步驟 5：複製圖片到博物館並更新 bears.json"""
    museum_dir = PROJECT_DIR / "bears" / today
    museum_dir.mkdir(parents=True, exist_ok=True)

    new_bears = []
    collection_no = get_max_collection_no() + 1

    for item in generated:
        dest = museum_dir / f"{item['name']}.png"
        shutil.copy2(item["temp_path"], dest)
        log(f"已複製: {item['name']}.png → {dest}")
        new_bears.append(make_bear_record(
            item["name"], item["style"], today, collection_no, len(new_bears) + 1
        ))
        collection_no += 1

    if new_bears:
        add_bears_to_json(new_bears)
        log(f"新增 {len(new_bears)} 隻熊熊")
    else:
        log("沒有新增熊熊")

    return new_bears


def main(mode=""):
    log("===== 熊熊每日配送計畫 =====")
    if mode:
        log(f"模式: {mode}")

    today = get_today()
    log(f"今日日期: {today}")

    log("\n--- 步驟 1: 檢查系統狀態 ---")
    comfyui_online = check_comfyui()
    log(f"ComfyUI: {'✓ 在線' if comfyui_online else '✗ 離線'}")

    log("\n--- 步驟 2: 取得熊熊名字和風格 ---")
    num_bears = 8 if comfyui_online else 5
    bear_names = get_next_bear_names(num_bears)

    if mode == "step2":
        styles, current_index = peek_styles(num_bears)
        log(f"風格輪流 index: {current_index}")
        log(f"熊熊 ({len(bear_names)}): {bear_names}")
        log(f"風格 ({len(styles)}): {styles}")
        for i, (name, style) in enumerate(zip(bear_names, styles), start=1):
            log(f"  #{i}: {name} / {style}")
        log("\n[step2] 預覽完成，未生圖、未更新詞彙輪流")
        return

    styles = get_next_styles(num_bears)
    log(f"熊熊: {bear_names}")
    log(f"風格: {styles}")

    log("\n--- 步驟 3: 準備目錄 ---")
    (TEMP_DIR / today).mkdir(parents=True, exist_ok=True)
    (PROJECT_DIR / "bears" / today).mkdir(parents=True, exist_ok=True)

    log("\n--- 步驟 4: 生成圖片 (16:9) ---")
    generated = step_generate_images(bear_names, styles, today, comfyui_online)

    if mode == "step4":
        log("\n[step4] 生圖完成，圖片保留於暫存目錄，未複製、未更新 bears.json")
        return

    log("\n--- 步驟 5: 更新熊熊博物館 ---")
    new_bears = step_update_museum(generated, today)

    if mode == "step5":
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
        help="step2=僅預覽名字風格, step4=僅生圖, step5=到更新博物館",
    )
    args = parser.parse_args()
    main(mode=args.mode)
