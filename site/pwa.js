// 앱 설치(PWA): service worker 등록, 설치 단추(안드로이드·PC 크롬·엣지), iPhone·iPad 안내.
// app.js가 자료를 다 받기 전에 설치 이벤트가 올 수 있어 따로 먼저 읽음(defer)
(() => {
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost'))
    addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => { /* 등록 실패해도 웹은 그대로 씀 */ }));
  const installed = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  const btn = document.getElementById('app-install'), hint = document.getElementById('app-ios');
  let ask = null;
  addEventListener('beforeinstallprompt', e => { e.preventDefault(); ask = e; btn.hidden = false; });
  addEventListener('appinstalled', () => { ask = null; btn.hidden = true; });
  btn.onclick = async () => { if (!ask) return; ask.prompt(); await ask.userChoice; ask = null; btn.hidden = true; };
  // iOS Safari에는 설치 창이 없어 방법을 알려 줌(iPadOS는 Mac처럼 보고하므로 터치 여부로 구분)
  const ios = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  if (ios && !installed) hint.hidden = false;
})();
