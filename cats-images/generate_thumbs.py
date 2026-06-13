#!/usr/bin/env python3
"""生成喵漫圖片縮圖"""
import os
import json
from PIL import Image

THUMB_SIZES = {
    's': (200, 200),   # 小縮圖
    'm': (400, 400),   # 中縮圖
}

def generate_thumb(img_path, thumb_dir, prefix):
    """為單張圖片生成縮圖"""
    try:
        img = Image.open(img_path)
        
        # 保持寬高比，最大邊限制為目標尺寸
        img.thumbnail(THUMB_SIZES[prefix], Image.Resampling.LANCZOS)
        
        # 生成輸出路徑
        basename = os.path.basename(img_path)
        name, ext = os.path.splitext(basename)
        thumb_path = os.path.join(thumb_dir, f"{name}-{prefix}{ext}")
        
        img.save(thumb_path, quality=85, optimize=True)
        print(f"  生成: {thumb_path}")
        return f"thumbs/{basename}"
    except Exception as e:
        print(f"  錯誤: {img_path} - {e}")
        return None

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 遍歷所有日期目錄
    for date_dir in sorted(os.listdir(base_dir)):
        date_path = os.path.join(base_dir, date_dir)
        if not os.path.isdir(date_path) or not date_dir.startswith('2026-'):
            continue
        
        print(f"\n處理 {date_dir}...")
        
        # 創建縮圖目錄
        thumb_dir = os.path.join(date_dir, 'thumbs')
        os.makedirs(thumb_dir, exist_ok=True)
        
        # 處理目錄中的圖片
        for filename in sorted(os.listdir(date_path)):
            if filename.startswith('.'):
                continue
            
            img_path = os.path.join(date_dir, filename)
            
            if os.path.isfile(img_path) and filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                # 生成兩種尺寸的縮圖
                generate_thumb(img_path, thumb_dir, 's')
                generate_thumb(img_path, thumb_dir, 'm')
    
    print("\n縮圖生成完成！")

if __name__ == '__main__':
    main()
