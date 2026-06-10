const CACHE_NAME = 'kuma-museum-v7';

// Cloudflare Pages 對不存在的路徑會回 200 + index.html，不可當成圖片/JSON 快取
function isImageRequest(request) {
  const path = new URL(request.url).pathname.toLowerCase();
  return /\.(png|jpe?g|gif|webp|svg|ico|avif)$/.test(path);
}

function isJsonRequest(request) {
  return new URL(request.url).pathname.endsWith('.json');
}

function isHtmlRequest(request) {
  const path = new URL(request.url).pathname;
  return path === '/' || path.endsWith('.html');
}

function isCacheableResponse(response, request) {
  if (!response || !response.ok) return false;
  const type = (response.headers.get('content-type') || '').toLowerCase();

  if (isImageRequest(request)) return type.startsWith('image/');
  if (isJsonRequest(request)) return type.includes('json');
  if (isHtmlRequest(request)) return type.includes('html');
  if (request.url.endsWith('.css')) return type.includes('css');
  if (request.url.endsWith('.js')) return type.includes('javascript') || type.includes('ecmascript');
  if (request.url.endsWith('.json')) return type.includes('json');
  if (request.url.endsWith('/manifest.json')) return type.includes('json');

  return true;
}

function isNetworkFirst(request) {
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return false;
  const path = url.pathname;
  return path === '/' || path.endsWith('.html') || path.endsWith('.json');
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (isCacheableResponse(response, request)) {
      cache.put(request, response.clone());
    } else {
      await cache.delete(request);
    }
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached && isCacheableResponse(cached, request)) return cached;
    throw error;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  if (cached) {
    if (isCacheableResponse(cached, request)) return cached;
    await cache.delete(request);
  }

  const response = await fetch(request);
  if (isCacheableResponse(response, request)) {
    cache.put(request, response.clone());
  }
  return response;
}

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(['/manifest.json']))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames =>
      Promise.all(
        cacheNames
          .filter(name => name !== CACHE_NAME)
          .map(name => caches.delete(name))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const { request } = event;
  if (request.method !== 'GET') return;
  if (!request.url.startsWith(self.location.origin)) return;

  if (isNetworkFirst(request)) {
    event.respondWith(networkFirst(request));
  } else {
    event.respondWith(cacheFirst(request));
  }
});
