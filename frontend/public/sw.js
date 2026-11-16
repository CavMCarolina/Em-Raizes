// Service worker: guarda a "casca" do app para abrir sem internet e mostra as notificações push.
// A API (/api/...) nunca é cacheada: comandos e dados sempre vão para o servidor.
const CACHE = "em-raizes-admin-v2";
const CASCA = ["/", "/index.html", "/manifest.webmanifest", "/icone.svg", "/icone-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(CASCA)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        const copia = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copia));
        return r;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("/index.html"))),
  );
});

// Notificação push vinda do servidor (alerta, chuva, emergência, foto com risco).
self.addEventListener("push", (e) => {
  let dados = {};
  try {
    dados = e.data ? e.data.json() : {};
  } catch {
    dados = { corpo: e.data ? e.data.text() : "" };
  }
  const titulo = dados.titulo || "Em Raízes";
  e.waitUntil(
    self.registration.showNotification(titulo, {
      body: dados.corpo || "",
      icon: "/icone-192.png",
      badge: "/icone-192.png",
      tag: dados.tag || "geral", // mesma tag = substitui em vez de empilhar
      renotify: dados.nivel === "perigo",
      requireInteraction: dados.nivel === "perigo",
      data: { url: dados.url || "/#/inicio" },
    }),
  );
});

// Tocar na notificação abre (ou foca) o app na tela certa.
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const destino = new URL(e.notification.data?.url || "/#/inicio", self.location.origin).href;
  e.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((janelas) => {
      for (const j of janelas) {
        if (new URL(j.url).origin === self.location.origin) {
          j.navigate(destino);
          return j.focus();
        }
      }
      return self.clients.openWindow(destino);
    }),
  );
});
