# 今日主角 Modal 左右滑動功能

## 目標
當「今日主角」區有多隻熊熊時，點擊任一熊熊卡片，開啟的詳情 Modal 除了能看該熊熊資料，還能用**左右滑動**（或按鍵盤方向鍵）切換到其他今日主角。

---

## 現況分析

### 今日主角輪播邏輯
- `getFeaturedBearsList()` 回傳所有被點星星的熊熊陣列（包含 featuredBear 如果已被星星標記）
- `renderFeaturedCarousel()` 渲染輪播 UI，單張時點擊直接 `openBearModalByRef`
- `openBearModalByRef(ref)` 開啟單一熊熊 Modal

### 問題
目前點擊今日主角卡片打開的 Modal **沒有**左右導航功能，無法滑到其他今日主角。

---

## 修改範圍

### 主要修改檔案
- `index.html`

### 需要變動的函式 / 區塊

| 位置 | 變動內容 |
|------|----------|
| `openBearModalByRef()` 附近 | 改造為支援「今日主角模式」：傳入額外參數或讀取 `featuredBearsList` 來追蹤目前位置 |
| Modal 結構 | 加入左右箭頭按鈕（與現有熊熊年鑑 Modal 樣式一致） |
| 事件監聽 | 鍵盤 `←` `→` 導航、觸控左右滑 |
| CSS | 箭頭按鈕樣式（可參考 `熊熊年鑑 Modal` 的箭頭樣式） |

---

## 實作步驟

### Step 1：改造 Modal 箭頭
在 `openBearModalByRef()` 的 Modal HTML 中加入左右箭頭按鈕：
```html
<div class="modal-nav modal-prev" onclick="modalPrevBear()">❮</div>
<div class="modal-nav modal-next" onclick="modalNextBear()">❯</div>
```

### Step 2：攜帶今日主角列表資訊
在點擊輪播卡片時，除了傳 `collectionNo`，再多傳一個「目前是第幾個」的 index，或是讓 Modal 能訪問到 `getFeaturedBearsList()`。

改造 `openBearModalByRef` 簽名：
```js
function openBearModalByRef(ref, featuredList = null, featuredIndex = -1) { ... }
```

點擊輪播卡片時傳入：
```js
onclick="openBearModalByRef('...', getFeaturedBearsList(), carouselIndex)"
```

### Step 3：實作 `modalPrevBear()` / `modalNextBear()`
- 根據 `featuredList` 和 `featuredIndex` 計算上一張/下一張
- 更新 Modal 內容（圖片、名字、編號、特性等）
- 更新圓點 active 狀態
- 處理邊界（最後一張→第一張，第一張→最後一張）

### Step 4：鍵盤 + 觸控支援
- 鍵盤：在 Modal 開啟時監聽 `keydown`（`←` `→`）
- 觸控：參考現有 `熊熊年鑑 Modal` 的 touch/swipe 邏輯（`touchstart/touchend` 計算水平滑動距離）

### Step 5：CSS 樣式
參考 `熊熊年鑑 Modal` 的箭頭樣式，確保左右箭頭在半透明黑底按鈕上可見。

---

## 驗證方式
1. 至少標記 2 隻熊熊為今日主角（點星星）
2. 點擊今日主角輪播區的任一卡片
3. Modal 開啟後，按鍵盤 `←` `→` 或點擊箭頭，確認能切換到其他今日主角
4. 觸控測試：左右滑動確認也能切換

---

## 風險 / 注意事項
- 今日主角只有 1 隻時，箭頭按鈕可以隱藏
- `openBearModalByRef` 同時也被其他地方呼叫（熊熊年鑑 Modal），需確認傳參相容
- 觸控滑動不要與 Modal 本身的 scroll 衝突，需要 `preventDefault`

---

## 參考現有實作
熊熊年鑑 Modal 已有完整的鍵盤+觸控導航，可直接複製邏輯再改造。