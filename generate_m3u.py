"""
Generatore playlist M3U - architettura provider.
Legge channels.json, carica providers.<nome> per ogni stream,
risolve e scrive playlist.m3u con URL diretti.
"""

import importlib
import json
from pathlib import Path

CHANNELS_FILE = Path("channels.json")
PLAYLIST_FILE = Path("playlist.m3u")
STATUS_FILE = Path("status.json")

def clean(value) -> str:
    return str(value or "").strip()

def m3u_escape(value: str) -> str:
    return clean(value).replace('"', "'")

def load_config() -> dict:
    if not CHANNELS_FILE.exists():
        raise FileNotFoundError(f"File non trovato: {CHANNELS_FILE}")
    with CHANNELS_FILE.open("r", encoding="utf-8-sig") as handle:
        raw = handle.read()
    raw = raw.lstrip("\ufeff").strip()
    if not raw:
        raise ValueError(f"{CHANNELS_FILE} è vuoto")
    return json.loads(raw)

def load_provider(name: str):
    module_name = f"providers.{clean(name).lower()}"
    return importlib.import_module(module_name)

def write_status(status: dict):
    with STATUS_FILE.open("w", encoding="utf-8") as handle:
        json.dump(status, handle, indent=2, ensure_ascii=False)

def main():
    config = load_config()
    channels = config.get("channels", [])

    if not isinstance(channels, list):
        raise ValueError('"channels" deve essere una lista')

    output = ["#EXTM3U"]

    status = {
        "summary": {
            "channels_total": 0,
            "channels_enabled": 0,
            "streams_total": 0,
            "streams_generated": 0,
            "streams_failed": 0
        },
        "channels": {}
    }

    for channel in channels:
        if not isinstance(channel, dict):
            continue

        channel_name = clean(channel.get("name"))
        if not channel_name:
            continue

        status["summary"]["channels_total"] += 1

        if channel.get("enabled", True) is not True:
            status["channels"][channel_name] = {"enabled": False, "streams": []}
            continue

        status["summary"]["channels_enabled"] += 1

        streams = channel.get("streams", [])
        if not isinstance(streams, list):
            streams = []

        channel_status = {"enabled": True, "streams": []}
        resolved_streams = []

        for stream in streams:
            if not isinstance(stream, dict):
                continue
            if stream.get("enabled", True) is not True:
                continue

            status["summary"]["streams_total"] += 1

            stream_name = clean(stream.get("name"))
            provider_name = clean(stream.get("provider")).lower()
            source_url = clean(stream.get("url"))

            stream_status = {
                "name": stream_name,
                "provider": provider_name,
                "priority": stream.get("priority", 999),
                "source_url_configured": bool(source_url)
            }

            try:
                print(f"[RESOLVE] {channel_name} / {stream_name}")

                if provider_name:
                    provider = load_provider(provider_name)
                    result = provider.resolve(channel, stream)
                elif source_url:
                    result = {
                        "url": source_url,
                        "provider": stream_name or "Direct",
                        "quality": "HD",
                        "headers": {}
                    }
                else:
                    raise ValueError("provider mancante e URL sorgente vuoto")

                if not isinstance(result, dict):
                    raise ValueError("Il provider non ha restituito un dict")

                resolved_url = clean(result.get("url"))
                print(f"[RESOLVE RESULT] {channel_name} / {stream_name} -> {bool(resolved_url)}")

                if not resolved_url:
                    raise ValueError("Il provider non ha restituito un URL")

                priority = int(stream.get("priority", result.get("priority", 999)))

                resolved_streams.append({
                    "result": result,
                    "priority": priority,
                    "url": resolved_url
                })

                stream_status.update({
                    "status": "resolved",
                    "url": resolved_url
                })

                status["summary"]["streams_generated"] += 1

            except Exception as exc:
                print(f"[RESOLVE ERROR] {channel_name} / {stream_name}: {exc}")
                stream_status["status"] = "error"
                stream_status["error"] = str(exc)
                status["summary"]["streams_failed"] += 1

            channel_status["streams"].append(stream_status)

        resolved_streams.sort(key=lambda item: item["priority"])
        seen = set()

        for item in resolved_streams:
            result = item["result"]
            stream_url = item["url"]

            stream_key = (channel_name, stream_url)
            if stream_key in seen:
                continue
            seen.add(stream_key)

            tvg_id = m3u_escape(channel.get("tvg_id", channel_name))
            tvg_name = m3u_escape(channel_name)
            tvg_logo = m3u_escape(channel.get("logo", ""))
            group = m3u_escape(channel.get("group", "Live TV"))
            label = channel_name

            output.append(
                '#EXTINF:-1 '
                f'tvg-id="{tvg_id}" '
                f'tvg-name="{tvg_name}" '
                f'tvg-logo="{tvg_logo}" '
                f'group-title="{group}",'
                f'{m3u_escape(label)}'
            )

            headers = result.get("headers", {})
            if isinstance(headers, dict):
                user_agent = clean(headers.get("User-Agent"))
                if user_agent:
                    output.append("#EXTVLCOPT:http-user-agent=" + user_agent)

            for opt in result.get("extra_vlcopts", []):
                output.append(f"#EXTVLCOPT:{clean(opt)}")

            output.append(stream_url)

        status["channels"][channel_name] = channel_status

    with PLAYLIST_FILE.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(output) + "\n")

    write_status(status)

    print("----------------------------------------")
    print("M3U generation completed")
    print(f"Channels: {status['summary']['channels_enabled']}/{status['summary']['channels_total']}")
    print(f"Streams generated: {status['summary']['streams_generated']}")
    print(f"Streams failed: {status['summary']['streams_failed']}")
    print(f"Playlist: {PLAYLIST_FILE}")
    print(f"Status: {STATUS_FILE}")
    print("----------------------------------------")

if __name__ == "__main__":
    main()
