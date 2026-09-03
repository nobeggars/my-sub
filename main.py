import requests
import urllib.parse
import json

URL = "https://raw.githubusercontent.com/zieng2/wl/refs/heads/main/vless_universal.txt"

def build_xray_config(remarks_name, outbounds, tags):
    """Строит структуру одного сервера-балансировщика"""
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
            "probeInterval": "30s", # Пинг каждые 30 секунд
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

    # Защита от пустых массивов
    if not ru_tags: ru_tags = ["direct"]
    if not eu_tags: eu_tags = ["direct"]

    # 1. Формируем конфиг для EU
    eu_config = build_xray_config("🇲🇦 🗽 LTE EU Авто", eu_outbounds, eu_tags)
    
    # 2. Формируем конфиг для RU
    ru_config = build_xray_config("🇲🇦 🗽 LTE RU Авто", ru_outbounds, ru_tags)

    # 3. Делаем массив из 2 серверов специально для Happ! (Квадратные скобки)
    happ_json_array = [eu_config, ru_config]

    # Сохраняем в файл
    filename = "subscription.txt"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(happ_json_array, f, indent=2, ensure_ascii=False)

    print("Успешно сформирован массив из 2 балансировщиков для Happ!")

if __name__ == "__main__":
    main()
