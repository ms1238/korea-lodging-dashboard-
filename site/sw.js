// 숙박관광 대시보드 service worker: 한 번 연 화면과 자료를 저장해 두어 오프라인에서도 열리게 함
const VERSION = '__BUILD__';  // the workflow writes the commit here, so each code deploy installs a fresh worker and cache
const CACHE = 'lodging-' + VERSION, LIB = 'lodging-lib-v1';
const SHELL = ['./', 'index.html', 'style.css', 'theme-datalab.css', 'app.js', 'indicators.json', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon.svg'];
const LIBS = ['https://unpkg.com/', 'https://cdn.jsdelivr.net/'];  // version-pinned libraries and fonts

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE && k !== LIB).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  if (LIBS.some(p => req.url.startsWith(p))) {  // pinned versions never change: saved copy first
    e.respondWith(caches.open(LIB).then(c => c.match(req).then(hit => hit || fetch(req).then(r => {
      if (r.ok || r.type === 'opaque') c.put(req, r.clone());
      return r;
    }))));
    return;
  }
  const url = new URL(req.url);
  if (url.origin !== location.origin || url.pathname.includes('/data/download/')) return;  // map tiles, APIs and large downloads: network only
  // the page and its data are rebuilt every day: network first, the saved copy when offline
  e.respondWith(fetch(req).then(r => {
    if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
    return r;
  }).catch(() => caches.match(req, { ignoreSearch: true })
    .then(hit => hit || (req.mode === 'navigate' ? caches.match('./') : Response.error()))));
});
