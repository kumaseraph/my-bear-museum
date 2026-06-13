#!/usr/bin/env python3
"""split_story_to_frames 單元測試"""

import sys
import os
import importlib.util
from pathlib import Path

# 動態載入（因為檔名有 hyphens，不能直接 import）
spec = importlib.util.spec_from_file_location(
    "daily_meow_delivery",
    Path(__file__).parent.parent / "daily-meow-delivery.py"
)
dm = importlib.util.module_from_spec(spec)
sys.modules["daily_meow_delivery"] = dm
spec.loader.exec_module(dm)
split_story_to_frames = dm.split_story_to_frames

def test_newline_split():
    """測試換行符分隔（熊熊的故事格式）：需要 >=4 行"""
    story = "第一句\n第二句\n第三句\n第四句"
    frames = split_story_to_frames(story)
    assert len(frames) == 4, f"預期 4 帧，實際 {len(frames)}"
    assert frames[0] == "第一句。"
    assert frames[1] == "第二句。"
    assert frames[2] == "第三句。"
    assert frames[3] == "第四句。"
    print("✅ test_newline_split 通過")

def test_dunhao_split():
    """測試句號（。）分隔：需要 <4 行才會走這個邏輯"""
    story = "第一句。第二句。第三句。第四句。"
    frames = split_story_to_frames(story)
    assert len(frames) == 4, f"預期 4 帧，實際 {len(frames)}"
    assert frames[0] == "第一句。"
    assert frames[1] == "第二句。"
    assert frames[2] == "第三句。"
    assert frames[3] == "第四句。"
    print("✅ test_dunhao_split 通過")

def test_no_punctuation():
    """測試句末沒有標點（程式自動加句號）- 需要 >=4 行走換行邏輯"""
    story = "第一句\n第二句\n第三句\n第四句"
    frames = split_story_to_frames(story)
    assert len(frames) == 4, f"預期 4 帧，實際 {len(frames)}"
    assert frames[0] == "第一句。"      # 自動加句號
    assert frames[1] == "第二句。"
    assert frames[2] == "第三句。"
    assert frames[3] == "第四句。"
    print("✅ test_no_punctuation 通過")

def test_exclamation_question():
    """測試驚嘆號和問號結尾 - 需要 >=4 行走換行邏輯"""
    story = "第一句？\n第二句！\n第三句？\n第四句！"
    frames = split_story_to_frames(story)
    assert len(frames) == 4, f"預期 4 帧，實際 {len(frames)}"
    assert frames[0] == "第一句？"
    assert frames[1] == "第二句！"
    assert frames[2] == "第三句？"
    assert frames[3] == "第四句！"
    print("✅ test_exclamation_question 通過")

def test_empty_lines():
    """測試空行被忽略（但不影響換行判斷）"""
    # 熊熊的真實故事格式：4行，帶空行
    story = "第一句\n\n第二句\n\n第三句\n\n第四句"
    frames = split_story_to_frames(story)
    # 空行被過濾後得到 4 行，觸發換行邏輯
    assert len(frames) == 4, f"預期 4 帧，實際 {len(frames)}"
    assert frames[0] == "第一句。"
    assert frames[3] == "第四句。"
    print("✅ test_empty_lines 通過")

if __name__ == "__main__":
    test_newline_split()
    test_dunhao_split()
    test_no_punctuation()
    test_exclamation_question()
    test_empty_lines()

    # 測試 read_story_from_file（使用真實的 story-today.txt）
    dm.setup_variables()
    result = dm.read_story_from_file('冒險', '2026-06-13')
    lines = result.split('\n')
    # 應該只有 4 行故事，不包含 header 註解
    assert len(lines) == 4, f"預期 4 行故事，實際 {len(lines)}"
    assert lines[0] == "在月光下醒來，橘貓妹妹看見窗外有光。"
    assert not any('故事類型' in l for l in lines), "不應包含『故事類型』"
    assert not any('日期' in l for l in lines), "不應包含『日期』"
    assert not any(l.startswith('#') for l in lines), "不應包含註解行"
    print("✅ test_read_story_from_file 通過")

    print("\n🎉 所有測試通過！")