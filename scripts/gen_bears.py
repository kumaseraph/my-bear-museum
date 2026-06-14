#!/usr/bin/env python3
"""
熊熊圖片生成腳本
生成 5 種風格的熊熊圖片，並自動生成縮略圖
"""
import requests
import json
import time
import os
import sys
from datetime import datetime, timedelta
from PIL import Image

# ComfyUI API
API = "http://fjjhomei9.fjjhome:8188"

# 熊熊列表（可自訂）
bears = [
    {"color":"白","style":"水彩","name":"雲朵綿綿","mood":"今天發現了一朵好香的花，想分享給你！","prompt":"A cute white bear cub sitting on a fluffy cloud, watercolor illustration style, soft pastel colors, gentle blue sky background, adorable round face with rosy cheeks, holding a small wildflower, warm and dreamy atmosphere, children's book illustration"},
    {"color":"棕","style":"3D","name":"蜜糖爪爪","mood":"這罐蜂蜜是特別留給好朋友的喔！","prompt":"A adorable brown bear cub with round belly, 3D rendered illustration, cute cartoon style, holding a golden honeycomb, honey dripping from it, cozy forest clearing background, warm sunlight filtering through trees, Pixar-style rendering, soft lighting"},
    {"color":"粉","style":"油畫","name":"玫瑰糖糖","mood":"今天的夕陽好美，想和你一起看～","prompt":"A charming pink bear cub with flower crown, oil painting style, impressionist brushstrokes, standing in a field of blooming roses, sunset golden hour lighting, soft pink and warm orange palette, dreamy romantic atmosphere, visible brush texture"},
    {"color":"藍","style":"奇幻","name":"星海泡泡","mood":"我在星星堆裡找到了一顆最亮的寶石！","prompt":"A magical blue bear cub floating in a starry night sky, fantasy illustration style, glowing with soft bioluminescence, surrounded by floating soap bubbles that contain tiny galaxies, cosmic nebula background, ethereal glowing particles, enchanting whimsical mood"},
    {"color":"灰","style":"像素","name":"方塊糖糖","mood":"雖然我只是方方的，但我們的友誼是滿滿的！","prompt":"A cute grey bear cub in pixel art style, standing in a cozy mushroom village, wearing a tiny explorer hat, holding a glowing lantern, 16-bit retro game aesthetic, vibrant colors on dark forest background, blocky charming design, nostalgic pixel game mood"}
]

def generate_thumbs(base_dir):
    """為指定目錄下的所有 PNG 圖片生成縮略圖"""
    thumbs_dir = os.path.join(base_dir, 'thumbs')
    
    # 建立縮略圖目錄
    if not os.path.exists(thumbs_dir):
        os.makedirs(thumbs_dir)
        print(f"  建立目錄: {thumbs_dir}")
    
    count = 0
    for f in os.listdir(base_dir):
        if f.endswith('.png') and not f.startswith('.'):
            img_path = os.path.join(base_dir, f)
            try:
                img = Image.open(img_path)
                name = os.path.splitext(f)[0]
                
                # 生成小縮略圖 (100x100)
                img_s = img.copy()
                img_s.thumbnail((100, 100))
                img_s.save(os.path.join(thumbs_dir, f'{name}-s.png'))
                
                # 生成中等縮略圖 (300x300)
                img_m = img.copy()
                img_m.thumbnail((300, 300))
                img_m.save(os.path.join(thumbs_dir, f'{name}-m.png'))
                
                print(f"  生成縮略圖: {f}")
                count += 1
            except Exception as e:
                print(f"  處理失敗 {f}: {e}")
    
    print(f"  縮略圖完成！共處理 {count} 張圖片")
    return count

def main():
    # 取得今天日期
    today = datetime.now().strftime('%Y-%m-%d')
    print(f"熊熊博物館更新任務開始！日期：{today}")
    print("="*50)
    
    # 讀取 workflow 模板
    with open('/home/fjj04/comfyui/workflow/Flux.2-Klein-文生图.json') as f:
        wf = json.load(f)
    
    # 生成圖片
    for i, bear in enumerate(bears):
        print(f"\n[{i+1}/5] 生成：{bear['name']} ({bear['color']}熊，{bear['style']}風格)")
        wf["93"]["inputs"]["text"] = bear["prompt"]
        wf["105"]["inputs"]["filename_prefix"] = f"{today}/熊熊_{bear['name']}"
        
        try:
            r = requests.post(f"{API}/prompt", json={"prompt": wf}, timeout=30)
            if r.status_code == 200:
                pid = r.json().get("prompt_id","")
                print(f"  提交成功，prompt_id={pid}")
                time.sleep(10)
                print(f"  完成：{bear['name']}")
            else:
                print(f"  失敗：{r.status_code}")
        except Exception as e:
            print(f"  錯誤：{e}")
    
    # 自動生成縮略圖
    print(f"\n開始生成縮略圖...")
    base_dir = f'/home/fjj04/my-bear-museum/bears/{today}'
    if os.path.exists(base_dir):
        generate_thumbs(base_dir)
    else:
        print(f"  目錄不存在: {base_dir}")
    
    print("\n" + "="*50)
    print("任務完成！")

if __name__ == '__main__':
    main()
