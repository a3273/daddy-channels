"""
DaddyLive provider v2 - massima copertura contro i cambi di dominio.

Frontend (lista canali / schedule): non serve conoscere il dominio in anticipo.
1) FONTE PUBBLICA VIVA: AdguardFilters watchers.yml pubblica il mirror attuale
   del network DaddyLive ( aggiornato dalla community, oggi: thedaddy.li )
2) REDIRECT-FOLLOW: un vecchio mirror morto spesso redirecta al dominio nuovo
3) STATICI aggiornati ( thedaddy.li, strmd.st + storici )
4) BRUTE-FORCE TLD di ultimo resort ( basi note x TLD comuni )

Embed (estrazione const SRC): iframe-follow dalla pagina watch VIVA
( watch -> player -> embed ), quindi il dominio embed si scopre da solo
anche se cambia ( oggi: dembed.st ). Referer dell'embed = URL della pagina
player. Fallback su embed statici con referer frontend vivo.

edge.json: oltre a id->edge, chiave "_meta" con i domini frontend/embed
scoperti in questo run ( il Val puo' usarli come fallback vivo ).
DAZN anti-ri-numerazione: invariata ( ID diretto + scan schedule + candidati ).
Playlist: URL stabili /live?ch=<id> -> il Val risolve l'edge al volo.
"""

import re
import logging
import time
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

# ★ FRONTEND STATICI (in ordine di priorita'; la discovery li riodina comunque)
MIRRORS = [
    "https://thedaddy.li",
    "https://strmd.st",
    "https://thedaddy.pk",
    "https://dlive.sx",
    "https://thedaddy.to",
    "https://daddylives.top",
    "https://papahd.live",
    "https://dlhd.sbs",
    "https://dlhd.pk",
    "https://dlstreams.st",
]

# ★ brute-force TLD: basi note x TLD comuni (solo se tutto il resto e' morto)
BASES = ["thedaddy", "strmd", "dlive", "dlhd", "daddylive", "dlstreams", "daddyhd"]
TLDS = ["li", "to", "pk", "sx", "st", "sbs", "live", "top", "ink", "vip",
        "icu", "watch", "cool", "fun", "shop", "site", "online"]

# fonte pubblica viva: mirror attuale del network secondo AdguardFilters
WATCHERS_URL = "https://raw.githubusercontent.com/AdguardTeam/AdguardFilters/master/watchers.yml"

# ★ EMBED STATICI (il vero meccanismo e' l'iframe-follow; questi sono fallback)
EMBED_MIRRORS = [
    "https://dembed.st",
    "https://bembed.sbs",
    "https://thedaddy.pk",
    "https://thedaddy.to",
]
EMBED_PATHS = [
    "/premiumtv/daddy.php?id={cid}",
    "/daddylive/daddy.php?id={cid}",
]

# percorsi lista canali (alcuni mirror servono il .php, altri no)
LIST_PATHS = ("/24-7-channels.php", "/24-7-channels")

CANDIDATES = {
    "dazn 1": [107],
    "dazn zona 2": [105],
}

# IL VAL VAL.TOWN
WORKER_BASE = "https://simo11.val.run/daddy-stream"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DISCOVERY_PROXIES = [
    lambda u: "https://api.allorigins.win/raw?url=" + quote(u, safe=""),
    lambda u: "https://api.codetabs.com/v1/proxy?ques=" + u,
    lambda u: "https://corsproxy.io/?url=" + quote(u, safe=""),
    lambda u: "https://api.cors.lol/?url=" + quote(u, safe=""),
]

# iframe che non sono il player (pubblicita' / social)
AD_HINTS = ("doubleclick", "googlesyndication", "discord", "telegram",
            "twitter", "facebook", "adservice")

_channel_cache = None
_edge_map = {}

_state = {
    "discovered": False,  # discovery dei domini gia' fatta in questo run
    "frontend": [],       # mirror candidati ordinati (vivi in testa)
    "alive": [],          # mirror frontend confermati vivi
    "embed": [],          # origin embed scoperte
}
# catena embed scoperta in questo run, template con {cid} (fast-path 1 fetch)
_chain = {"embed": None, "referer": None}


def get_edge_map():
    """id_canale -> URL edge, piu' chiave _meta con i domini scoperti."""
    data = dict(_edge_map)
    try:
        data["_meta"] = {
            "frontend": _state["alive"][:5],
            "embed": _state["embed"][:5],
            "ts": int(time.time()),
        }
    except Exception:
        pass
    return data


def _origin(url: str) -> str:
    m = re.match(r"https?://[^/]+", url)
    return m.group(0) if m else ""


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


def _probe_frontend(mirror: str, timeout: int = 6) -> bool:
    """True se il mirror serve la lista canali 24/7."""
    try:
        r = requests.get(mirror + "/24-7-channels.php", headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            t = r.text
            return "watch.php" in t or "ID:" in t
    except Exception:
        pass
    return False


def _discover_mirrors() -> list:
    """Trova i mirror frontend vivi: watchers.yml -> redirect -> statici -> TLD."""
    candidates: list = []

    # 1) fonte pubblica community: mirror noto del network DaddyLive
    try:
        r = requests.get(WATCHERS_URL, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            pat = re.compile(
                r"last_known_mirror:\s*((?:thedaddy|strmd|dlive|dlhd|daddylive|dlstreams|daddyhd)[a-z0-9.\-]*)",
                re.IGNORECASE,
            )
            for host in pat.findall(r.text):
                cand = "https://" + host.lower()
                if cand not in candidates:
                    candidates.append(cand)
    except Exception:
        pass

    # 2) redirect-follow: un mirror morto spesso punta al dominio nuovo
    for mirror in MIRRORS:
        try:
            r = requests.get(mirror, headers=HEADERS, timeout=6, allow_redirects=True)
            org = _origin(r.url)
            if org and org not in candidates:
                candidates.append(org)
        except Exception:
            continue

    # verifica i candidati: solo chi serve davvero la lista canali
    alive = []
    for cand in candidates:
        if _probe_frontend(cand):
            alive.append(cand)
            if cand not in _state["alive"]:
                _state["alive"].append(cand)

    # 3) brute-force TLD: ultimo resort, solo se finora nulla di vivo
    if not alive:
        for base in BASES:
            for tld in TLDS:
                cand = f"https://{base}.{tld}"
                if _probe_frontend(cand, timeout=4):
                    alive.append(cand)
                    if cand not in _state["alive"]:
                        _state["alive"].append(cand)
                if len(alive) >= 2:
                    break
            if len(alive) >= 2:
                break

    # ordine finale: scoperti vivi -> scoperti -> statici
    ordered: list = []
    for m in alive + candidates + MIRRORS:
        if m not in ordered:
            ordered.append(m)
    return ordered


def _ordered_mirrors() -> list:
    if not _state["discovered"]:
        try:
            _state["frontend"] = _discover_mirrors()
        except Exception as e:
            logger.warning("DaddyLive: discovery fallita (%s), uso i mirror statici", e)
            _state["frontend"] = list(MIRRORS)
        _state["discovered"] = True
    return _state["frontend"]


def _mark_alive(mirror: str):
    if mirror not in _state["alive"]:
        _state["alive"].append(mirror)
    lst = _state["frontend"]
    if lst and lst[0] == mirror:
        return
    if mirror in lst:
        lst.remove(mirror)
    lst.insert(0, mirror)


def _parse_datatitle(html: str) -> dict:
    channels: dict = {}
    for m in re.finditer(r'href="(?:[^"]*?/)?watch\.php\?id=(\d+)"[^>]*data-title="([^"]+)"', html, re.IGNORECASE):
        name = m.group(2).strip()
        if name:
            channels.setdefault(name, int(m.group(1)))
    return channels


def _parse_textids(html: str) -> dict:
    """Layout attuale: card 'Nome' + testo 'ID: N'."""
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "\n", text)
    channels: dict = {}
    for m in re.finditer(r"([^\n]{2,60})\n+\s*ID:\s*(\d+)", text):
        name = re.sub(r"\s+", " ", m.group(1)).strip(" -\t")
        if name and not re.fullmatch(r"[\d\s\-:]+", name):
            channels.setdefault(name, int(m.group(2)))
    return channels


def _parse_href(html: str) -> dict:
    """Fallback: nome = primo testo dopo il link watch."""
    channels: dict = {}
    for m in re.finditer(r'href="(?:[^"]*?/)?watch\.php\?id=(\d+)"(.{0,300}?)>\s*([^<>]{2,60})<', html, re.IGNORECASE | re.DOTALL):
        name = re.sub(r"\s+", " ", m.group(3)).strip()
        if name and not re.fullmatch(r"[\d\s\-:]+", name):
            channels.setdefault(name, int(m.group(1)))
    return channels


def _parse_channels(html: str) -> dict:
    best: dict = {}
    for parse in (_parse_datatitle, _parse_textids, _parse_href):
        try:
            got = parse(html)
        except Exception:
            got = {}
        if len(got) > len(best):
            best = got
        if len(best) >= 5:
            break
    return best


def fetch_channel_list() -> dict:
    global _channel_cache
    if _channel_cache is not None:
        return _channel_cache
    last_err = ""
    for mirror in _ordered_mirrors()[:8]:
        for path in LIST_PATHS:
            try:
                html = _fetch(mirror + path, timeout=15).text
                channels = _parse_channels(html)
                if channels:
                    logger.info("DaddyLive: %d canali via %s%s", len(channels), mirror, path)
                    _mark_alive(mirror)
                    _channel_cache = channels
                    return channels
            except Exception as e:
                last_err = f"{mirror}{path}: {e}"
    raise RuntimeError(f"DaddyLive: nessun mirror raggiungibile. Ultimo: {last_err}")


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


def _schedule_dazn_ids() -> dict:
    """Scoperta automatica ID DAZN dalla schedule: i bottoni 'DAZN 1 IT' /
    'DAZN ZONA 2 IT' linkano a watch.php?id=N."""
    ids: dict = {"dazn 1": [], "dazn zona 2": []}
    for mirror in _ordered_mirrors()[:3]:
        for path in ("/index.php", "/"):
            try:
                html = _fetch(mirror + path, timeout=15).text
            except Exception:
                continue
            for m in re.finditer(r'href="(?:[^"]*?/)?watch\.php\?id=(\d+)"[^>]*>\s*([^<]{2,40})', html, re.IGNORECASE):
                cid = int(m.group(1))
                label = m.group(2).strip().lower()
                if "dazn" not in label:
                    continue
                if "zona" in label and "2" in label:
                    if cid not in ids["dazn zona 2"]:
                        ids["dazn zona 2"].append(cid)
                elif "zona" not in label and re.search(r"\b1\b", label):
                    if cid not in ids["dazn 1"]:
                        ids["dazn 1"].append(cid)
            if ids["dazn 1"] or ids["dazn zona 2"]:
                logger.info("DaddyLive: schedule scan DAZN ids=%s via %s", ids, mirror)
                break
        if ids["dazn 1"] or ids["dazn zona 2"]:
            break
    return ids


def _iframes(html: str, base: str) -> list:
    urls: list = []
    for m in re.finditer(r'<iframe[^>]+src="([^"]+)"', html, re.IGNORECASE):
        src = m.group(1).strip().replace("\\/", "/")
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = base.rstrip("/") + src
        low = src.lower()
        if src.startswith("http") and not any(a in low for a in AD_HINTS):
            if src not in urls:
                urls.append(src)
    return urls


def _find_src(html: str):
    m = re.search(r'const\s+SRC\s*=\s*"([^"]+?\.m3u8[^"]*)"', html)
    if m:
        return m.group(1)
    for cand in re.findall(r"https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*", html)[:5]:
        if not any(a in cand.lower() for a in AD_HINTS):
            return cand
    return None


def _embed_src(url: str, referer: str):
    return _find_src(_fetch(url, referer=referer, must_contain=".m3u8", timeout=10).text)


def _remember_embed(url: str):
    org = _origin(url)
    if org and org not in _state["embed"]:
        _state["embed"].append(org)


def _templatize(url: str, cid: int) -> str:
    s = str(cid)
    return url.replace("id=" + s, "id={cid}").replace("-" + s, "-{cid}").replace("=" + s, "={cid}")


def _stamp(src: str) -> str:
    sep = "&" if "?" in src else "?"
    return f"{src}{sep}_={int(time.time() * 1000)}"


def _extract_real_stream(cid: int) -> str:
    """iframe-follow: watch -> player -> embed. Il dominio embed si scopre
    dalla pagina viva; fallback embed statici con referer frontend vivo."""
    last_err = ""

    # fast path: catena embed gia' scoperta in questo run (1 solo fetch)
    if _chain["embed"]:
        try:
            src = _embed_src(_chain["embed"].format(cid=cid), _chain["referer"].format(cid=cid))
            if src:
                return _stamp(src)
        except Exception as e:
            last_err = f"chain: {e}"
        _chain["embed"] = None  # catena morta: full rediscovery

    for mirror in _ordered_mirrors()[:4]:
        # 1) iframe-follow dalla pagina watch viva
        for entry in (f"{mirror}/watch.php?id={cid}", f"{mirror}/stream/stream-{cid}.php"):
            try:
                page = _fetch(entry, timeout=12).text
            except Exception as e:
                last_err = f"{entry}: {e}"
                continue
            src = _find_src(page)
            if src:
                _remember_embed(entry)
                return _stamp(src)
            for u1 in _iframes(page, entry)[:4]:
                try:
                    h1 = _fetch(u1, referer=entry, timeout=10).text
                except Exception as e:
                    last_err = f"{u1}: {e}"
                    continue
                src = _find_src(h1)
                if src:
                    _remember_embed(u1)
                    return _stamp(src)
                for u2 in _iframes(h1, u1)[:4]:
                    try:
                        h2 = _fetch(u2, referer=u1, timeout=10).text
                    except Exception as e:
                        last_err = f"{u2}: {e}"
                        continue
                    src = _find_src(h2)
                    if src:
                        _remember_embed(u2)
                        if str(cid) in u2:
                            _chain["embed"] = _templatize(u2, cid)
                            _chain["referer"] = _templatize(u1, cid)
                        return _stamp(src)
        # 2) fallback statico: embed noti, referer = frontend vivo (non l'host embed)
        for host in EMBED_MIRRORS:
            for path in EMBED_PATHS:
                try:
                    src = _embed_src(host + path.format(cid=cid), f"{mirror}/stream/stream-{cid}.php")
                except Exception as e:
                    last_err = f"{host}{path}: {e}"
                    continue
                if src:
                    _remember_embed(host + path)
                    _chain["embed"] = host + path
                    _chain["referer"] = f"{mirror}/stream/stream-{{cid}}.php"
                    return _stamp(src)

    raise RuntimeError(f"Stream non trovato per canale {cid}. Ultimo: {last_err}")


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
    """URL STABILE: il Val self-healing risolve l'edge al volo.
    - query numerica = ID diretto (es. DAZN 107/105); se l'ID muore:
      recupero automatico via scan schedule + candidati
    - query testuale = matching per nome sulla lista 24/7
    """
    query = (stream.get("query") or channel.get("name", "")).strip()
    result = None

    if query.isdigit():
        try:
            result = get_stream_by_id(int(query))
        except Exception:
            sched = _schedule_dazn_ids()
            pool: list = []
            for v in CANDIDATES.values():
                pool.extend(v)
            for v in sched.values():
                pool.extend(v)
            for cid in pool:
                try:
                    result = get_stream_by_id(cid)
                    logger.info("DaddyLive: id %s morto, recuperato id %s", query, cid)
                    break
                except Exception:
                    continue
            if result is None:
                raise RuntimeError(f"DaddyLive: id {query} morto e nessun candidato vivo")
    else:
        try:
            result = get_stream(query)
        except ValueError:
            sched = _schedule_dazn_ids()
            cands = list(CANDIDATES.get(query.lower(), [])) + sched.get(query.lower(), [])
            for cid in cands:
                try:
                    result = get_stream_by_id(cid)
                    logger.info("DaddyLive: '%s' trovato via candidato id %s", query, cid)
                    break
                except Exception:
                    continue
            if result is None:
                raise

    stable_url = f"{WORKER_BASE}/live?ch={result['cid']}"
    return {
        "url": stable_url,
        "provider": "DaddyLive",
        "quality": "HD",
        "headers": {},
        "extra_vlcopts": ["network-caching=2000"],
        "proxy": "direct",
        "proxy_required": False,
    }
# ███ FINE FILE daddy.py v2 ███
