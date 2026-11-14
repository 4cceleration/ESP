// Relevo entre internet y el ESP32.
//
// La placa abre una conexión WebSocket saliente hacia /_board (con su clave) y la
// deja abierta. Cuando alguien visita el sitio, el Durable Object le pide la página
// a la placa por esa conexión, la guarda un minuto y la entrega. Si la placa está
// apagada, se entrega la última copia guardada.
import { DurableObject } from "cloudflare:workers";

const FRESH_MS = 60_000;      // durante este tiempo no se vuelve a molestar a la placa
const ASK_TIMEOUT_MS = 8_000; // espera máxima por la respuesta de la placa
const MAX_PAGE = 300_000;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const board = env.BOARD.get(env.BOARD.idFromName("main"));

    if (url.pathname === "/_board") return board.fetch(request);
    if (url.pathname === "/api/blink") {
      if (request.method !== "POST") return new Response(null, { status: 405, headers: { Allow: "POST" } });
      return board.fetch(new Request(url.origin + "/api/blink", { method: "POST" }));
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response(null, { status: 405, headers: { Allow: "GET, HEAD" } });
    }
    if (url.pathname === "/_status") return board.fetch(new Request(url.origin + "/_status"));
    if (url.pathname !== "/" && url.pathname !== "/index.html") {
      return new Response("No encontrado", { status: 404, headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
    const res = await board.fetch(new Request(url.origin + "/"));
    return request.method === "HEAD" ? new Response(null, res) : res;
  },
};

function sameKey(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function pageResponse(page, source) {
  const headers = {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "public, max-age=60",
    "X-Served-By": "esp32",
    "X-Relay-Cache": source,
    "X-Page-Age": String(Math.round((Date.now() - page.at) / 1000)),
  };
  if (page.etag) headers.ETag = page.etag;
  if (page.gzip) {
    headers["Content-Encoding"] = "gzip";
    return new Response(page.body, { headers, encodeBody: "manual" });
  }
  return new Response(page.body, { headers });
}

const OFFLINE = `<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Sin conexión</title><body style="font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;text-align:center;padding:24px"><div><h1 style="margin:0 0 8px">La placa está desconectada</h1><p style="margin:0">Este sitio lo sirve un ESP32 que ahora mismo no responde. Vuelve a intentar en un momento.</p></div>`;

export class Board extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.pending = new Map();
    this.seq = 0;
    this.page = undefined;
    this.inflight = null;
    // La placa manda "ping" cada 30 s; se contesta sin despertar el objeto.
    this.ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair("ping", "pong"));
  }

  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/_board") return this.acceptBoard(request);
    if (url.pathname === "/_status") {
      const page = await this.loadPage();
      return Response.json({
        board_connected: this.ctx.getWebSockets().length > 0,
        page_age_s: page ? Math.round((Date.now() - page.at) / 1000) : null,
        page_bytes: page ? page.body.byteLength : 0,
      }, { headers: { "Cache-Control": "no-store" } });
    }
    if (url.pathname === "/api/blink") return this.blink();
    return this.servePage();
  }

  // Botón rojo: le ordena a la placa hacer titilar su LED (como mucho una orden por segundo).
  blink() {
    const headers = { "Cache-Control": "no-store" };
    const ws = this.ctx.getWebSockets()[0];
    if (!ws) return new Response(null, { status: 503, headers });
    const now = Date.now();
    if (now - (this.lastBlink || 0) > 1000) {
      this.lastBlink = now;
      try { ws.send('{"cmd":"blink"}'); } catch { return new Response(null, { status: 503, headers }); }
    }
    return new Response(null, { status: 202, headers });
  }

  acceptBoard(request) {
    if (request.headers.get("Upgrade") !== "websocket") {
      return new Response("Se esperaba WebSocket", { status: 426 });
    }
    const key = request.headers.get("X-Board-Key") || "";
    if (!this.env.BOARD_KEY || !sameKey(key, this.env.BOARD_KEY)) {
      return new Response("No autorizado", { status: 401 });
    }
    for (const old of this.ctx.getWebSockets()) {
      try { old.close(1012, "reemplazada"); } catch {}
    }
    const pair = new WebSocketPair();
    this.ctx.acceptWebSocket(pair[1]);
    return new Response(null, { status: 101, webSocket: pair[0] });
  }

  async loadPage() {
    if (this.page === undefined) this.page = (await this.ctx.storage.get("page")) ?? null;
    return this.page;
  }

  async servePage() {
    const saved = await this.loadPage();
    if (saved && Date.now() - saved.at < FRESH_MS) return pageResponse(saved, "HIT");

    const ws = this.ctx.getWebSockets()[0];
    if (ws) {
      try {
        // Varias visitas simultáneas comparten una sola pregunta a la placa.
        this.inflight ??= this.ask(ws).finally(() => { this.inflight = null; });
        const fresh = await this.inflight;
        this.page = fresh;
        await this.ctx.storage.put("page", fresh);
        return pageResponse(fresh, "MISS");
      } catch (err) {
        console.log("la placa no respondió:", err.message);
      }
    }
    if (saved) return pageResponse(saved, "STALE");
    return new Response(OFFLINE, { status: 503, headers: { "Content-Type": "text/html; charset=utf-8", "Retry-After": "30" } });
  }

  ask(ws) {
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error("tiempo agotado"));
      }, ASK_TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timer, chunks: [], size: 0, meta: null });
      ws.send(JSON.stringify({ id, path: "/" }));
    });
  }

  webSocketMessage(ws, message) {
    if (typeof message === "string") {
      let m;
      try { m = JSON.parse(message); } catch { return; }
      const p = this.pending.get(m.id);
      if (!p) return;
      if (!m.end) { p.meta = m; return; }
      clearTimeout(p.timer);
      this.pending.delete(m.id);
      if (!p.meta || p.meta.status !== 200 || p.size === 0) {
        p.reject(new Error("respuesta inválida de la placa"));
        return;
      }
      const body = new Uint8Array(p.size);
      let offset = 0;
      for (const c of p.chunks) { body.set(c, offset); offset += c.byteLength; }
      p.resolve({ at: Date.now(), body, gzip: !!p.meta.gzip, etag: p.meta.etag || "" });
      return;
    }
    // Binario: 4 bytes con el id de la petición + un trozo de la página.
    if (message.byteLength < 5) return;
    const id = new DataView(message).getUint32(0);
    const p = this.pending.get(id);
    if (!p) return;
    const chunk = new Uint8Array(message.slice(4));
    p.size += chunk.byteLength;
    if (p.size > MAX_PAGE) {
      clearTimeout(p.timer);
      this.pending.delete(id);
      p.reject(new Error("página demasiado grande"));
      return;
    }
    p.chunks.push(chunk);
  }

  webSocketClose(ws, code) {
    try { ws.close(code === 1005 || code === 1006 ? 1000 : code, "cerrada"); } catch {}
  }

  webSocketError() {}
}
