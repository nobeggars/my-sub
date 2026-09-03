import requests
import urllib.parse
import json

URL = "https://raw.githubusercontent.com/zieng2/wl/refs/heads/main/vless_universal.txt"

def build_xray_config(remarks_name, outbounds, tags):
    """Формирует готовый JSON-блок балансировщика"""
    return {
        "remarks": remarks_name,
        "dns": {
            "servers": [
                "https://8.8.8.8/dns-query",
                "https://8.8.8.8/dns-query"
            ],
            "queryStrategy": "UseIP"
        },
        "inbounds": [
            {
                "tag": "socks",
                "port": 10808,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {
                    "udp": True,
                    "auth": "noauth"
                },
                "sniffing": {
                    "enabled": True,
                    "routeOnly": True,
                    "destOverride": ["http", "tls", "quic"]
                }
            },
            {
                "tag": "http",
                "port": 10809,
                "listen": "127.0.0.1",
                "protocol": "http",
                "settings": {
                    "allowTransparent": False
                },
                "sniffing": {
                    "enabled": True,
                    "routeOnly": True,
                    "destOverride": ["http", "tls", "quic"]
                }
            }
        ],
        "log": {
            "loglevel": "warning"
        },
        "outbounds": outbounds + [
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
                    "strategy": {
                        "type": "leastPing"
                    }
                }
            ]
        },
        "observatory": {
            "enableConcurrency": True,
            "probeInterval": "1m",
            "probeUrl": "https://www.google.com/generate_204",
            "subjectSelector": tags
        }
    }

def parse_vless_url(url, index):
    """Разбирает vless:// ссылку и делает из неё outbound Xray"""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'vless':
        return None, None

    uuid = parsed.username
    address = parsed.hostname
    port = parsed.port or 443
    name = urllib.parse.unquote(parsed.fragment)
    
    qs = urllib.parse.parse_qs(parsed.query)
    def get_qs(key, default=""): return qs.get(key, [default])[0]

    security = get_qs("security", "none")
    network = get_qs("type", "tcp")
    tag = f"cand-{index:02d}"

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

    return outbound, tag, name

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
    
    # Ключевые слова для RU серверов (в нижнем регистре)
    ru_keywords = ['ru', 'russia', 'россия', 'moscow', 'st. petersburg', 'st.petersburg']
    
    ru_idx, eu_idx = 1, 1

    for line in response.text.splitlines():
        line = line.strip()
        if not line: continue

        # Проверяем, куда относится сервер, чтобы дать правильный индекс cand-XX
        name_lower = urllib.parse.unquote(urllib.parse.urlparse(line).fragment).lower()
        is_ru = any(k in name_lower for k in ru_keywords)
        
        outbound, tag, _ = parse_vless_url(line, ru_idx if is_ru else eu_idx)
        if not outbound: continue

        if is_ru:
            ru_outbounds.append(outbound)
            ru_tags.append(tag)
            ru_idx += 1
        else:
            eu_outbounds.append(outbound)
            eu_tags.append(tag)
            eu_idx += 1

    # Собираем финальные конфиги
    eu_config = build_xray_config("🇲🇦 🗽 LTE EU Авто", eu_outbounds, eu_tags)
    ru_config = build_xray_config("🇲🇦 🗽 LTE RU Авто", ru_outbounds, ru_tags)

    # Записываем всё пластом в один txt файл
    filename = "subscription_balancers.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(json.dumps(eu_config, indent=2, ensure_ascii=False))
        f.write("\n\n") # Пробел между двумя JSON-блоками
        f.write(json.dumps(ru_config, indent=2, ensure_ascii=False))

    print(f"Готово! Сохранено в {filename}.")
    print(f"Собрано EU: {len(eu_tags)}, RU: {len(ru_tags)}")

if __name__ == "__main__":
    main()

