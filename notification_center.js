(function () {
  'use strict';
  const API = 'https://speakchain-bot-production.up.railway.app';
  let model = {items: [], unread: 0, push: {}};
  let mounted = false;

  function esc(value) {
    const node = document.createElement('span'); node.textContent = String(value || ''); return node.innerHTML;
  }
  function socialReadIds() {
    try { return new Set(JSON.parse(localStorage.getItem('speakchain.notifications.socialRead') || '[]')); }
    catch (_) { return new Set(); }
  }
  function rememberSocialRead(id) {
    const ids = socialReadIds(); ids.add(id);
    try { localStorage.setItem('speakchain.notifications.socialRead', JSON.stringify(Array.from(ids).slice(-200))); } catch (_) {}
  }
  async function request(op, extra) {
    const response = await fetch(API + '/api/v1/notifications', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.assign({op: op || 'list'}, extra || {})),
    });
    if (!response.ok) throw new Error('notifications_' + response.status);
    return response.json();
  }
  function icon(kind) {
    return {payment:'💳', support:'💬', challenge:'🎯', match:'🤝', webinar:'🔴', social:'👥'}[kind] || '🔗';
  }
  function relative(value) {
    const delta = Date.now() - Date.parse(value || '');
    if (!Number.isFinite(delta) || delta < 60000) return 'щойно';
    if (delta < 3600000) return Math.floor(delta / 60000) + ' хв тому';
    if (delta < 86400000) return Math.floor(delta / 3600000) + ' год тому';
    return new Date(value).toLocaleDateString('uk-UA', {day:'numeric', month:'short'});
  }
  function render() {
    const badge = document.getElementById('sc-notification-badge');
    if (badge) { badge.textContent = model.unread > 99 ? '99+' : String(model.unread || ''); badge.hidden = !model.unread; }
    const list = document.getElementById('sc-notification-list');
    if (!list) return;
    const pushCard = !model.push.telegram_primary && model.push.supported && Notification.permission === 'default'
      ? '<button class="sc-push-card" id="sc-enable-push"><b>Увімкнути нагадування</b><span>Важливі події приходитимуть навіть коли застосунок закритий.</span></button>' : '';
    const empty = '<div class="sc-notification-empty">Тут з’являтимуться важливі події, відповіді підтримки та новини навчання.</div>';
    list.innerHTML = pushCard + (model.items.length ? model.items.map(item =>
      '<button class="sc-notification-item ' + (!item.read_at ? 'unread' : '') + '" data-id="' + esc(item.id) + '" data-url="' + esc(item.url) + '">' +
      '<span class="sc-notification-icon">' + icon(item.kind) + '</span><span class="sc-notification-copy"><b>' + esc(item.title) + '</b>' +
      '<span>' + esc(item.body) + '</span><small>' + esc(relative(item.created_at)) + '</small></span></button>'
    ).join('') : empty);
    document.getElementById('sc-enable-push')?.addEventListener('click', enablePush);
    list.querySelectorAll('.sc-notification-item').forEach(button => button.addEventListener('click', async () => {
      const id = button.dataset.id || '';
      if (id.startsWith('social:')) rememberSocialRead(id);
      else await request('read', {id}).catch(() => null);
      button.classList.remove('unread');
      if (button.dataset.url) location.href = button.dataset.url;
      else await load();
    }));
  }
  async function load() {
    try {
      model = await request('list');
      const seen = socialReadIds();
      model.items.forEach(item => { if (String(item.id).startsWith('social:') && seen.has(item.id)) item.read_at = item.read_at || 'local'; });
      model.unread = model.items.filter(item => !item.read_at).length;
      render();
    } catch (_) {}
  }
  function urlBase64ToUint8Array(value) {
    const padding = '='.repeat((4 - value.length % 4) % 4);
    const base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/');
    return Uint8Array.from(atob(base64), char => char.charCodeAt(0));
  }
  async function enablePush() {
    if (!('Notification' in window) || !('serviceWorker' in navigator)) return;
    const permission = await Notification.requestPermission();
    await request('permission', {permission}).catch(() => null);
    if (permission !== 'granted' || !model.push.public_key) { await load(); return; }
    const registration = await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(model.push.public_key),
    });
    await request('subscribe', {subscription: subscription.toJSON()});
    await load();
  }
  function open() {
    document.getElementById('sc-notification-center')?.classList.add('open');
    document.getElementById('sc-notification-center')?.setAttribute('aria-hidden', 'false');
    load();
  }
  function close() {
    document.getElementById('sc-notification-center')?.classList.remove('open');
    document.getElementById('sc-notification-center')?.setAttribute('aria-hidden', 'true');
  }
  function mount() {
    if (mounted) return; mounted = true;
    const style = document.createElement('style');
    style.textContent = '.sc-bell{position:relative;width:36px;height:36px;border:0;border-radius:50%;background:var(--bg-card2,#1e1e2a);color:var(--text,#fff);font-size:18px;cursor:pointer}.sc-badge{position:absolute;right:-3px;top:-4px;min-width:17px;height:17px;padding:0 4px;border-radius:9px;background:#f04444;color:#fff;font:800 10px/17px sans-serif}.sc-center{position:fixed;inset:0;z-index:12000;display:none;background:rgba(0,0,0,.55)}.sc-center.open{display:block}.sc-panel{position:absolute;right:0;top:0;width:min(100%,430px);height:100%;background:var(--bg,#0d0d14);color:var(--text,#eaeaf5);display:flex;flex-direction:column;box-shadow:-12px 0 40px rgba(0,0,0,.45)}.sc-center-head{display:flex;align-items:center;padding:max(16px,env(safe-area-inset-top)) 16px 14px;border-bottom:1px solid var(--line,#2a2a3a)}.sc-center-head h2{font-size:20px;flex:1}.sc-center-head button{border:0;background:transparent;color:inherit;font-size:28px}.sc-list{overflow:auto;padding:8px 12px 24px}.sc-notification-item,.sc-push-card{width:100%;display:flex;text-align:left;border:0;border-bottom:1px solid var(--line,#2a2a3a);background:transparent;color:inherit;padding:14px 8px;gap:11px}.sc-notification-item.unread{background:rgba(124,110,247,.09)}.sc-notification-item.unread b:after{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:#7c6ef7;margin-left:7px}.sc-notification-icon{font-size:22px}.sc-notification-copy{display:flex;flex:1;min-width:0;flex-direction:column;gap:4px}.sc-notification-copy b{font-size:14px}.sc-notification-copy span{font-size:13px;color:var(--text2,#8888a8);line-height:1.4}.sc-notification-copy small{font-size:11px;color:var(--text3,#666)}.sc-push-card{margin:8px 0;border:1px solid rgba(124,110,247,.4);border-radius:13px;background:rgba(124,110,247,.12);flex-direction:column}.sc-push-card span{color:var(--text2,#8888a8);font-size:12px}.sc-notification-empty{padding:48px 22px;text-align:center;color:var(--text2,#8888a8);line-height:1.5}';
    document.head.appendChild(style);
    const center = document.createElement('div'); center.id = 'sc-notification-center'; center.className = 'sc-center'; center.setAttribute('aria-hidden', 'true');
    center.innerHTML = '<section class="sc-panel" role="dialog" aria-modal="true" aria-label="Повідомлення"><header class="sc-center-head"><h2>Повідомлення</h2><button id="sc-notification-close" aria-label="Закрити">×</button></header><div class="sc-list" id="sc-notification-list"></div></section>';
    document.body.appendChild(center); center.addEventListener('click', event => { if (event.target === center) close(); });
    document.getElementById('sc-notification-close').onclick = close;
    const bell = document.createElement('button'); bell.className = 'sc-bell'; bell.setAttribute('aria-label', 'Повідомлення'); bell.innerHTML = '🔔<span class="sc-badge" id="sc-notification-badge" hidden></span>'; bell.onclick = open;
    const host = document.querySelector('.top-right'); if (host) host.insertBefore(bell, host.firstChild); else document.body.appendChild(bell);
    window.SC_PWA?.ready?.then(load).catch(() => {});
    setInterval(() => { if (document.visibilityState === 'visible') load(); }, 60000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true}); else mount();
})();
