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

import os
import json
import shutil
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

# API 設定
COMFYUI_URL = "http://fjjhomei9.fjjhome:8188"
MINIMAX_API_KEY = "sk-cp-lV21qvcemkF6vZI0d494QVJFj0oj0y7cvAjpjGACOs2H4gYBwtvAFqYjZNFyYIiv2W532ZcNwftGpfGWXzS4SkGyLpqi7vBUIrFteW72R1FGMGau8-oi_0A"

MINIMAX_SIZE = "16:9"
BEAR_COLORS = ["白熊", "棕熊", "灰熊", "黑熊", "粉熊", "藍熊", "紫熊", "綠熊", "紅熊", "橘熊"]


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


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


def get_next_styles(n=8):
    rotation = load_json(STYLE_ROTATION)
    styles = rotation.get("styles", [])
    current_index = rotation.get("current_index", 0)
    
    selected = []
    for i in range(n):
        selected.append(styles[(current_index + i) % len(styles)])
    
    rotation["current_index"] = (current_index + n) % len(styles)
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
    series_list = [
        "童話夢境系列", "星際冒險系列", "浪漫時光系列", 
        "勇者傳奇系列", "暖心守護系列", "糖果廚房系列",
        "海洋傳奇系列", "星光冒險系列"
    ]
    return random.choice(series_list)


def generate_minimax_image(prompt, bear_name, style, color, output_path, idx):
    full_prompt = f"A cute {color.lower()} bear character named {bear_name}, {style} art style, adorable kawaii style, soft colors, high quality, horizontal composition"
    
    log(f"MiniMax #{idx+1}: {bear_name} ({style})")
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=MINIMAX_API_KEY, base_url="https://api.minimax.io/v1")
        
        response = client.images.generate(
            model="MiniMax-Image-01",
            prompt=full_prompt,
            size=MINIMAX_SIZE,
            n=1
        )
        
        image_url = response.data[0].url
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


def main():
    log("===== 熊熊每日配送計畫 =====")
    
    today = get_today()
    log(f"今日日期: {today}")
    
    log("\n--- 步驟 1: 檢查系統狀態 ---")
    comfyui_online = check_comfyui()
    log(f"ComfyUI: {'✓ 在線' if comfyui_online else '✗ 離線'}")
    
    log("\n--- 步驟 2: 取得熊熊名字和風格 ---")
    num_bears = 8 if comfyui_online else 5
    bear_names = get_next_bear_names(num_bears)
    styles = get_next_styles(num_bears)
    log(f"熊熊: {bear_names}")
    log(f"風格: {styles}")
    
    log("\n--- 步驟 3: 準備目錄 ---")
    today_dir = TEMP_DIR / today
    today_dir.mkdir(parents=True, exist_ok=True)
    museum_dir = PROJECT_DIR / "bears" / today
    museum_dir.mkdir(parents=True, exist_ok=True)
    
    log("\n--- 步驟 4: 生成圖片 (16:9) ---")
    new_bears = []
    
    if comfyui_online:
        log("ComfyUI 在線: MiniMax 5張 + ComfyUI 3張")
        for i in range(5):
            name, style = bear_names[i], styles[i]
            color = random.choice(BEAR_COLORS)
            output = today_dir / f"{name}.png"
            if generate_minimax_image(f"A {color} bear", name, style, color, output, i):
                shutil.copy(output, museum_dir / f"{name}.png")
                new_bears.append({
                    "name": name, "date": today,
                    "checkIn": today.replace("-", "") + f"-{i+1:02d}",
                    "collectionNo": 47 + i,
                    "title": f"{name} ({style})",
                    "series": get_random_series(), "birthday": today,
                    "personality": f"我是{name}，今天帶來{style}的魔力！",
                    "quote": get_random_quote(),
                    "img": f"bears/{today}/{name}.png"
                })
    else:
        log("ComfyUI 離線: MiniMax 5張")
        for i in range(5):
            name, style = bear_names[i], styles[i]
            color = random.choice(BEAR_COLORS)
            output = today_dir / f"{name}.png"
            if generate_minimax_image(f"A {color} bear", name, style, color, output, i):
                shutil.copy(output, museum_dir / f"{name}.png")
                new_bears.append({
                    "name": name, "date": today,
                    "checkIn": today.replace("-", "") + f"-{i+1:02d}",
                    "collectionNo": 47 + i,
                    "title": f"{name} ({style})",
                    "series": get_random_series(), "birthday": today,
                    "personality": f"我是{name}，今天帶來{style}的魔力！",
                    "quote": get_random_quote(),
                    "img": f"bears/{today}/{name}.png"
                })
    
    log("\n--- 步驟 5: 更新 bears.json ---")
    if new_bears:
        add_bears_to_json(new_bears)
        log(f"新增 {len(new_bears)} 隻熊熊")
    else:
        log("沒有新增熊熊")
    
    log("\n--- 步驟 6: Git Commit ---")
    os.chdir(PROJECT_DIR)
    os.system("git add bears.json bears/ vocabulary/style-rotation.json daily-delivery.py")
    os.system(f'git commit -m "新增 {today} 熊熊"')
    os.system("git push")
    
    log("\n===== 完成 =====")
    log(f"到 https://kumaweb.pages.dev 觀看結果")


if __name__ == "__main__":
    main()
