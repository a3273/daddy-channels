"""Provider DaddyLive - delega la risoluzione al worker Cloudflare."""
import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)

# URL del worker Cloudflare che risolve DaddyLive
RESOLVER_BASE = "https://resolvers.simone-scorrano-2011.workers.dev/daddy"

def resolve(channel, stream):
    query = stream.get("query") or ""
    if not query:
        raise ValueError("DaddyLive: query mancante")

    stable_url = f"{RESOLVER_BASE}?ch={quote(query)}"
    logger.info("DaddyLive: %s -> %s", query, stable_url)

    return {
        "url": stable_url,
        "provider": "DaddyLive",
        "quality": "HD",
        "headers": {},
        "extra_vlcopts": ["network-caching=15000"],
    }
