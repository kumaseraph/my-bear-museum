# 熊熊博物館 v7.0 版面優化計畫

> 建立日期：2026-06-09
> 更新日期：2026-06-09
> 目標版本：v7.0

---

## 設計參考案例

本計畫參考了以下設計案例：

| 品牌/網站 | 設計特色 | 應用於本計畫 |
|-----------|----------|--------------|
| **Linear** | 深灰紫背景 (#1A1A2E)、溫暖灰調、圓角結構、漸層紫色、導航低調 | 深色模式配色 |
| **Linear Style** | 微動效、模糊效果、動態流光、漸層色彩 | Hero 裝飾動畫 |
| **Framer** | 滑動轉場、疊加卡片效果、指示點設計 | 輪播動畫 |
| **Airbnb** | 圖片中心展示、溫暖品牌色、圓角卡片 | 整體視覺風格 |

### Linear 深色模式關鍵學習
- 深灰背景不是純黑，用 `#1A1A2E`
- 溫暖灰調，不是冷藍灰
- 圓角代替分割線
- 漸層紫色 `#BB86FC` 作為強調色

### Linear Style 動效學習
- 微動效 (Micro-motion)：hover 上浮 + 陰影加深
- 模糊效果 (Blur)：側邊卡片虛化
- 動態流光 (Streamers)：漂浮裝飾動畫
- 漸層 (Gradient)：卡片邊框、裝飾線條

### 動效參數建議
| 動效 | 參數 |
|------|------|
| Hover 上浮 | `transform: translateY(-4px)` |
| 過渡時間 | `transition: 0.2s ease` |
| 陰影加深 | `box-shadow` 從 `0 4px 12px` → `0 8px 24px` |
| 卡片模糊 | `filter: blur(2px)` 側邊卡片 |
| 主題切換 | `transition: background-color 0.3s, color 0.3s` |

---

## 執行摘要

本計畫旨在優化熊熊博物館的視覺設計與使用者體驗，共 6 項優化項目，預計拆分为两阶段執行。

| 階段 | 項目 | 難度 | 風險 |
|------|------|------|------|
| 第一階段 | 深色模式、隨機看看、系列視覺化、Hero 優化 | ⭐⭐ | 低-中 |
| 第二階段 | 手機底部導航、精選熊熊大卡片輪播 | ⭐⭐⭐ | 中-高 |

---

## 項目清單

| # | 項目名稱 | 優先序 | 預估工時 | 狀態 |
|---|----------|--------|----------|------|
| P1 | 深色模式 | 1 | 1-2 小時 | 待評估 |
| P2 | 隨機看看 | 2 | 1 小時 | 待評估 |
| P3 | 系列視覺化 | 3 | 2 小時 | 待評估 |
| P4 | Hero 優化 | 4 | 2-3 小時 | 待評估 |
| P5 | 手機底部導航 | 5 | 1 小時 | 待評估 |
| P6 | 精選熊熊大卡片輪播 | 6 | 3-4 小時 | 待評估 |

---

## P1：深色模式

### 1.1 目標
提供手動切換的淺色/深色主題，切換結果記憶於瀏覽器 localStorage。

### 1.2 技術方案

#### CSS 架構
```
/* 預設淺色主題 */
:root {
  --bg-primary: #FFF5F5;
  --bg-card: #FFFFFF;
  --text-primary: #5D4E4E;
  --text-secondary: #8B7355;
  --border-gradient: linear-gradient(135deg, #FFD1DC, #E6E6FA, #B0E0E6);
  --star-color: #FFD700;
  --accent: #8B6914;
  --shadow: rgba(93, 64, 55, 0.15);
}

/* 深色主題 */
[data-theme="dark"] {
  --bg-primary: #1A1A2E;
  --bg-card: #2D2D44;
  --text-primary: #E8E8E8;
  --text-secondary: #B8B8C8;
  --border-gradient: linear-gradient(135deg, #4A4A6A, #3D3D5C);
  --star-color: #BB86FC;
  --accent: #BB86FC;
  --shadow: rgba(0, 0, 0, 0.4);
}
```

#### 主題切換按鈕
- 位置：Header 右側（或 Hero 區域）
- 圖示：☀️ / 🌙
- 動畫：旋轉 180 度過渡

#### JavaScript 邏輯
```javascript
function toggleTheme() {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  document.documentElement.setAttribute('data-theme', isDark ? 'light' : 'dark');
  localStorage.setItem('theme', isDark ? 'light' : 'dark');
}

// 頁面載入時讀取記憶
const savedTheme = localStorage.getItem('theme');
if (savedTheme) document.documentElement.setAttribute('data-theme', savedTheme);
```

### 1.3 影響範圍
- 全站所有 CSS 樣式（使用 CSS 變數自動適配）
- 圖片濾鏡：`filter: brightness(0.9) contrast(1.1)` 在深色模式下
- Modal 彈窗樣式
- 滾動條樣式（WebKit）

### 1.4 測試清單
- [ ] 點擊按鈕正確切換
- [ ] 關閉視窗後重新開啟，主題維持
- [ ] 手機版同樣正常運作
- [ ] 所有頁面（首頁、圖鑑、Modal）在兩種主題下皆正常顯示

### 1.5 風險與對策
| 風險 | 對策 |
|------|------|
| 某些熊熊圖片在深色背景不夠突出 | 對 `.bear-thumb img` 增加 `filter: brightness(1.05)` |
| 第三方嵌入內容（YouTube 等）不受影響 | 獨立包裝在 iframe 或增加包裝層 |

---

## P2：隨機看看

### 2.1 目標
提供一鍵隨機展示熊熊的功能，增加探索趣味性。

### 2.2 技術方案

#### 按鈕位置與樣式
- 位置：Hero 區域右側
- 樣式：膠囊形，漸層紫色背景 `#8B5CF6 → #A78BFA`
- 圖示：🎲
- Hover：上浮 2px + 陰影加深

#### 彈出卡片結構
```
┌─────────────────────────────────────────┐
│                                    [✕]  │
│                                          │
│           ╭─────────────────╮           │
│           │                 │           │
│           │    🐻 棉花糖    │           │
│           │   No.0015       │           │
│           │                 │           │
│           ╰─────────────────╯           │
│                                          │
│         🌸 童話夢境系列                   │
│                                          │
│   「甜进心坎裡的溫暖陪伴」                 │
│                                          │
│   [🔄 再看一隻] [⭐ 加入收藏] [📖 詳情]   │
│                                          │
└─────────────────────────────────────────┘
```

#### JavaScript 邏輯
```javascript
function showRandomBear() {
  const randomBear = bears[Math.floor(Math.random() * bears.length)];
  openBearModalByBear(randomBear, bears); // 複用現有 Modal
}

// 或使用獨立彈窗
function showRandomBearPopup() {
  const randomBear = bears[Math.floor(Math.random() * bears.length)];
  const popup = document.getElementById('randomPopup');
  popup.querySelector('.popup-name').textContent = randomBear.name;
  popup.querySelector('.popup-series').textContent = randomBear.series;
  popup.querySelector('.popup-quote').textContent = `"${randomBear.quote}"`;
  popup.querySelector('.popup-img').src = randomBear.img;
  popup.classList.add('active');
}
```

### 2.3 功能細節

| 功能 | 說明 |
|------|------|
| **再看一隻** | 關閉當前卡片，隨機抽出另一隻 |
| **加入收藏** | 呼叫 `toggleStar()` 星星功能 |
| **查看詳情** | 呼叫 `openBearModal()` 開啟完整 Modal |
| **關閉方式** | 點擊 ✕、點擊外部、按 ESC 鍵 |

### 2.4 測試清單
- [ ] 點擊按鈕彈出隨機熊熊
- [ ] 「再看一隻」更換不同熊熊
- [ ] 「加入收藏」星星亮起
- [ ] 「查看詳情」開啟完整 Modal
- [ ] ESC 鍵關閉彈窗
- [ ] 手機版點擊外部可關閉

### 2.5 風險與對策
| 風險 | 對策 |
|------|------|
| 隨機到同一隻熊連續多次 | 可紀錄最近 3 次，強制排除 |
| 動畫過場順暢度 | 使用 CSS `transform` + `opacity`，避免 reflow |

---

## P3：系列視覺化

### 3.1 目標
在首頁或導航附近新增系列展示區塊，幫助用戶快速理解熊熊分類。

### 3.2 技術方案

#### 佈局結構
```
┌──────────────────────────────────────────────────┐
│  🏷️ 熊熊系列                                      │
│                                                  │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐             │
│  │ 🌸 童話  │ │ 🌌 星際 │ │ ⚔️ 勇者 │  ...        │
│  │ 夢境    │ │ 冒險    │ │ 傳奇    │             │
│  │ ▓▓▓▓░░ │ │ ▓▓▓░░░ │ │ ▓▓░░░░ │             │
│  │ 12 隻   │ │  8 隻   │ │  6 隻   │             │
│  └─────────┘ └─────────┘ └─────────┘             │
└──────────────────────────────────────────────────┘
```

#### 系列顏色設定
| 系列 ID | 系列名稱 | 主色 | 輔色 | 漸層 |
|--------|----------|------|------|------|
| `fairy` | 童話夢境 | #FFD1DC | #DB7093 | `linear-gradient(135deg, #FFD1DC, #FFE4EC)` |
| `space` | 星際冒險 | #E6E6FA | #6B5B95 | `linear-gradient(135deg, #E6E6FA, #F0F0FF)` |
| `brave` | 勇者傳奇 | #B0E0E6 | #4682B4 | `linear-gradient(135deg, #B0E0E6, #E0F0F8)` |
| `warm` | 暖心守護 | #FFD1A4 | #8B6914 | `linear-gradient(135deg, #FFD1A4, #FFE4C4)` |
| `romantic` | 浪漫時光 | #FFE4E1 | #D87093 | `linear-gradient(135deg, #FFE4E1, #FFF0EE)` |
| `home` | 溫暖家園 | #FFE4B5 | #DEB887 | `linear-gradient(135deg, #FFE4B5, #FFF8DC)` |

#### 進度條計算
```javascript
const seriesData = {
  '童話夢境': { count: 0, color: '#FFD1DC' },
  '星際冒險': { count: 0, color: '#E6E6FA' },
  // ...
};

// 計算每個系列的數量
bears.forEach(bear => {
  if (seriesData[bear.series]) seriesData[bear.series].count++;
});

// 計算百分比
const total = bears.length;
Object.values(seriesData).forEach(s => {
  s.percent = Math.round((s.count / total) * 100);
});
```

#### 點擊篩選
```javascript
function filterBySeries(seriesName) {
  filterByCategory(seriesName); // 複用現有 filterByCategory
  document.getElementById('yearbookModal').scrollIntoView();
}
```

### 3.3 動畫設計
| 動畫 | 參數 |
|------|------|
| 卡片 hover | `transform: scale(1.03)` + `box-shadow` 加深 |
| 進度條填充 | `width: 0 → 100%`，使用 `transition: width 0.8s ease-out` |
| 數字計數 | 從 0 跳到實際數字，0.5 秒 |

### 3.4 測試清單
- [ ] 所有系列正確顯示
- [ ] 數量統計正確
- [ ] 進度條比例正確
- [ ] 點擊系列可篩選
- [ ] 手機版佈局正常（2x3 或 1x6）

### 3.5 風險與對策
| 風險 | 對策 |
|------|------|
| 新系列加入時需要手動更新 | 從 `bears` 資料動態計算，無需硬編碼 |
| 某系列數量為 0 時顯示空白 | 設定最小寬度 20px + 顯示「敬請期待」 |

---

## P4：Hero 優化

### 4.1 目標
美化首頁 Banner 區域，增加視覺吸引力與互動感。

### 4.2 技術方案

#### 結構設計
```
┌──────────────────────────────────────────────────┐
│  ✨ 漂浮裝飾層（position: absolute, z-index: 0）  │
│  ┌──────────────────────────────────────────┐   │
│  │  🐻 熊熊線上博物館 🐻                      │   │
│  │  每一個卡片都是一個溫暖的故事 ✨          │   │
│  │                                           │   │
│  │     ╭──────────────────────╮              │   │
│  │     │  🐾 35 館藏數量       │  ← 動畫數字 │   │
│  │     │  熊熊博物館           │              │   │
│  │     ╰──────────────────────╯              │   │
│  │                                           │   │
│  │  [🌙 深色模式]          [🎲 隨機看看]     │   │
│  └──────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

#### 漂浮裝飾動畫
```css
@keyframes float {
  0%, 100% { transform: translateY(0) rotate(0deg); opacity: 0.6; }
  50% { transform: translateY(-20px) rotate(180deg); opacity: 1; }
}

.floating-decoration {
  position: absolute;
  font-size: 20px;
  animation: float 4s ease-in-out infinite;
}
.floating-decoration:nth-child(2) { animation-delay: 0.5s; }
.floating-decoration:nth-child(3) { animation-delay: 1s; }
/* ... */
```

#### 數字動畫
```javascript
function animateCountUp(element, target, duration = 1500) {
  const start = 0;
  const startTime = performance.now();
  
  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const easeOut = 1 - Math.pow(1 - progress, 3);
    const current = Math.round(start + (target - start) * easeOut);
    element.textContent = current;
    
    if (progress < 1) requestAnimationFrame(update);
  }
  requestAnimationFrame(update);
}
```

#### 打字機效果
```javascript
function typeWriter(element, text, speed = 50) {
  let i = 0;
  element.textContent = '';
  
  function type() {
    if (i < text.length) {
      element.textContent += text.charAt(i);
      i++;
      setTimeout(type, speed);
    }
  }
  type();
}
```

### 4.3 響應式設計
| 斷點 | 調整 |
|------|------|
| > 768px | 完整 Hero，漂浮裝飾 8-10 個 |
| 481-768px | 簡化裝飾，5-6 個，縮小標題 |
| ≤ 480px | 最精簡，2-3 個裝飾，豎向排列按鈕 |

### 4.4 測試清單
- [ ] 漂浮裝飾動畫流暢
- [ ] 數字從 0 動畫到實際數量
- [ ] 打字機效果正常
- [ ] 手機版不爆版
- [ ] 與深色模式相容

### 4.5 風險與對策
| 風險 | 對策 |
|------|------|
| 打字機文字太長 | 設定 `max-width` 配合 `overflow: hidden`，或減少手機版字數 |
| 漂浮裝飾過多影響效能 | 使用 `will-change: transform`，裝飾數量根據螢幕大小調整 |

---

## P5：手機底部導航

### 5.1 目標
在行動裝置上提供底部固定導航列，提升手機用戶的操作便利性。

### 5.2 技術方案

#### 結構設計
```
┌──────────────────────────────────────────────────┐
│  [內容區域 - 可滾動]                              │
│  ...                                              │
│  ...                                              │
│  ...                                              │
├──────────────────────────────────────────────────┤
│  ┌────┐  ┌────┐  ┌────┐  ┌────┐                  │
│  │ 🏠 │  │ ⭐ │  │ 🎲 │  │ 👤 │                  │
│  │首頁│  │收藏│  │隨機│  │我的│                  │
│  └────┘  └────┘  └────┘  └────┘                  │
│  ▲ 底部固定導航列                                 │
└──────────────────────────────────────────────────┘
```

#### CSS 樣式
```css
@media (max-width: 768px) {
  .mobile-nav {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 60px;
    background: rgba(255, 255, 255, 0.85);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    display: flex;
    justify-content: space-around;
    align-items: center;
    padding-bottom: env(safe-area-inset-bottom);
    border-top: 1px solid rgba(0,0,0,0.1);
    z-index: 1000;
  }
  
  .mobile-nav-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    color: var(--text-secondary);
    text-decoration: none;
    font-size: 10px;
    transition: color 0.2s;
  }
  
  .mobile-nav-item.active {
    color: var(--accent);
  }
  
  .mobile-nav-item.active::before {
    content: '';
    position: absolute;
    top: -8px;
    width: 4px;
    height: 4px;
    background: var(--accent);
    border-radius: 50%;
  }
}
```

#### 與漢堡選單的衝突處理
```javascript
// 當螢幕宽度 > 768px，隱藏底部導航，顯示漢堡選單
// 當螢幕宽度 ≤ 768px，顯示底部導航，隱藏漢堡選單
function handleResize() {
  const isMobile = window.innerWidth <= 768;
  document.getElementById('mobileNav').style.display = isMobile ? 'flex' : 'none';
  document.getElementById('mainNav').classList.toggle('mobile-hidden', isMobile);
}
window.addEventListener('resize', handleResize);
handleResize(); // 初始執行
```

### 5.3 導航項目設計

| 圖示 | 文字 | 點擊行為 |
|------|------|----------|
| 🏠 | 首頁 | `window.scrollTo({ top: 0, behavior: 'smooth' })` |
| ⭐ | 收藏 | 開啟「我的收藏」Modal 或篩選已收藏熊熊 |
| 🎲 | 隨機 | 呼叫 `showRandomBear()` |
| 👤 | 我的 | 開啟用戶資訊/設定 Modal |

### 5.4 測試清單
- [ ] 手機版底部導航正常顯示
- [ ] 點擊各項目正確跳轉/執行
- [ ] 滑動內容時導航列保持固定
- [ ] iPhone 底部安全區域正確（不被 Home Bar 遮住）
- [ ] 電腦版不顯示底部導航
- [ ] 深色模式下樣式正確

### 5.5 風險與對策
| 風險 | 對策 |
|------|------|
| iPhone Home Bar 遮住導航 | `padding-bottom: env(safe-area-inset-bottom)` |
| 與現有 Modal 疊加層級衝突 | 導航列 `z-index: 1000`，Modal `z-index: 2000` |
| 點擊事件穿透 | 在打開 Modal 時隱藏底部導航 |

---

## P6：精選熊熊大卡片輪播

### 6.1 目標
將精選熊熊從現有的小縮圖並排改為大卡片輪播顯示，提升視覺效果與互動體驗。

### 6.2 技術方案

#### 結構設計
```
┌──────────────────────────────────────────────────┐
│  ✨ 精選熊熊                                       │
│                                                  │
│   ◀  ╭─────────────╮  ╭────╮  ╭────╮  ▶         │
│      │             │  │    │  │    │           │
│      │  雲朵綿綿   │  │蜜糖│  │雪地│           │
│      │             │  │爪爪│  │領袖│           │
│      │  🌸 童話   │  │    │  │    │           │
│      │             │  ╰────╯  ╰────╯           │
│      ╰─────────────╯                             │
│                                                  │
│         ● ○ ○ ○ ○  ← 指示點                      │
│                                                  │
│   ┌─────────────────────────────────────────┐   │
│   │ 「棉花糖一樣柔軟，甜进心坎裡」          │   │
│   │                    ── 雲朵綿綿 No.0012  │   │
│   └─────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

#### CSS 三卡片佈局
```css
.featured-carousel {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
  padding: 20px 0;
}

.featured-card {
  transition: all 0.4s ease;
  border-radius: 20px;
}

.featured-card.center {
  width: 200px;
  height: 260px;
  transform: scale(1.1);
  box-shadow: 0 20px 60px rgba(0,0,0,0.2);
  z-index: 2;
}

.featured-card.side {
  width: 120px;
  height: 160px;
  opacity: 0.6;
  transform: scale(0.85);
  filter: blur(2px);
  z-index: 1;
}

.featured-card.far-side {
  width: 80px;
  height: 110px;
  opacity: 0.3;
  transform: scale(0.6);
  filter: blur(4px);
}
```

#### 輪播邏輯
```javascript
let currentFeaturedIndex = 0;
const featuredCards = []; // 快取 DOM 元素

function updateCarousel() {
  featuredCards.forEach((card, i) => {
    const offset = i - currentFeaturedIndex;
    
    if (offset === 0) {
      card.className = 'featured-card center';
    } else if (Math.abs(offset) === 1) {
      card.className = `featured-card side ${offset > 0 ? 'right' : 'left'}`;
    } else if (Math.abs(offset) === 2) {
      card.className = `featured-card far-side ${offset > 0 ? 'right' : 'left'}`;
    } else {
      card.className = 'featured-card hidden';
    }
  });
  
  // 更新指示點
  updateDots();
  
  // 更新語錄
  updateQuote();
}

function nextFeatured() {
  currentFeaturedIndex = (currentFeaturedIndex + 1) % featuredList.length;
  updateCarousel();
}

function prevFeatured() {
  currentFeaturedIndex = (currentFeaturedIndex - 1 + featuredList.length) % featuredList.length;
  updateCarousel();
}
```

#### 觸控滑動支援
```javascript
let touchStartX = 0;
let touchEndX = 0;

carousel.addEventListener('touchstart', e => {
  touchStartX = e.changedTouches[0].screenX;
}, { passive: true });

carousel.addEventListener('touchend', e => {
  touchEndX = e.changedTouches[0].screenX;
  handleSwipe();
}, { passive: true });

function handleSwipe() {
  const diff = touchStartX - touchEndX;
  if (Math.abs(diff) > 50) { // 滑動超過 50px 認定為有效滑動
    if (diff > 0) {
      nextFeatured(); // 左滑 → 下一張
    } else {
      prevFeatured(); // 右滑 → 上一張
    }
  }
}
```

#### 自動播放
```javascript
let featuredAutoplayInterval;

function startFeaturedAutoplay() {
  featuredAutoplayInterval = setInterval(nextFeatured, 5000);
}

function stopFeaturedAutoplay() {
  clearInterval(featuredAutoplayInterval);
}

// 滑鼠懸停時暫停自動播放
carousel.addEventListener('mouseenter', stopFeaturedAutoplay);
carousel.addEventListener('mouseleave', startFeaturedAutoplay);

// 頁面可見性變化時暫停（用戶切換分頁時）
document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopFeaturedAutoplay();
  else startFeaturedAutoplay();
});
```

### 6.3 手機版適配
| 螢幕宽度 | 中間卡片 | 側邊卡片 | 顯示數量 |
|----------|----------|----------|----------|
| > 768px | 200×260px | 120×160px | 5 張（2 側 + 1 中 + 2 遠側）|
| 481-768px | 160×210px | 90×120px | 3 張 |
| ≤ 480px | 140×180px | 70×90px | 3 張 |

### 6.4 測試清單
- [ ] 點擊左右箭頭正確切換
- [ ] 點擊中間卡片開啟 Modal
- [ ] 點擊側邊卡片切換到該熊熊
- [ ] 指示點點擊跳轉
- [ ] 自動播放正常
- [ ] 滑鼠懸停暫停自動播放
- [ ] 分頁切換時暫停/繼續自動播放
- [ ] 手機滑動切換
- [ ] 語錄卡片正確更新
- [ ] 深色模式下樣式正確
- [ ] 手機版佈局正常

### 6.5 風險與對策
| 風險 | 對策 |
|------|------|
| 觸控滑動與頁面滑動衝突 | `touch-action: pan-y` 允許上下滑，攔截左右滑 |
| 自動播放造成效能問題 | 使用 `requestAnimationFrame`，分頁隱藏時清除 interval |
| 輪播動畫卡頓 | 使用 CSS `transform` 而非改變 `width/height` |
| 熊熊數量少於 5 隻時佈局破版 | 根據實際數量動態調整 CSS class |

---

## 測試總檢核

每個項目完成後，都需要通過以下通用測試：

### 跨主題測試
- [ ] 淺色模式下正常
- [ ] 深色模式下正常
- [ ] 主題切換時平滑過渡

### 跨裝置測試
- [ ] 電腦版（1920px 以上）
- [ ] 平板（768px - 1024px）
- [ ] 手機（375px - 428px）

### 效能測試
- [ ] Lighthouse Performance > 90
- [ ] 無 JavaScript 錯誤
- [ ] 無 layout shift

---

## 版本規劃

| 版本 | 內容 |
|------|------|
| v6.70 | 深色模式上線 |
| v6.71 | 隨機看看上線 |
| v6.72 | 系列視覺化上線 |
| v6.73 | Hero 優化上線 |
| v6.74 | 手機底部導航上線 |
| v6.75 | 精選熊熊大卡片輪播上線 |

---

*熊熊博物館 v7.0 計畫完成*