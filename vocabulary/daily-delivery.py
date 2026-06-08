#!/usr/bin/env python3
"""
熊熊博物館 - 每日配送自動化腳本
執行時間：每天 04:10（由 Cronjob 觸發）

功能：
1. 檢查新圖片（bears/YYYY-MM-DD/）
2. 驗證圖片命名（{顏色}_{風格}_{日期}_{序號}.png）
3. 複製到 my-bear-museum/bears/
4. 更新 index.html（新增熊熊數據）
5. 更新版本號
6. Git commit + push
7. 部署到 Cloudflare Pages
"""

import os
import sys
import json
import subprocess
import re
from datetime import datetime
from pathlib import Path

# ============== 設定 ==============
BEARS_DIR = Path("/home/fjj04/bears")
MUSEUM_DIR = Path("/home/fjj04/my-bear-museum")
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

# ============== 步驟 4：更新 index.html ==============

def load_naming_dict():
    """載入熊熊命名字典"""
    naming_file = MUSEUM_DIR / "vocabulary" / "bear-naming.json"
    with open(naming_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['combinations']['names']

def load_quotes_dict():
    """載入熊熊語錄"""
    quotes_file = MUSEUM_DIR / "vocabulary" / "bear-quotes.json"
    with open(quotes_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("quotes", [])

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

def update_index_html(images, date_str, collection_start):
    """更新 index.html 的 bears 數組（使用詞彙庫命名）"""
    import random
    
    # 載入詞彙庫
    all_names = load_naming_dict()
    all_quotes = load_quotes_dict()
    
    # 收集已使用的名稱和語錄
    with open(INDEX_HTML, 'r', encoding='utf-8') as f:
        content = f.read()
    used_names = set(re.findall(r'name:\s*"([^"]+)"', content))
    used_quotes = set(re.findall(r'quote:\s*"([^"]+)"', content))
    
    log(f"詞彙庫：{len(all_names)} 個名字，{len(all_quotes)} 條語錄")
    log(f"已使用：{len(used_names)} 個名字，{len(used_quotes)} 條語錄")
    
    # 產生熊熊 JSON
    bears = []
    for i, img in enumerate(sorted(images), start=1):
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
            "img": f"bears/{date_str}/{img.name}"
        }
        bears.append(bear_json)
        log(f"新增熊熊: {bear_name} (No.{collection_start + i})")
    
    return bears

# ============== ComfyUI 魔法畫筆 ==============

COMFYUI_URL = "http://fjjhomei9.fjjhome:8188"

def generate_with_comfyui(prompt, width=1600, height=912, output_prefix="Bear", negative_prompt="blurry, low quality, watermark, dark"):
    """
    使用 ComfyUI 生成圖片（Flux.2-Klein workflow）
    
    參數：
    - prompt: 英文 prompt（熊熊描述）
    - width, height: 圖片尺寸
    - output_prefix: 輸出檔案前綴（日期資料夾）
    - negative_prompt: 負向 prompt
    
    返回：
    - 輸出檔案名稱列表
    """
    import requests
    import time
    import random
    
    log(f"提交 ComfyUI prompt: {prompt[:50]}...")
    
    # 組合完整 workflow（使用雙反斜線）
    workflow = {
        "84": {"inputs": {"samples": ["98", 0], "vae": ["92", 0]}, "class_type": "VAEDecode"},
        "85": {"inputs": {"width": width, "height": height, "batch_size": 1}, "class_type": "EmptyFlux2LatentImage"},
        "86": {"inputs": {"text": negative_prompt, "clip": ["91", 0]}, "class_type": "CLIPTextEncode"},
        "90": {"inputs": {"unet_name": "Flux\\Flux.2-Klein\\flux-2-klein-9b-fp8.safetensors", "weight_dtype": "default"}, "class_type": "UNETLoader"},
        "91": {"inputs": {"clip_name": "qwen_3_8b_fp8mixed.safetensors", "type": "flux2", "device": "default"}, "class_type": "CLIPLoader"},
        "92": {"inputs": {"vae_name": "Flux\\flux2-vae.safetensors"}, "class_type": "VAELoader"},
        "93": {"inputs": {"text": prompt, "clip": ["91", 0]}, "class_type": "CLIPTextEncode"},
        "98": {"inputs": {"seed": random.randint(1, 9999999999), "steps": 20, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0, "model": ["90", 0], "positive": ["93", 0], "negative": ["86", 0], "latent_image": ["85", 0]}, "class_type": "KSampler"},
        "105": {"inputs": {"filename_prefix": f"{output_prefix}/Flux2-Klein", "images": ["84", 0]}, "class_type": "SaveImage"}
    }
    
    # 提交 prompt
    response = requests.post(f"{COMFYUI_URL}/api/prompt", json={"prompt": workflow})
    if response.status_code != 200:
        raise Exception(f"ComfyUI API 錯誤: {response.text}")
    
    result = response.json()
    prompt_id = result.get("prompt_id")
    queue_number = result.get("number", "?")
    log(f"已提交 prompt，排隊號碼: {queue_number}")
    
    # 等待完成（最多 2 分鐘）
    max_wait = 120
    for i in range(max_wait):
        time.sleep(1)
        try:
            history = requests.get(f"{COMFYUI_URL}/api/history/{prompt_id}").json()
            if prompt_id in history:
                status = history[prompt_id].get("status", {})
                if status.get("status_str") == "success":
                    outputs = history[prompt_id].get("outputs", {})
                    images = []
                    for node_id, node_output in outputs.items():
                        if "images" in node_output:
                            for img in node_output["images"]:
                                images.append(img)
                    log(f"✅ ComfyUI 生成完成: {len(images)} 張圖片")
                    return images
        except:
            pass
        
        if (i + 1) % 10 == 0:
            log(f"等待中... ({i+1}/{max_wait} 秒)")
    
    raise Exception("ComfyUI 生成超時")


def download_comfyui_image(filename, subfolder, dest_path):
    """下載 ComfyUI 輸出的圖片"""
    import requests
    url = f"{COMFYUI_URL}/api/view?filename={filename}&subfolder={subfolder}&type=output"
    response = requests.get(url)
    if response.status_code == 200:
        with open(dest_path, 'wb') as f:
            f.write(response.content)
        return True
    return False

# ============== 主流程 ==============

def main():
    log("=" * 50)
    log("熊熊博物館每日配送開始")
    log("=" * 50)
    
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
    
    # 更新版本號
    log(f"\n🏷️  步驟 4：更新版本號")
    new_version = get_next_version()
    update_version(new_version)
    
    # Git commit
    log(f"\n📦 步驟 5：Git commit")
    run_cmd(f"cd {MUSEUM_DIR} && git add bears/{TODAY}/ && git add index.html")
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

if __name__ == "__main__":
    main()