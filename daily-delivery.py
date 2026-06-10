#!/usr/bin/env python3
"""
熊熊每日配送計畫 - 自動化配送腳本
克勞熊使用說明：
1. 檢查系統狀態 (ComfyUI + MiniMax)
2. 讀取今日風格
3. 生成圖片 (MiniMax 5張 16:9，若 ComfyUI 在線則再生成 3張)
4. 更新 bears.json 和 index.html
5. Commit + 部署
"""

import os
import re
import json
import shutil
import requests
import urllib.request
import urllib.error
from datetime import datetime, date
from pathlib import Path
import random
import sys

# ===== 設定 =====
PROJECT_DIR = Path("/home/fjj04/my-bear-museum")
BEARS_JSON = PROJECT_DIR / "bears.json"
INDEX_HTML = PROJECT_DIR / "index.html"
TEMP_DIR = Path("/home/fjj04/bears")
VOCAB_DIR = PROJECT_DIR / "vocabulary"
BEAR_NAMING = VOCAB_DIR / "bear-naming.json"
STYLE_ROTATION = VOCAB_DIR / "style-rotation.json"
BEAR_QUOTES = VOCAB_DIR / "bear-quotes.json"
WORLD_BUILDING = VOCAB_DIR / "world-building.json"

# API 設定
COMFYUI_URL = "http://fjjhomei9.fjjhome:8188"
MINIMAX_API_KEY = "sk-cp-lV21qvcemkF6vZI0d494QVJFj0oj0y7cvAjpjGACOs2H4gYBwtvAFqYjZNFyYIiv2W532ZcNwftGpfGWXzS4SkGyLpqi7vBUIrFteW72R1FGMGau8-oi_0A"

# MiniMax 生圖設定
MINIMAX_MODEL = "MiniMax-Image-01"
MINIMAX_SIZE = "16:9"  # 16:9 橫向大圖

# 熊熊顏色
BEAR_COLORS = ["白熊", "棕熊", "灰熊", "黑熊", "粉熊", "藍熊", "紫熊", "綠熊", "紅熊", "橘熊"]


def log(msg):
    """輸出日誌"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def load_json(path):
    """載入 JSON 檔案"""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    """儲存 JSON 檔案"""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def check_comfyui():
    """檢查 ComfyUI 是否運行"""
    try:
        resp = requests.get(f"{COMFYUI_URL}/system_stats", timeout=5)
        return resp.status_code == 200
    except:
        return False


def check_minimax():
    """檢查 MiniMax API Key"""
    return bool(MINIMAX_API_KEY)


def get_today():
    """取得今日日期"""
    return date.today().strftime("%Y-%m-%d")


def get_next_bear_names(n=8):
    """取得下一組熊熊名字（避免重複）"""
    naming = load_json(BEAR_NAMING)
    combinations = naming.get("combinations", {}).get("names", [])
    
    # 載入現有 bears.json 避免重複
    try:
        existing = load_json(BEARS_JSON)
        existing_names = {b["name"] for b in existing.get("bears", [])}
    except:
        existing_names = set()
    
    # 過濾已使用的名字
    available = [name for name in combinations if name not in existing_names]
    
    # 如果不夠，隨機生成
    while len(available) < n:
        prefix = random.choice(naming["parts"]["prefix"]["words"])
        suffix = random.choice(naming["parts"]["suffix"]["words"])
        name = prefix + suffix
        if name not in existing_names and name not in available:
            available.append(name)
    
    return random.sample(available, min(n, len(available)))


def get_next_styles(n=8):
    """取得下一組風格（輪流）"""
    rotation = load_json(STYLE_ROTATION)
    styles = rotation.get("styles", [])
    current_index = rotation.get("current_index", 0)
    
    selected = []
    for i in range(n):
        selected.append(styles[(current_index + i) % len(styles)])
    
    # 更新 index
    rotation["current_index"] = (current_index + n) % len(styles)
    rotation["last_updated"] = get_today()
    save_json(STYLE_ROTATION, rotation)
    
    return selected


def get_random_quote():
    """取得隨機語錄"""
    quotes = load_json(BEAR_QUOTES)
    categories = list(quotes.get("categories", {}).keys())
    cat = random.choice(categories)
    cat_quotes = quotes["categories"][cat].get("quotes", [])
    return random.choice(cat_quotes) if cat_quotes else "每一天都是新的開始。"


def get_random_series():
    """取得隨機系列"""
    series_list = [
        "童話夢境系列", "星際冒險系列", "浪漫時光系列", 
        "勇者傳奇系列", "暖心守護系列", "糖果廚房系列",
        "海洋傳奇系列", "星光冒險系列"
    ]
    return random.choice(series_list)


def generate_minimax_image(prompt, bear_name, style, color, output_path, idx):
    """使用 MiniMax API 生成圖片（16:9）"""
    full_prompt = f"A cute {color.lower()} bear character named {bear_name}, {style} art style, adorable kawaii style, soft colors, high quality, horizontal composition"
    
    log(f"MiniMax #{idx+1}: {bear_name} ({style})")
    
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=MINIMAX_API_KEY,
            base_url="https://api.minimax.io/v1"
        )
        
        response = client.images.generate(
            model=MINIMAX_MODEL,
            prompt=full_prompt,
            size=MINIMAX_SIZE,
            n=1
        )
        
        image_url = response.data[0].url
        
        # 下載圖片
        urllib.request.urlretrieve(image_url, output_path)
        log(f"  已保存: {output_path.name}")
        return True
        
    except Exception as e:
        log(f"  MiniMax 生成失敗: {e}")
        return False


def generate_comfyui_image(prompt, bear_name, output_path, idx):
    """使用 ComfyUI 生成圖片"""
    log(f"ComfyUI #{idx+1}: {bear_name}")
    
    workflow = {
        "3": {
            "inputs": {
                "text": f"{prompt}, bear character, high quality, 16:9 aspect ratio",
                "CLIP": ["4", 0]
            },
            "class_type": "CLIPTextEncode"
        },
        "4": {
            "inputs": {
                "models": []
            },
            "class_type": "CheckpointLoaderSimple"
        },
        "5": {
            "inputs": {
                "width": 1600,
                "height": 912,
                "batch_size": 1
            },
            "class_type": "EmptyLatentImage"
        },
        "6": {
            "inputs": {
                "samples": ["5", 0],
                "model": ["4", 0],
                "positive": ["3", 0],
                "negative": ["3", 0],
                "seed": random.randint(1, 999999999)
            },
            "class_type": "KSampler"
        },
        "7": {
            "inputs": {
                "samples": ["6", 0]
            },
            "class_type": "VAEDecode"
        },
        "8": {
            "inputs": {
                "filename_prefix": "bear",
                "images": ["7", 0]
            },
            "class_type": "SaveImage"
        }
    }
    
    try:
        resp = requests.post(
            f"{COMFYUI_URL}/prompt",
            json={"prompt": workflow},
            timeout=60
        )
        
        if resp.status_code == 200:
            log(f"  ComfyUI 任務已提交: {output_path.name}")
            return True
        else:
            log(f"  ComfyUI 提交失敗: {resp.status_code}")
            return False
            
    except Exception as e:
        log(f"  ComfyUI 連線失敗: {e}")
        return False


def update_index_html(new_bears):
    """更新 index.html 中的 bears 陣列"""
    log("更新 index.html...")
    
    # 讀取現有的 bears 陣列
    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 找到 bears 陣列的開始和結束位置
    start_pattern = r'const bears = \['
    end_pattern = r'\];'
    
    start_match = re.search(start_pattern, content)
    if not start_match:
        log("錯誤: 找不到 bears 陣列")
        return False
    
    start_pos = start_match.start()
    
    # 找到匹配的結束位置
    search_content = content[start_pos + len(start_match.group()):]
    depth = 1
    end_pos = 0
    
    for i, char in enumerate(search_content):
        if char == '[':
            depth += 1
        elif char == ']':
            depth -= 1
            if depth == 0:
                end_pos = i
                break
    
    if end_pos == 0:
        log("錯誤: 找不到 bears 陣列結尾")
        return False
    
    end_pos = start_pos + len(start_match.group()) + end_pos + 1
    
    # 讀取現有的 bears.json
    existing = load_json(BEARS_JSON)
    existing_bears = existing.get("bears", [])
    
    # 合併新熊熊
    all_bears = existing_bears + new_bears
    
    # 產生新的 bears 陣列
    js_lines = ['const bears = [']
    for i, bear in enumerate(all_bears):
        js_lines.append('            {')
        for key, value in bear.items():
            if isinstance(value, str):
                escaped = value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
                js_lines.append(f'                {key}: "{escaped}",')
            elif isinstance(value, int):
                js_lines.append(f'                {key}: {value},')
        js_lines.append('            }' + (',' if i < len(all_bears) - 1 else ''))
    js_lines.append('        ];')
    
    new_bears_array = '\n'.join(js_lines)
    
    # 替換 bears 陣列
    new_content = content[:start_pos] + new_bears_array + content[end_pos:]
    
    # 保存
    with open(INDEX_HTML, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    log(f"index.html 已更新，共 {len(all_bears)} 隻熊熊")


def add_bears_to_json(new_bears):
    """新增熊熊到 bears.json"""
    data = load_json(BEARS_JSON)
    data["bears"].extend(new_bears)
    data["last_updated"] = get_today()
    save_json(BEARS_JSON, data)
    log(f"已更新 bears.json")


def main():
    log("===== 熊熊每日配送計畫 =====")
    
    today = get_today()
    log(f"今日日期: {today}")
    
    # 1. 檢查系統狀態
    log("\n--- 步驟 1: 檢查系統狀態 ---")
    comfyui_online = check_comfyui()
    minimax_ready = check_minimax()
    
    log(f"ComfyUI: {'✓ 在線' if comfyui_online else '✗ 離線'}")
    log(f"MiniMax: {'✓ 就緒' if minimax_ready else '✗ 未設定 API Key'}")
    
    if not minimax_ready:
        log("錯誤: MiniMax API Key 未設定")
        sys.exit(1)
    
    # 2. 取得熊熊名字和風格
    log("\n--- 步驟 2: 取得熊熊名字和風格 ---")
    
    if comfyui_online:
        num_bears = 8  # ComfyUI 在線：MiniMax 5 + ComfyUI 3
    else:
        num_bears = 5  # ComfyUI 離線：MiniMax 5
    
    bear_names = get_next_bear_names(num_bears)
    styles = get_next_styles(num_bears)
    
    log(f"熊熊名字: {bear_names}")
    log(f"風格: {styles}")
    
    # 3. 創建今日目錄
    log("\n--- 步驟 3: 準備圖片目錄 ---")
    today_dir = TEMP_DIR / today
    today_dir.mkdir(parents=True, exist_ok=True)
    log(f"圖片目錄: {today_dir}")
    
    museum_dir = PROJECT_DIR / "bears" / today
    museum_dir.mkdir(parents=True, exist_ok=True)
    log(f"博物館目錄: {museum_dir}")
    
    # 4. 生成圖片
    log("\n--- 步驟 4: 生成圖片 (16:9) ---")
    
    new_bears = []
    
    if comfyui_online:
        # ComfyUI 在線：MiniMax 5張 + ComfyUI 3張
        log("ComfyUI 在線，使用混合模式...")
        
        # MiniMax 生成 5 張 (idx 0-4)
        for i in range(5):
            name = bear_names[i]
            style = styles[i]
            color = random.choice(BEAR_COLORS)
            output = today_dir / f"{name}.png"
            
            prompt = f"A {color} bear in {style} style, {name}"
            if generate_minimax_image(prompt, name, style, color, output, i):
                museum_output = museum_dir / f"{name}.png"
                shutil.copy(output, museum_output)
                
                new_bears.append({
                    "name": name,
                    "date": today,
                    "checkIn": today.replace("-", "") + f"-{i+1:02d}",
                    "collectionNo": 47 + i,
                    "title": f"{name} ({style})",
                    "series": get_random_series(),
                    "birthday": today,
                    "personality": f"我是{name}，今天帶來{style}的魔力！",
                    "quote": get_random_quote(),
                    "img": f"bears/{today}/{name}.png"
                })
        
        # ComfyUI 生成 3 張 (idx 5-7)
        for i in range(3):
            idx = i + 5
            name = bear_names[idx]
            style = styles[idx]
            output = today_dir / f"{name}.png"
            
            prompt = f"A bear in {style} style, {name}"
            if generate_comfyui_image(prompt, name, output, idx):
                museum_output = museum_dir / f"{name}.png"
                shutil.copy(output, museum_output)
                
                new_bears.append({
                    "name": name,
                    "date": today,
                    "checkIn": today.replace("-", "") + f"-{idx+1:02d}",
                    "collectionNo": 47 + idx,
                    "title": f"{name} ({style})",
                    "series": get_random_series(),
                    "birthday": today,
                    "personality": f"我是{name}，今天帶來{style}的魔力！",
                    "quote": get_random_quote(),
                    "img": f"bears/{today}/{name}.png"
                })
    
    else:
        # ComfyUI 離線：MiniMax 生成 5 張
        log("ComfyUI 離線，MiniMax 生成 5 張...")
        
        for i in range(5):
            name = bear_names[i]
            style = styles[i]
            color = random.choice(BEAR_COLORS)
            output = today_dir / f"{name}.png"
            
            prompt = f"A {color} bear in {style} style, {name}"
            if generate_minimax_image(prompt, name, style, color, output, i):
                museum_output = museum_dir / f"{name}.png"
                shutil.copy(output, museum_output)
                
                new_bears.append({
                    "name": name,
                    "date": today,
                    "checkIn": today.replace("-", "") + f"-{i+1:02d}",
                    "collectionNo": 47 + i,
                    "title": f"{name} ({style})",
                    "series": get_random_series(),
                    "birthday": today,
                    "personality": f"我是{name}，今天帶來{style}的魔力！",
                    "quote": get_random_quote(),
                    "img": f"bears/{today}/{name}.png"
                })
    
    # 5. 更新 bears.json 和 index.html
    log("\n--- 步驟 5: 更新 bears.json 和 index.html ---")
    if new_bears:
        add_bears_to_json(new_bears)
        update_index_html(new_bears)
        log(f"新增 {len(new_bears)} 隻熊熊")
    else:
        log("沒有新增熊熊")
    
    # 6. Git 操作
    log("\n--- 步驟 6: Git Commit ---")
    os.chdir(PROJECT_DIR)
    
    os.system("git add bears.json index.html bears/ vocabulary/style-rotation.json daily-delivery.py")
    os.system(f'git commit -m "新增 {today} 熊熊圖片"')
    os.system("git push")
    
    log("\n===== 完成 =====")
    log(f"到 https://kumaweb.pages.dev 觀看結果")


if __name__ == "__main__":
    main()
