#!/usr/bin/env python3
"""
素材掃描腳本 - 掃描 materials/ 目錄並產生 metadata.json
"""

import json
import os
import re
from pathlib import Path
from datetime import datetime

# 分類對應
CATEGORY_MAP = {
    'borders': '邊框',
    'icons': '圖標',
    'backgrounds': '背景',
    'blocks': '區塊',
    'flowcharts': '流程圖',
    'buttons': '按鈕',
    'pagenumbers': '頁碼'
}

# 風格關鍵詞
STYLE_KEYWORDS = {
    'formal': ['政府', '公務', '政策', '施政', '業務', '年度', '議會', '報告', '專業', '商務', '正式', '古典'],
    'simple': ['極簡', '簡潔', '線條', '幾何', '留白', '現代', '科技'],
    'creative': ['創意', '活潑', '繽紛', '彩虹', '幾何', '抽象'],
    'bear': ['熊熊', '可愛', '溫暖', '童話', '收藏', '夢幻'],
    'nature': ['自然', '環保', '綠色', '植物', '健康', '清新'],
    'festival': ['春節', '端午', '中秋', '聖誕', '萬聖', '節慶', '紅金']
}

# 從檔名推斷名稱（移除日期前綴）
def extract_name(filename):
    # 移除 YYYYMMDD_ 前綴
    name = re.sub(r'^\d{8}_', '', filename)
    # 移除副檔名
    name = re.sub(r'\.(svg|jpg|png)$', '', name, flags=re.IGNORECASE)
    return name

# 從檔名推斷風格
def infer_style(name):
    name_upper = name.upper()
    for style, keywords in STYLE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in name_upper:
                return style
    return 'formal'  # 預設正式風格

# 從檔名推斷子分類
def infer_subcategory(filename, category):
    name = filename.upper()
    
    if category == 'borders':
        if '四角' in name:
            return '四角邊框'
        elif '單側' in name:
            return '單側邊框'
        elif '全框' in name:
            return '全框邊框'
    elif category == 'icons':
        if any(k in name for k in ['人員', '團隊', '協作']):
            return '人員相關'
        else:
            return '內容相關'
    elif category == 'backgrounds':
        if any(k in name for k in ['政府', '公務', '政策']):
            return '政府機關風格'
        elif any(k in name for k in ['科技', 'AI', '大數據', '雲端']):
            return '科技應用'
        elif any(k in name for k in ['活動', '頒獎', '記者', '成果']):
            return '活動場合'
        elif any(k in name for k in ['極簡', '線條', '幾何']):
            return '通用風格'
        else:
            return '通用風格'
    elif category == 'blocks':
        return '卡片區塊'
    elif category == 'flowcharts':
        return '步驟流程'
    
    return category

# 從日期資料夾名稱解析日期
def parse_date_from_folder(folder_name):
    match = re.match(r'(\d{4})-(\d{2})-(\d{2})', folder_name)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None

# 主程式
def scan_materials(base_path):
    materials = []
    
    materials_path = Path(base_path)
    
    # 遍歷所有日期資料夾
    for date_folder in sorted(materials_path.iterdir(), reverse=True):
        if not date_folder.is_dir():
            continue
        if not re.match(r'\d{4}-\d{2}-\d{2}', date_folder.name):
            continue
        
        date_str = date_folder.name
        
        # 遍歷所有分類資料夾
        for cat_folder in date_folder.iterdir():
            if not cat_folder.is_dir():
                continue
            
            category_key = cat_folder.name.lower()
            if category_key not in CATEGORY_MAP:
                continue
            
            category_name = CATEGORY_MAP[category_key]
            
            # 遍歷所有檔案
            for file in cat_folder.iterdir():
                if file.suffix.lower() not in ['.svg', '.jpg', '.png']:
                    continue
                
                filename = file.name
                
                # 解析
                name = extract_name(filename)
                style = infer_style(name)
                subcategory = infer_subcategory(filename, category_key)
                ext = file.suffix.lower().replace('.', '')
                
                # 產生路徑（相對於 my-bear-museum）
                rel_path = str(file.relative_to(materials_path.parent))
                
                material = {
                    'path': rel_path,
                    'name': name,
                    'shortName': name.split('_')[-1] if '_' in name else name,
                    'category': category_key,
                    'categoryName': category_name,
                    'subcategory': subcategory,
                    'style': style,
                    'description': f'{subcategory}素材',
                    'tags': [category_name, style],
                    'favorite': False,
                    'created': date_str,
                    'format': ext
                }
                
                materials.append(material)
    
    return materials

# 儲存為 JSON
def save_metadata(materials, output_path):
    metadata = {
        'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total': len(materials),
        'materials': materials
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 已產生 metadata.json，共 {len(materials)} 個素材")

# 統計
def print_stats(materials):
    print("\n📊 素材統計：")
    categories = {}
    styles = {}
    
    for m in materials:
        cat = m['categoryName']
        categories[cat] = categories.get(cat, 0) + 1
        style = m['style']
        styles[style] = styles.get(style, 0) + 1
    
    print("\n按分類：")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")
    
    print("\n按風格：")
    style_names = {
        'formal': '🏛️ 正式',
        'simple': '✨ 簡潔',
        'creative': '🎨 創意',
        'bear': '🐻 熊熊',
        'nature': '🌿 自然',
        'festival': '🎊 節慶'
    }
    for style, count in sorted(styles.items(), key=lambda x: -x[1]):
        name = style_names.get(style, style)
        print(f"  {name}: {count}")

# 主程式
if __name__ == '__main__':
    base_path = '/home/fjj04/my-bear-museum/materials'
    output_path = '/home/fjj04/my-bear-museum/materials/metadata.json'
    
    print("🔍 開始掃描素材...")
    materials = scan_materials(base_path)
    
    print(f"📦 找到 {len(materials)} 個素材")
    print_stats(materials)
    
    save_metadata(materials, output_path)