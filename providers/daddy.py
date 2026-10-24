"""
DaddyLive provider - risoluzione nome->ID (o ID diretto) + URL stabile self-healing.

Doppia protezione dai cambi di dominio:
- FRONTEND MIRRORS: lista domini equivalenti (thedaddy.pk, dlive.sx, ...) per
  la lista canali e i referer; il primo vivo vince.
- EMBED MIRRORS: lista host embed (bembed.sbs, thedaddy.pk, ...) da cui estrarre
  const SRC: se bembed.sbs muore, il sistema passa al successivo da solo.
Discovery: direct-first; fallback proxy CORS con cache-buster.
Query numerica nel channels.json (es. "204") = ID diretto, senza ricerca per nome.
Playlist: URL stabili /live?ch=<id> -> il Val risolve l'edge al volo.
"""

import re
import logging
import time
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

# ★ FRONTEND MIRRORS: lista canali + referer (primo vivo vince, ordine = priorita)
MIRRORS = [
    "https://thedaddy.pk",
    "https://dlive.sx",
    "https://thedaddy.to",
    "https://daddylives.top",
    "https://papahd.live",
    "https://dlhd.sbs",
    "https://dlhd.pk",
    "https://dlstreams.st",
]

# ★ EMBED MIRRORS: host da cui estrarre const SRC (bembed.sbs e le sue gemelle)
EMBED_MIRRORS = [
    "https://bembed.sbs",
    "https://thedaddy.pk",
    "https://thedaddy.to",
    "https://daddylives.top",
    "https://papahd.live",
]
EMBED_PATH = "/premiumtv/daddy.php?id={cid}"

# IL VAL VAL.TOWN
WORKER_BASE = "https://simo11.val.run/daddy-stream"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DISCOVERY_PROXIES = [
    lambda u: "https://api.allorigins.win/raw?url=" + quote(u, safe=""),
    lambda u: "https://api.codetabs.com/v1/proxy?quest=" + u,
    lambda u: "https://corsproxy.io/?url=" + quote(u, safe=""),
    lambda u: "https://api.cors.lol/?url=" + quote(u, safe=""),
]

_channel_cache = None
_edge_map = {}


def get_edge_map():
    """Restituisce la mappa id_canale -> URL edge (per edge.json di fallback)."""
    return dict(_edge_map)


def _fetch(url: str, referer: str = None, timeout: int = 12, must_contain: str = None) -> requests.Response:
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 50:
            if must_contain is None or must_contain in r.text:
                return r
    except Exception:
        pass
    for make_proxy in DISCOVERY_PROXIES:
        try:
            busted = url + ("&" if "?" in url else "?") + "nocache=" + str(int(time.time() * 1000))
            r = requests.get(make_proxy(busted), headers=headers, timeout=timeout + 5)
            if r.status_code == 200 and len(r.text) > 50:
                if must_contain is None or must_contain in r.text:
                    return r
        except Exception:
            continue
    raise RuntimeError(f"Fetch fallita: {url[:70]}")


def fetch_channel_list() -> dict:
    global _channel_cache
    if _channel_cache is not None:
        return _channel_cache

    for mirror in MIRRORS:
        try:
            html = _fetch(f"{mirror}/24-7-channels.php").text
            pattern = re.compile(
                r'href="(?:[^"]*?/)?watch\.php\?id=(\d+)"[^>]*data-title="([^"]+)"',
                re.IGNORECASE
            )
            channels = {}
            for m in pattern.finditer(html):
                cid = int(m.group(1))
                name = m.group(2).strip()
                if name:
                    channels[name] = cid
            if channels:
                logger.info("DaddyLive: trovati %d canali via %s", len(channels), mirror)
                _channel_cache = channels
                return channels
        except Exception as e:
            logger.warning("DaddyLive mirror %s fallito: %s", mirror, e)

    raise RuntimeError("DaddyLive: nessun mirror raggiungibile")


def find_channel_id(channels: dict, query: str) -> int:
    q = query.lower().strip()
    for name, cid in channels.items():
        if name.lower() == q:
            return cid
    for name, cid in channels.items():
        if q in name.lower():
            return cid
    words = set(q.split())
    best_score, best_id = 0, None
    for name, cid in channels.items():
        score = len(words & set(name.lower().split()))
        if score > best_score:
            best_score, best_id = score, cid
    if best_id and best_score >= max(1, len(words) - 1):
        return best_id
    raise ValueError(f"DaddyLive: canale '{query}' non trovato")


def _extract_real_stream(cid: int) -> str:
    """Prova OGNI embed mirror finche' uno non restituisce const SRC:
    se bembed.sbs muore, thedaddy.pk/daddylives/papahd subentrano da soli."""
    last_err = ""
    for host in EMBED_MIRRORS:
        embed_url = host + EMBED_PATH.format(cid=cid)
        try:
            html = _fetch(embed_url, referer=f"{host}/stream/stream-{cid}.php",
                          must_contain=".m3u8").text
            m = re.search(r'const\s+SRC\s*=\s*"([^"]+?\.m3u8)"', html)
            if m:
                src = m.group(1)
                sep = "&" if "?" in src else "?"
                return f"{src}{sep}_={int(time.time() * 1000)}"
            m3 = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
            if m3:
                return m3.group(0)
        except Exception as e:
            last_err = f"{host}: {e}"
    raise RuntimeError(f"Stream non trovato per canale {cid}. Ultimo errore: {last_err}")


def get_stream(channel_name: str) -> dict:
    channels = fetch_channel_list()
    cid = find_channel_id(channels, channel_name)
    return _resolve_cid(cid)


def get_stream_by_id(cid: int) -> dict:
    return _resolve_cid(cid)


def _resolve_cid(cid: int) -> dict:
    real_url = _extract_real_stream(cid)
    _edge_map[str(cid)] = real_url.split("?_=")[0]
    logger.info("STREAM REALE (id %s): %s", cid, real_url[:80])
    return {
        "url": real_url,
        "cid": cid,
        "headers": {},
        "source": "daddylive",
        "channel_id": cid,
    }


def resolve(channel: dict, stream: dict) -> dict:
    """URL STABILE: il Val self-healing risolve l'edge al volo."""
    query = stream.get("query") or channel.get("name", "")
    if str(query).strip().isdigit():
        result = get_stream_by_id(int(str(query).strip()))
    else:
        result = get_stream(query)

    stable_url = f"{WORKER_BASE}/live?ch={result['cid']}"
    return {
        "url": stable_url,
        "provider": "DaddyLive",
        "quality": "HD",
        "headers": {},
        "extra_vlcopts": ["network-caching=15000"],
        "proxy": "direct",
        "proxy_required": False,
    }
    
