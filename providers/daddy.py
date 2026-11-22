"""
Provider DaddyLive - Risolve stream direttamente da thedaddy.li
"""

import re
import requests
from urllib.parse import quote

# Dominio principale di DaddyLive
DADDY_BASE = "https://thedaddy.li"

def resolve(channel, stream):
    """
    Risolve lo stream per un canale DaddyLive.
    
    Args:
        channel: Dizionario con info canale (name, logo, etc)
        stream: Dizionario con info stream (query = ID canale)
    
    Returns:
        dict con url, provider, quality, headers
    """
    query = stream.get("query") or ""
    if not query:
        raise ValueError("DaddyLive: query (ID canale) mancante")

    # Costruisci URL della pagina player
    player_url = f"{DADDY_BASE}/cast/stream-{query}.php"
    
    try:
        # Scarica la pagina player
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        
        response = requests.get(player_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        html = response.text
        
        # Cerca URL m3u8 nell'HTML
        # Pattern 1: URL m3u8 completo (es. https://edge.wedd48c.top/premium577/index.m3u8)
        m3u8_patterns = [
            r'https?://[^"\'<>\s]+\.m3u8[^"\'<>\s]*',  # URL completo
            r'["\']([^"\']*\.m3u8[^"\']*)["\']',        # Tra virgolette
            r'src\s*=\s*["\']([^"\']*\.m3u8[^"\']*)["\']',  # Attributo src
            r'url\s*[:=]\s*["\']([^"\']*\.m3u8[^"\']*)["\']',  # Variabile url
            r'file\s*[:=]\s*["\']([^"\']*\.m3u8[^"\']*)["\']',  # Variabile file
            r'source\s*[:=]\s*["\']([^"\']*\.m3u8[^"\']*)["\']',  # Variabile source
        ]
        
        m3u8_url = None
        for pattern in m3u8_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                # Estrai l'URL (potrebbe essere nel gruppo 1 se c'erano virgolette)
                url = match.group(1) if match.lastindex else match.group(0)
                # Pulisci l'URL
                url = url.strip('\'"')
                if url.startswith('http'):
                    m3u8_url = url
                    break
        
        if not m3u8_url:
            # Fallback: usa direttamente la pagina player
            # Alcuni player possono gestire pagine HTML con video embedded
            m3u8_url = player_url
        
        return {
            "url": m3u8_url,
            "provider": "DaddyLive",
            "quality": "HD",
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": DADDY_BASE
            },
            "extra_vlcopts": [
                "network-caching=15000",
                f"http-referrer={DADDY_BASE}"
            ],
        }
        
    except requests.exceptions.RequestException as e:
        raise ValueError(f"DaddyLive: errore richiesta HTTP: {e}")
    except Exception as e:
        raise ValueError(f"DaddyLive: errore risoluzione: {e}")
