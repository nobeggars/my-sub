import requests
import urllib.parse
import json

URL = "https://raw.githubusercontent.com/zieng2/wl/refs/heads/main/vless_universal.txt"
CHUNK_SIZE = 20  # Количество серверов в одном балансировщике

def build_xray_config(remarks_name, outbounds, tags):
    """Строит структуру одного сервера-балансировщика"""
    # Если список пустой, добавляем заглушку, чтобы Xray не крашился
    if not tags:
        tags = ["direct"]

    return {
        "remarks": remarks_name,
        "dns": {
            "servers": ["https://8.8.8.8/dns-query", "https://8.8.8.8/dns-query"],
            "queryStrategy": "UseIP"
        },
        "inbounds": [
            {
                "tag": "socks",
                "port": 10808,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {"udp": True, "auth": "noauth"},
                "sniffing": {"enabled": True, "routeOnly": True, "destOverride": ["http", "tls", "quic"]}
            },
            {
                "tag": "http",
                "port": 10809,
                "listen": "127.0.0.1",
                "protocol": "http",
                "settings": {"allowTransparent": False},
                "sniffing": {"enabled": True, "routeOnly": True, "destOverride": ["http", "tls", "quic"]}
            }
        ],
        "log": {"loglevel": "warning"},
        "outbounds": outbounds + [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"}
        ],
        "routing": {
            "domainMatcher": "hybrid",
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {"type": "field", "protocol": ["bittorrent"], "outboundTag": "direct"},
                {
                    "type": "field",
                    "domain": [
                        "max.ru", "domain:2gis.ru", "domain:ads.x5.ru", "domain:2gis.com",
                        "domain:vk.com", "domain:vk.ru", "domain:ya.ru", "domain:yandex.ru",
                        "domain:mail.ru", "domain:gosuslugi.ru", "domain:rutube.ru"
                    ],
                    "outboundTag": "direct"
                },
                {
                    "type": "field",
                    "inboundTag": ["socks", "http"],
                    "network": "tcp,udp",
                    "balancerTag": "best_ping_balancer"
                }
            ],
            "balancers": [
                {
                    "tag": "best_ping_balancer",
                    "selector": tags,
                    "strategy": {"type": "leastPing"}
                }
            ]
        },
        "observatory": {
            "enableConcurrency": True,
            "probeInterval": "30s",
            "probeUrl": "https://www.google.com/generate_204",
            "subjectSelector": tags
        }
    }

def parse_vless_url(url, index):
    """Разбирает одну ссылку VLESS в объект outbound"""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'vless':
        return None, None

    uuid = parsed.username
    address = parsed.hostname
    port = parsed.port or 443
    
    qs = urllib.parse.parse_qs(parsed.query)
    def get_qs(key, default=""): return qs.get(key, [default])[0]

    security = get_qs("security", "none")
    network = get_qs("type", "tcp")
    tag = f"cand-{index:02d}"

    user = {
        "id": uuid,
        "encryption": get_qs("encryption", "none")
    }
    flow = get_qs("flow")
    if flow:
        user["flow"] = flow

    outbound = {
        "tag": tag,
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": address,
                "port": int(port),
                "users": [user]
            }]
        },
        "streamSettings": {
            "network": network,
            "security": security
        }
    }

    if security == "reality":
        reality_settings = {
            "serverName": get_qs("sni"),
            "publicKey": get_qs("pbk"),
            "fingerprint": get_qs("fp", "chrome")
        }
        sid = get_qs("sid")
        if sid:
            reality_settings["shortId"] = sid
        outbound["streamSettings"]["realitySettings"] = reality_settings
            
    elif security == "tls":
        outbound["streamSettings"]["tlsSettings"] = {
            "serverName": get_qs("sni"),
            "fingerprint": get_qs("fp", "chrome")
        }

    if network == "grpc":
        outbound["streamSettings"]["grpcSettings"] = {
            "serviceName": get_qs("serviceName"),
            "multiMode": True
        }
    elif network == "ws":
        ws_settings = {"path": get_qs("path", "/")}
        host = get_qs("host")
        if host:
            ws_settings["headers"] = {"Host": host}
        outbound["streamSettings"]["wsSettings"] = ws_settings

    return outbound, tag

def main():
    try:
        response = requests.get(URL, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Ошибка скачивания: {e}")
        return

    ru_outbounds, eu_outbounds = [], []
    ru_tags, eu_tags = [], []
    
    ru_keywords = ['ru', 'russia', 'россия', 'moscow', 'st. petersburg', 'st.petersburg']
    ru_idx, eu_idx = 1, 1

    # Собираем все сервера в общие списки
    for line in response.text.splitlines():
        line = line.strip()
        if not line: continue

        name_lower = urllib.parse.unquote(urllib.parse.urlparse(line).fragment).lower()
        is_ru = any(k in name_lower for k in ru_keywords)
        
        idx = ru_idx if is_ru else eu_idx
        outbound, tag = parse_vless_url(line, idx)
        if not outbound: continue

        if is_ru:
            ru_outbounds.append(outbound)
            ru_tags.append(tag)
            ru_idx += 1
        else:
            eu_outbounds.append(outbound)
            eu_tags.append(tag)
            eu_idx += 1

    happ_json_array = []

    # Нарезаем список EU на куски по CHUNK_SIZE (20 штук)
    eu_outbound_chunks = [eu_outbounds[i:i + CHUNK_SIZE] for i in range(0, len(eu_outbounds), CHUNK_SIZE)]
    eu_tags_chunks = [eu_tags[i:i + CHUNK_SIZE] for i in range(0, len(eu_tags), CHUNK_SIZE)]

    # Создаем отдельные профили для каждого куска EU
    for i, (outbounds_chunk, tags_chunk) in enumerate(zip(eu_outbound_chunks, eu_tags_chunks), 1):
        config_name = f"🇲🇦 🗽 LTE EU {i} | Авто"
        happ_json_array.append(build_xray_config(config_name, outbounds_chunk, tags_chunk))

    # Добавляем RU профиль (целиком)
    if ru_outbounds:
        happ_json_array.append(build_xray_config("🇲🇦 🗽 LTE RU Авто", ru_outbounds, ru_tags))

    # Сохраняем итоговый массив
    filename = "subscription.txt"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(happ_json_array, f, indent=2, ensure_ascii=False)

    print(f"Успешно сформировано балансировщиков EU: {len(eu_outbound_chunks)}, RU: 1")

if __name__ == "__main__":
    main()

