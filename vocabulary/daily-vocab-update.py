#!/usr/bin/env python3
"""
熊熊博物館——每日詞彙更新腳本
每天自動新增 10 個不重複的新詞到 vocabulary.json
"""
import json
import os
from datetime import datetime

VOCAB_DIR = os.path.expanduser("~/my-bear-museum/vocabulary")
WORLD_BUILDING_FILE = os.path.join(VOCAB_DIR, "world-building.json")
DAILY_WORDS_FILE = os.path.join(VOCAB_DIR, "daily-words-pool.json")
LOG_FILE = os.path.join(VOCAB_DIR, "update-log.json")

# 詞彙規則
INCLUDED = ["溫暖", "療癒", "童話", "收藏", "夢幻", "正向"]
EXCLUDED = ["負面詞彙", "暴力詞彙", "恐怖詞彙", "宗教爭議詞彙", "政治詞彙"]

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_all_used_words(wb):
    """取出所有已使用的詞"""
    used = set()
    for cat_data in wb['categories'].values():
        used.update(cat_data.get('words', []))
    return used

def count_words(wb):
    """計算詞庫總詞數"""
    return sum(len(cat_data.get('words', [])) for cat_data in wb['categories'].values())

def get_new_words(count=10):
    """從 pool 中取出未使用的新詞"""
    pool_data = load_json(DAILY_WORDS_FILE)
    # daily-words-pool.json 的詞在 pool_data['pool'] 陣列中
    all_pool_words = pool_data.get('pool', [])
    used = set()
    
    wb_path = WORLD_BUILDING_FILE
    if os.path.exists(wb_path):
        wb = load_json(wb_path)
        used = get_all_used_words(wb)
    
    # 找出未使用的詞
    available = [w for w in all_pool_words if w not in used]
    
    if len(available) < count:
        return available, []
    
    selected = available[:count]
    return selected, []

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"[{today}] 熊熊詞彙更新開始...")
    
    # 讀取世界觀詞庫
    if not os.path.exists(WORLD_BUILDING_FILE):
        print("錯誤：找不到 world-building.json")
        return
    
    wb = load_json(WORLD_BUILDING_FILE)
    used_before = get_all_used_words(wb)
    
    # 取得新詞
    new_words, skipped = get_new_words(10)
    
    if not new_words:
        print("沒有新的詞可以添加了。")
        return
    
    # 分散加入各分類（輪流）
    categories = list(wb['categories'].keys())
    for i, word in enumerate(new_words):
        cat = categories[i % len(categories)]
        wb['categories'][cat]['words'].append(word)
    
    # 更新版本與日期
    wb['updated'] = today
    if 'version' in wb:
        parts = wb.get('version', '1.0.0').split('.')
        parts[-1] = str(int(parts[-1]) + 1)
        wb['version'] = '.'.join(parts)
    
    save_json(WORLD_BUILDING_FILE, wb)
    
    used_after = get_all_used_words(wb)
    added = used_after - used_before
    
    # 記錄 log
    log = {}
    if os.path.exists(LOG_FILE):
        log = load_json(LOG_FILE)
    
    log[today] = {
        "added": list(added),
        "count": len(added),
        "total": count_words(wb)
    }
    save_json(LOG_FILE, log)
    
    print(f"已新增 {len(added)} 個詞彙")
    print(f"新增詞彙：{', '.join(added)}")
    print(f"詞庫總計：{count_words(wb)} 詞")

if __name__ == "__main__":
    main()
