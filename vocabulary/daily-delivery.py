#!/usr/bin/env python3
"""
熊熊博物館 - 每日配送自動化腳本
執行時間：每天 04:10（由 Cronjob 觸發）

功能：
1. 檢查新圖片（bears/YYYY-MM-DD/）
2. 自動將 JPG 圖片轉換為 PNG 格式
3. 驗證圖片命名（{顏色}_{風格}_{日期}_{序號}.png）
4. 複製到 my-bear-museum/bears/
5. 更新 index.html（新增熊熊數據，使用詞彙庫命名）
6. 更新版本號
7. Git commit + push
8. 部署到 Cloudflare Pages
"""

import os
import sys
import json
import subprocess
import re
from datetime import datetime
from pathlib import Path

# ============== 設定 ==============
MUSEUM_DIR = Path("/home/fjj04/my-bear-museum")
BEARS_DIR = MUSEUM_DIR / "bears"  # 熊熊圖片目錄
INDEX_HTML = MUSEUM_DIR / "index.html"
TODAY = datetime.now().strftime("%Y-%m-%d")
TODAY_SHORT = datetime.now().strftime("%Y%m%d")

# ============== 工具函數 ==============

def log(msg):
    """輸出日誌"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def run_cmd(cmd, check=True):
    """執行 shell 命令"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise Exception(f"命令執行失敗: {cmd}\n{result.stderr}")
    return result.stdout.strip()

def get_max_collection_no():
    """取得目前最大的 collectionNo"""
    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        content = f.read()
    matches = re.findall(r'collectionNo:\s*(\d+)', content)
    if matches:
        return max(int(m) for m in matches)
    return 0

def update_version(new_version):
    """更新版本號（三處）"""
    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. title 標籤
    content = re.sub(
        r'<title>.*?</title>',
        f'<title>熊熊博物館 v{new_version}</title>',
        content
    )
    
    # 2. footer 版本文字
    content = re.sub(
        r'v\d+\.\d+</span>\s*–\s*熊熊博物館更新',
        f'v{new_version}</span> – 熊熊博物館更新',
        content
    )
    
    # 3. version history 註解
    content = re.sub(
        r'<!-- v\d+\.\d+',
        f'<!-- v{new_version}',
        content
    )
    
    with open(INDEX_HTML, 'w', encoding='utf-8') as f:
        f.write(content)
    
    log(f"版本更新至 v{new_version}")

def get_next_version():
    """取得下一個版本號"""
    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        content = f.read()
    match = re.search(r'v(\d+)\.(\d+)', content)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2)) + 1
        return f"{major}.{minor}"
    return "6.1"

# ============== 步驟 0：JPG 轉 PNG ==============

def convert_jpg_to_png(date_str):
    """將 JPG 圖片轉換為 PNG 格式"""
    img_dir = BEARS_DIR / date_str
    
    if not img_dir.exists():
        return 0
    
    jpg_files = list(img_dir.glob("*.jpg")) + list(img_dir.glob("*.jpeg"))
    
    if not jpg_files:
        return 0
    
    log(f"找到 {len(jpg_files)} 張 JPG 圖片需要轉換")
    
    #嘗試使用 PIL 轉換
    try:
        from PIL import Image
        for jpg_file in jpg_files:
            png_file = jpg_file.with_suffix('.png')
            if png_file.exists():
                log(f"PNG 已存在，跳過: {jpg_file.name}")
                continue
            img = Image.open(jpg_file)
            img.save(png_file, 'PNG')
            log(f"已轉換: {jpg_file.name} -> {png_file.name}")
            jpg_file.unlink()  # 刪除原始 JPG
        return len(jpg_files)
    except ImportError:
        log("⚠️  需要 Pillow 庫來轉換圖片格式")
        log(" 執行: uv pip install pillow")
        return 0

# ============== 步驟 1-2：檢查並驗證圖片 ==============

def check_and_validate_images(date_str):
    """檢查並驗證圖片"""
    img_dir = BEARS_DIR / date_str
    
    if not img_dir.exists():
        log(f"❌ 找不到目錄: {img_dir}")
        return []
    
    images = sorted(img_dir.glob("*.png"))
    log(f"找到 {len(images)} 張圖片")
    
    # 驗證命名格式
    valid_images = []
    for img in images:
        name = img.name
        # 格式：{顏色}_{風格}_{日期}_{序號}.png
        if re.match(r'^(棕熊|灰熊|白熊|粉熊|藍熊|黑熊|橙熊|綠熊|金熊|銀熊)_(.+)_\d{8}_\d{2}\.png$', name):
            valid_images.append(img)
        else:
            log(f"⚠️  命名格式不符: {name}")
    
    return valid_images

# ============== 步驟 3：複製到 my-bear-museum ==============

def copy_images_to_museum(images, date_str):
    """複製圖片到博物館目錄"""
    dest_dir = MUSEUM_DIR / "bears" / date_str
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    for img in images:
        dest = dest_dir / img.name
        if dest.exists():
            log(f"已存在，跳過: {img.name}")
        else:
            import shutil
            shutil.copy2(img, dest)
            log(f"已複製: {img.name}")
    
    # 驗證
    dest_images = list(dest_dir.glob("*.png"))
    log(f"博物館目錄共 {len(dest_images)} 張圖片")

# ============== 風格輪流函數 ==============

def load_style_rotation():
    """載入風格輪流設定"""
    rotation_file = MUSEUM_DIR / "vocabulary" / "style-rotation.json"
    with open(rotation_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['current_index'], data['styles']

def get_styles_for_today(count=6):
    """取得今天要使用的風格（根據輪流順序）"""
    current_index, styles = load_style_rotation()
    total_styles = len(styles)
    
    # 取得接下來 count 個風格（會循環）
    selected = []
    idx = current_index
    for _ in range(count):
        selected.append(styles[idx % total_styles])
        idx += 1
    
    return selected, current_index

def advance_style_index(count=6):
    """更新風格輪流的 current_index"""
    rotation_file = MUSEUM_DIR / "vocabulary" / "style-rotation.json"
    with open(rotation_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    total_styles = len(data['styles'])
    new_index = (data['current_index'] + count) % total_styles
    data['current_index'] = new_index
    data['last_updated'] = datetime.now().strftime("%Y-%m-%d")
    
    with open(rotation_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    log(f"風格輪流：current_index 更新為 {new_index}")

# ============== 詞彙庫載入函數 ==============

def load_naming_dict():
    """載入熊熊命名字典"""
    naming_file = MUSEUM_DIR / "vocabulary" / "bear-naming.json"
    with open(naming_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['combinations']['names']

def load_quotes_dict():
    """載入熊熊語錄（支援分類結構）"""
    quotes_file = MUSEUM_DIR / "vocabulary" / "bear-quotes.json"
    with open(quotes_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 支援兩種格式：純陣列 或 分類結構
    if isinstance(data, list):
        return data
    
    # 分類結構：提取所有 quotes
    all_quotes = []
    categories = data.get("categories", {})
    for category_name, category_data in categories.items():
        quotes = category_data.get("quotes", [])
        all_quotes.extend(quotes)
    return all_quotes

def generate_bear_name(used_names):
    """從詞彙庫取得一個還沒用過的熊熊名稱"""
    import random
    all_names = load_naming_dict()
    available = [n for n in all_names if n not in used_names]
    if not available:
        available = all_names  # 如果都用過了，就隨機選
    return random.choice(available)

def generate_bear_quote(used_quotes):
    """從詞彙庫取得一段還沒用過的語錄"""
    import random
    all_quotes = load_quotes_dict()
    available = [q for q in all_quotes if q not in used_quotes]
    if not available:
        available = all_quotes
    return random.choice(available)

# ============== 步驟 4：更新 index.html ==============

def update_index_html(images, date_str, collection_start):
    """更新 index.html 的 bears 數組（使用詞彙庫命名）"""
    import random
    
    # 載入詞彙庫
    all_names = load_naming_dict()
    all_quotes = load_quotes_dict()
    
    # 收集已使用的名稱、語錄、圖片路徑
    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        content = f.read()
    used_names = set(re.findall(r'name:\s*"([^"]+)"', content))
    used_quotes = set(re.findall(r'quote:\s*"([^"]+)"', content))
    
    # 收集已存在的圖片路徑（避免重複新增）
    existing_imgs = set(re.findall(r'img:\s*"([^"]+)"', content))
    
    log(f"詞彙庫：{len(all_names)} 個名字，{len(all_quotes)} 條語錄")
    log(f"已使用：{len(used_names)} 個名字，{len(used_quotes)} 條語錄")
    log(f"已存在：{len(existing_imgs)} 張圖片")
    
    # 產生熊熊 JSON（只處理新圖片）
    bears = []
    for i, img in enumerate(sorted(images), start=1):
        img_path = f"bears/{date_str}/{img.name}"
        
        # 跳過已存在的圖片
        if img_path in existing_imgs:
            log(f"圖片已存在，跳過: {img.name}")
            continue
        
        name = img.stem  # 例如：白熊_水彩_20260608_01
        
        # 解析命名
        parts = name.split('_')
        color = parts[0] if len(parts) > 0 else "棕熊"
        style = parts[1] if len(parts) > 1 else "3D"
        
        # 從詞彙庫取名字（避開已使用的）
        bear_name = generate_bear_name(used_names)
        used_names.add(bear_name)
        
        # 從詞彙庫取語錄（避開已使用的）
        quote = generate_bear_quote(used_quotes)
        used_quotes.add(quote)
        
        bear_json = {
            "name": bear_name,
            "date": date_str,
            "checkIn": f"{TODAY_SHORT}-{i:02d}",
            "collectionNo": collection_start + i,
            "category": style,
            "desc": quote,
            "img": img_path
        }
        bears.append(bear_json)
        log(f"新增熊熊: {bear_name} (No.{collection_start + i})")
    
    if not bears:
        return bears
    
    # 將新熊熊寫入 index.html
    # 找到 bears 陣列的結尾（倒数第二个 ]之前）
    lines = content.split('\n')
    bears_end_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == '];':
            bears_end_idx = i
            break
    
    if bears_end_idx is None:
        raise Exception("找不到 bears 陣列結尾")
    
    # 產生新的熊熊 JSON 文字
    new_bears_text = []
    for bear in bears:
        new_bears_text.append('            {')
        new_bears_text.append(f'                name: "{bear["name"]}",')
        new_bears_text.append(f'                date: "{bear["date"]}",')
        new_bears_text.append(f'                checkIn: "{bear["checkIn"]}",')
        new_bears_text.append(f'                collectionNo: {bear["collectionNo"]},')
        new_bears_text.append(f'                category: "{bear["category"]}",')
        new_bears_text.append(f'                desc: "{bear["desc"]}",')
        new_bears_text.append(f'                img: "{bear["img"]}"')
        new_bears_text.append('            },' + ('' if bear == bears[-1] else ''))
    
    # 在 bears_end_idx 之前插入新熊熊
    new_lines = lines[:bears_end_idx] + new_bears_text + [''] + lines[bears_end_idx:]
    
    with open(INDEX_HTML, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))
    
    log(f"已寫入 {len(bears)} 隻熊熊到 index.html")
    
    return bears

# ============== 主流程 ==============

def main():
    log("=" * 50)
    log("熊熊博物館每日配送開始")
    log("=" * 50)
    
    # 取得今天的風格（根據輪流順序）
    styles_today, current_idx = get_styles_for_today(6)
    log(f"\n🎨 今天的風格（輪流 index: {current_idx}）:")
    log(f"   {', '.join(styles_today)}")
    
    # JPG 轉 PNG
    log(f"\n📁 步驟 0：JPG轉 PNG - {TODAY}")
    converted = convert_jpg_to_png(TODAY)
    if converted > 0:
        log(f"已轉換 {converted} 張 JPG 為 PNG")
    
    # 檢查新圖片
    log(f"\n📁 步驟 1：檢查圖片 - {TODAY}")
    images = check_and_validate_images(TODAY)
    
    if not images:
        log("沒有新圖片，配送結束")
        return
    
    # 複製到博物館
    log(f"\n📋 步驟 2：複製圖片到博物館")
    copy_images_to_museum(images, TODAY)
    
    # 取得目前最大 collectionNo
    max_no = get_max_collection_no()
    log(f"目前最大 collectionNo: {max_no}")
    
    # 更新 index.html
    log(f"\n📝 步驟 3：更新 index.html")
    new_bears = update_index_html(images, TODAY, max_no)
    log(f"新增 {len(new_bears)} 隻熊熊")
    
    # 如果有新熊熊才繼續
    if not new_bears:
        log("\n沒有新熊熊，配送結束")
        return
    
    # 更新版本號
    log(f"\n🏷️  步驟 4：更新版本號")
    new_version = get_next_version()
    update_version(new_version)
    
    # Git commit
    log(f"\n📦 步驟 5：Git commit")
    run_cmd(f"cd {MUSEUM_DIR} && git add bears/{TODAY}/")
    run_cmd(f"cd {MUSEUM_DIR} && git add index.html")
    run_cmd(f"cd {MUSEUM_DIR} && git add vocabulary/daily-delivery.py")
    run_cmd(f"cd {MUSEUM_DIR} && git commit -m 'v{new_version} - 每日配送 {TODAY}'")
    run_cmd(f"cd {MUSEUM_DIR} && git push")
    log("Git push 完成")
    
    # 部署
    log(f"\n🚀 步驟 6：部署到 Cloudflare Pages")
    run_cmd(f"cd {MUSEUM_DIR} && npx wrangler pages deploy . --project-name kumaweb --branch main --no-install-skills --commit-dirty=true")
    
    log("\n" + "=" * 50)
    log("✅ 配送完成！")
    log(f"🌐 https://kumaweb.pages.dev")
    log("=" * 50)
    
    # 更新風格輪流 index
    advance_style_index(6)

if __name__ == "__main__":
    main()