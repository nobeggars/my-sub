import requests
import urllib.parse
import json

URL = "https://raw.githubusercontent.com/zieng2/wl/refs/heads/main/vless_universal.txt"

def parse_vless_url(url, prefix, index):
    """Разбирает vless:// ссылку и генерирует уникальный тег"""
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
    # Тег будет выглядеть как cand-eu-01 или cand-ru-01
    tag = f"cand-{prefix}-{index:02d}"

    outbound = {
        "tag": tag,
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": address,
                "port": int(port),
                "users": [{
                    "id": uuid,
                    "encryption": get_qs("encryption", "none"),
                    "flow": get_qs("flow", "")
                }]
            }]
        },
        "streamSettings": {
            "network": network,
            "security": security
        }
    }

    if security == "reality":
        outbound["streamSettings"]["realitySettings"] = {
            "serverName": get_qs("sni"),
            "publicKey": get_qs("pbk"),
            "shortId": get_qs("sid"),
            "fingerprint": get_qs("fp", "chrome"),
            "show": False
        }
        if network == "tcp":
            outbound["streamSettings"]["tcpSettings"] = {}
            
    elif security == "tls":
        outbound["streamSettings"]["tlsSettings"] = {
            "serverName": get_qs("sni"),
            "show": False,
            "fingerprint": get_qs("fp", "chrome")
        }

    if network == "grpc":
        outbound["streamSettings"]["grpcSettings"] = {
            "serviceName": get_qs("serviceName"),
            "multiMode": True
        }
    elif network == "ws":
        outbound["streamSettings"]["wsSettings"] = {
            "path": get_qs("path", "/")
        }
        host = get_qs("host")
        if host:
            outbound["streamSettings"]["wsSettings"]["headers"] = {"Host": host}

    return outbound, tag

def main():
    print("Качаем подписку...")
    try:
        response = requests.get(URL, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Ошибка при скачивании: {e}")
        return

    ru_outbounds, eu_outbounds = [], []
    ru_tags, eu_tags = [], []
    
    ru_keywords = ['ru', 'russia', 'россия', 'moscow', 'st. petersburg', 'st.petersburg']
    ru_idx, eu_idx = 1, 1

    for line in response.text.splitlines():
        line = line.strip()
        if not line: continue

        name_lower = urllib.parse.unquote(urllib.parse.urlparse(line).fragment).lower()
        is_ru = any(k in name_lower for k in ru_keywords)
        
        prefix = "ru" if is_ru else "eu"
        idx = ru_idx if is_ru else eu_idx
        
        outbound, tag = parse_vless_url(line, prefix, idx)
        if not outbound: continue

        if is_ru:
            ru_outbounds.append(outbound)
            ru_tags.append(tag)
            ru_idx += 1
        else:
            eu_outbounds.append(outbound)
            eu_tags.append(tag)
            eu_idx += 1

    # Собираем ЕДИНЫЙ валидный JSON-конфиг
    unified_config = {
        "remarks": "🇲🇦 🗽 LTE Авто (EU + RU балансировщик)",
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
        # Впихиваем все сервера в один список
        "outbounds": eu_outbounds + ru_outbounds + [
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"}
        ],
        "routing": {
            "domainMatcher": "hybrid",
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {
                    "type": "field",
                    "protocol": ["bittorrent"],
                    "outboundTag": "direct"
                },
                {
                    # Направляем русские домены и сервисы в RU балансировщик
                    "type": "field",
                    "domain": [
                        "regexp:.*\\.ru$", "max.ru", "domain:2gis.ru", "domain:ads.x5.ru",
                        "domain:2gis.com", "domain:vk.com", "domain:ya.ru", "domain:yandex.ru",
                        "domain:mail.ru", "domain:gosuslugi.ru", "domain:rutube.ru"
                    ],
                    "balancerTag": "ru_balancer"
                },
                {
                    # Весь остальной интернет идет через EU балансировщик
                    "type": "field",
                    "network": "tcp,udp",
                    "balancerTag": "eu_balancer"
                }
            ],
            "balancers": [
                {
                    "tag": "eu_balancer",
                    "selector": eu_tags,
                    "strategy": {"type": "leastPing"}
                },
                {
                    "tag": "ru_balancer",
                    "selector": ru_tags,
                    "strategy": {"type": "leastPing"}
                }
            ]
        },
        "observatory": {
            "enableConcurrency": True,
            "probeInterval": "1m",
            "probeUrl": "https://www.google.com/generate_204",
            "subjectSelector": eu_tags + ru_tags
        }
    }

    filename = "subscription.txt"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(unified_config, f, indent=2, ensure_ascii=False)

    print(f"Готово! Сохранено в {filename}.")
    print(f"В конфиг зашито серверов EU: {len(eu_tags)}, RU: {len(ru_tags)}")

if __name__ == "__main__":
    main()

