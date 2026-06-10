// nav-component.js — Web Component 導航列
// 使用 Shadow DOM 完全隔離，不受任何頁面樣式影響

class NavBar extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._isOpen = false;
  }

  connectedCallback() {
    this.render();
    this.setupEventListeners();
    this.updateActiveLink();
  }

  injectBodyStyles() {
    if (document.getElementById('nav-offset-styles')) return;
    const style = document.createElement('style');
    style.id = 'nav-offset-styles';
    style.textContent = `
      body.sidebar-open > *:not(nav-bar) {
        transform: translateX(280px);
        transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      }
      body.sidebar-open {
        overflow-x: hidden;
      }
    `;
    document.head.appendChild(style);
  }

  get isOpen() {
    return this._isOpen;
  }

  set isOpen(val) {
    this._isOpen = val;
    this.injectBodyStyles();
    // Notify body for content offset
    if (val) {
      document.body.classList.add('sidebar-open');
    } else {
      document.body.classList.remove('sidebar-open');
    }
  }

  get styles() {
    const bgColor = '#a1887f';
    const hoverColor = '#8d6e63';
    const textColor = '#ffffff';
    const dividerColor = 'rgba(255,255,255,0.3)';
    const groupLabelColor = 'rgba(255,255,255,0.65)';
    const overlayBg = 'rgba(0,0,0,0.4)';
    const activeBg = 'rgba(255,255,255,0.15)';
    return `
      * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
      }

      :host {
        display: block;
        font-family: 'Noto Sans TC', 'Inter', 'Segoe UI', 'Microsoft JhengHei', sans-serif;
      }

      /* Hamburger button */
      .hamburger {
        position: fixed;
        top: 16px;
        left: 16px;
        right: auto;
        z-index: 1001;
        width: 44px;
        height: 44px;
        background: ${bgColor};
        border: none;
        border-radius: 10px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        transition: background 0.2s, transform 0.2s;
      }

      .hamburger svg {
        width: 22px;
        height: 22px;
        fill: ${textColor};
        transition: opacity 0.2s;
      }

      .hamburger:hover {
        background: ${hoverColor};
        transform: scale(1.05);
      }

      .hamburger:focus {
        outline: 2px solid #d4a574;
        outline-offset: 2px;
      }

      /* Overlay backdrop */
      .overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: ${overlayBg};
        z-index: 999;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.3s ease;
      }

      .overlay.active {
        opacity: 1;
        pointer-events: auto;
      }

      /* Sidebar */
      .sidebar {
        position: fixed;
        top: 0;
        left: 0;
        right: auto;
        width: 280px;
        height: 100vh;
        background: ${bgColor};
        z-index: 1000;
        transform: translateX(-100%);
        transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        display: flex;
        flex-direction: column;
        box-shadow: 4px 0 20px rgba(0,0,0,0.25);
        overflow-y: auto;
      }

      .sidebar.open {
        transform: translateX(0);
      }

      /* Sidebar header - full width banner */
      .sidebar-header {
        position: relative;
        width: 100%;
        height: 120px;
        overflow: hidden;
        border-bottom: 1px solid ${dividerColor};
      }

      .sidebar-header img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
        border-radius: 4px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        border: 1px solid rgba(255,255,255,0.15);
      }

      .sidebar-header .close-btn {
        position: absolute;
        top: 8px;
        right: 8px;
        z-index: 10;
      }

      .close-btn {
        width: 36px;
        height: 36px;
        background: rgba(255,255,255,0.2);
        border: none;
        border-radius: 8px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s;
        flex-shrink: 0;
      }

      .close-btn:hover {
        background: rgba(255,255,255,0.4);
      }

      .close-btn:focus {
        outline: 2px solid #d4a574;
        outline-offset: 2px;
      }

      .close-btn svg {
        width: 20px;
        height: 20px;
        fill: ${textColor};
      }

      /* Nav links */
      .nav-links {
        flex: 1;
        padding: 12px 0;
        overflow-y: auto;
      }

      .nav-group {
        padding: 0 12px;
        margin-bottom: 4px;
      }

      .group-label {
        font-size: 0.7rem;
        font-weight: 600;
        color: ${groupLabelColor};
        text-transform: uppercase;
        letter-spacing: 0.08em;
        padding: 10px 8px 6px;
        display: flex;
        align-items: center;
        gap: 5px;
      }

      .group-label::after {
        content: '';
        flex: 1;
        height: 1px;
        background: ${dividerColor};
        margin-left: 8px;
      }

      .nav-link {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 12px;
        color: ${textColor};
        text-decoration: none;
        font-size: 0.95rem;
        font-weight: 500;
        border-radius: 8px;
        transition: background 0.2s, transform 0.1s;
        margin: 2px 8px;
      }

      .nav-link:hover {
        background: ${hoverColor};
        transform: translateX(4px);
      }

      .nav-link:focus {
        outline: 2px solid #d4a574;
        outline-offset: -2px;
      }

      .nav-link.active {
        background: ${hoverColor};
        font-weight: 700;
      }

      .nav-link .icon {
        font-size: 1.1rem;
        width: 24px;
        text-align: center;
        flex-shrink: 0;
      }

      /* Mobile responsive */
      @media (max-width: 600px) {
        .sidebar {
          width: 100vw;
        }
      }
    `;
  }

  get currentPath() {
    return window.location.pathname.split('/').pop() || 'index.html';
  }

  updateActiveLink() {
    const current = this.currentPath;
    const links = this.shadowRoot.querySelectorAll('.nav-link');
    links.forEach(link => {
      const href = link.getAttribute('href');
      if (href === current) {
        link.classList.add('active');
      } else {
        link.classList.remove('active');
      }
    });
  }

  toggleSidebar() {
    this.isOpen = !this._isOpen;
    const sidebar = this.shadowRoot.querySelector('.sidebar');
    const overlay = this.shadowRoot.querySelector('.overlay');
    const hamburger = this.shadowRoot.querySelector('.hamburger');

    if (this.isOpen) {
      sidebar.classList.add('open');
      overlay.classList.add('active');
      hamburger.setAttribute('aria-expanded', 'true');
      document.body.style.overflow = 'hidden';
    } else {
      sidebar.classList.remove('open');
      overlay.classList.remove('active');
      hamburger.setAttribute('aria-expanded', 'false');
      document.body.style.overflow = '';
    }
  }

  closeSidebar() {
    if (this._isOpen) {
      this.isOpen = false;
      const sidebar = this.shadowRoot.querySelector('.sidebar');
      const overlay = this.shadowRoot.querySelector('.overlay');
      const hamburger = this.shadowRoot.querySelector('.hamburger');
      sidebar.classList.remove('open');
      overlay.classList.remove('active');
      hamburger.setAttribute('aria-expanded', 'false');
      document.body.style.overflow = '';
    }
  }

  setupEventListeners() {
    // Hamburger button click
    const hamburger = this.shadowRoot.querySelector('.hamburger');
    hamburger.addEventListener('click', () => this.toggleSidebar());

    // Close button click
    const closeBtn = this.shadowRoot.querySelector('.close-btn');
    closeBtn.addEventListener('click', () => this.closeSidebar());

    // Overlay click to close
    const overlay = this.shadowRoot.querySelector('.overlay');
    overlay.addEventListener('click', () => this.closeSidebar());

    // Nav link click to close sidebar
    const links = this.shadowRoot.querySelectorAll('.nav-link');
    links.forEach(link => {
      link.addEventListener('click', () => this.closeSidebar());
    });

    // ESC key to close
    this._escHandler = (e) => {
      if (e.key === 'Escape' && this._isOpen) {
        this.closeSidebar();
      }
    };
    document.addEventListener('keydown', this._escHandler);
  }

  disconnectCallback() {
    document.removeEventListener('keydown', this._escHandler);
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>${this.styles}</style>

      <button class="hamburger" aria-label="開啟導航選單" aria-expanded="false" aria-controls="sidebar">
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path d="M3 6h18v2H3V6zm0 5h18v2H3v-2zm0 5h18v2H3v-2z"/>
        </svg>
      </button>

      <div class="overlay" aria-hidden="true"></div>

      <nav class="sidebar" id="sidebar" role="navigation" aria-label="主導航">
        <div class="sidebar-header">
          <img src="/images/forest-banner.jpg" alt="森林" />
          <button class="close-btn" aria-label="關閉導航選單">
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
            </svg>
          </button>
        </div>

        <div class="nav-links">
          <div class="nav-group">
            <div class="group-label">🐻 熊熊系列</div>
            <a href="index.html" class="nav-link"><span class="icon">🏠</span>熊熊博物館</a>
            <a href="ppt.html" class="nav-link"><span class="icon">📊</span>PPT素材</a>
            <a href="slides.html" class="nav-link"><span class="icon">🎬</span>影片素材</a>
            <a href="video.html" class="nav-link"><span class="icon">🎥</span>熊熊影片</a>
            <a href="vocabulary.html" class="nav-link"><span class="icon">📚</span>詞彙庫</a>
          </div>

          <div class="nav-group">
            <div class="group-label">🐱 貓貓系列</div>
            <a href="meow.html" class="nav-link"><span class="icon">🐱</span>喵時光</a>
          </div>

          <div class="nav-group">
            <div class="group-label">🧪 測試系列</div>
            <a href="test-gallery.html" class="nav-link"><span class="icon">📷</span>圖片瀏覽</a>
            <a href="test-selection.html" class="nav-link"><span class="icon">✨</span>圖片選擇</a>
            <a href="test-stripe.html" class="nav-link"><span class="icon">🎨</span>設計系統</a>
          </div>
        </div>
      </nav>
    `;
  }
}

//註冊自訂元素
customElements.define('nav-bar', NavBar);
