"""
Provider DaddyLive - Usa il resolver esterno per streaming IPTV compatibile.

Il resolver gestisce automaticamente:
- Estrazione m3u8 da thedaddy.li → dembed.st
- Riscrittura della playlist con proxy dei segmenti (/seg)
- Gestione dei token dinamici e header Referer/Origin corretti
- Cache edge per ridurre drasticamente le richieste all'origine

VLC/Televizo vedono solo URL stabili del resolver, garantendo 
riproduzione fluida senza blocchi IP-bound.
"""

import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)

# Base URL del resolver che gestisce tutto il lavoro sporco
# Questo worker fa da proxy per i segmenti, risparmiando richieste dirette 
# e aggirando le protezioni anti-hotlinking di dembed.st
RESOLVER_BASE = "https://resolvers.simone-scorrano-2011.workers.dev/daddy"

def resolve(channel, stream):
    """
    Risolve uno stream DaddyLive usando il resolver esterno.
    
    Args:
        channel: dict con info canale (name, logo, group, ...)
        stream: dict con info stream (query = ID numerico DaddyLive)
    
    Returns:
        dict con:
            - url: URL stabile del resolver (m3u8 con segmenti proxyati)
            - provider: nome provider
            - quality: qualità stimata
            - headers: headers per VLC (vuoti, il resolver gestisce tutto)
            - extra_vlcopts: opzioni VLC ottimizzate per stabilità
    
    Raises:
        ValueError: se la query (ID canale) è mancante
    """
    query = stream.get("query") or ""
    if not query:
        raise ValueError("DaddyLive: query (ID canale) mancante nello stream")
    
    # Costruisci URL stabile del resolver
    # Il resolver accetta l'ID numerico (es. 577) o lo slug (es. sky-sport-f1)
    stable_url = f"{RESOLVER_BASE}?ch={quote(str(query))}"
    
    logger.info(
        "DaddyLive: %s (ID %s) -> %s", 
        channel.get("name", "Unknown"), 
        query, 
        stable_url
    )
    
    return {
        "url": stable_url,
        "provider": "DaddyLive",
        "quality": "HD",
        "headers": {},
        # network-caching alto per compensare eventuale latenza del proxy
        # http-reconnect per recupero automatico in caso di micro-interruzioni
        "extra_vlcopts": [
            "network-caching=15000",
            "http-reconnect",
            "http-user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ],
    }
