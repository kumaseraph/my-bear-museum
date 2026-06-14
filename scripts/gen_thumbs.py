#!/usr/bin/env python3
"""生成熊图片缩略图脚本"""
import os
import sys
from PIL import Image
from datetime import datetime, timedelta

def generate_thumbs(base_dir):
    """为指定目录下的所有 PNG 图片生成缩略图"""
    thumbs_dir = os.path.join(base_dir, 'thumbs')
    
    # 创建缩略图目录
    if not os.path.exists(thumbs_dir):
        os.makedirs(thumbs_dir)
        print(f"创建目录: {thumbs_dir}")
    
    count = 0
    for f in os.listdir(base_dir):
        if f.endswith('.png') and not f.startswith('.'):
            img_path = os.path.join(base_dir, f)
            try:
                img = Image.open(img_path)
                name = os.path.splitext(f)[0]
                
                # 生成小缩略图 (100x100)
                img_s = img.copy()
                img_s.thumbnail((100, 100))
                img_s.save(os.path.join(thumbs_dir, f'{name}-s.png'))
                
                # 生成中等缩略图 (300x300)
                img_m = img.copy()
                img_m.thumbnail((300, 300))
                img_m.save(os.path.join(thumbs_dir, f'{name}-m.png'))
                
                print(f"生成缩略图: {f}")
                count += 1
            except Exception as e:
                print(f"处理失败 {f}: {e}")
    
    print(f"\n完成！共处理 {count} 张图片")
    return count

if __name__ == '__main__':
    if len(sys.argv) > 1:
        base_dir = sys.argv[1]
        generate_thumbs(base_dir)
    else:
        # 默认处理今天的目录
        today = datetime.now()
        found = False
        for i in range(2):
            date = today - timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')
            base_dir = f'/home/fjj04/my-bear-museum/bears/{date_str}'
            if os.path.exists(base_dir):
                print(f"\n处理目录: {date_str}")
                generate_thumbs(base_dir)
                found = True
                break
        if not found:
            print("未找到今日熊图片目录")
            sys.exit(1)
