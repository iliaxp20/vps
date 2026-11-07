#!/usr/bin/env python3
"""
Emergency Relay VPN Deployer (Iran & Foreign Dual-Server Architecture)
Designed for extreme censorship and national intranet (اینترنت ملی) situations.
100% Domestic mirror deployment on Iran server (mirror.iranserver.com & docker.iranserver.com).
Zero external/foreign service dependencies for the Iran server.
"""

import os
import sys
import uuid
import secrets
import tempfile
import time
from pathlib import Path
import paramiko

BASE_DIR = Path(__file__).resolve().parent

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_input(prompt, default=""):
    if default:
        res = input(f"{prompt} [{default}]: ").strip()
        return res if res else default
    return input(f"{prompt}: ").strip()

def create_ssh_client(host, port, user, password=None, key_path=None):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[*] Connecting to {host}:{port} as {user}...")
    try:
        if key_path and os.path.exists(key_path):
            client.connect(host, port=int(port), username=user, key_filename=key_path, timeout=15)
        else:
            client.connect(host, port=int(port), username=user, password=password, timeout=15)
        print(f"[+] Connected to {host} successfully.")
        return client
    except Exception as e:
        print(f"[-] Connection failed to {host}: {e}")
        return None

def exec_cmd(client, cmd, check_err=False):
    stdin, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='ignore')
    err = stderr.read().decode('utf-8', errors='ignore')
    code = stdout.channel.recv_exit_status()
    if check_err and code != 0:
        print(f"[-] Error running: {cmd}\n{err}")
    return code, out, err

def setup_iran_server_environment(client):
    """
    Ensures 100% domestic operations on Iran Server.
    Uses mirror.iranserver.com for APT and docker.iranserver.com for Docker Hub.
    ZERO foreign connections required!
    """
    print("[*] [ایران] اعمال میرورهای ۱۰۰٪ داخلی ایران‌سرور (mirror.iranserver.com)...")
    
    # Update APT to IranServer mirror (works on Ubuntu 20.04, 22.04, 24.04)
    iran_apt_script = """
if [ -f /etc/apt/sources.list ]; then
    cp /etc/apt/sources.list /etc/apt/sources.list.bak 2>/dev/null || true
    sed -i -E 's|https?://[a-zA-Z0-9.-]+/ubuntu/?|http://mirror.iranserver.com/ubuntu/|g' /etc/apt/sources.list
fi
if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
    cp /etc/apt/sources.list.d/ubuntu.sources /etc/apt/sources.list.d/ubuntu.sources.bak 2>/dev/null || true
    sed -i -E 's|https?://[a-zA-Z0-9.-]+/ubuntu/?|http://mirror.iranserver.com/ubuntu/|g' /etc/apt/sources.list.d/ubuntu.sources
fi
"""
    exec_cmd(client, iran_apt_script)

    # Check Docker
    code, out, _ = exec_cmd(client, "docker --version && docker compose version")
    if code != 0:
        print("[*] [ایران] نصب داکر از طریق مخازن داخلی ایران‌سرور...")
        exec_cmd(client, "DEBIAN_FRONTEND=noninteractive apt-get update -y && DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 openssl")
        exec_cmd(client, "systemctl enable --now docker")

    # Configure Docker daemon with IranServer & ArvanCloud registry mirrors
    print("[*] [ایران] تنظیم رجیستری میرورهای داخلی داکر (docker.iranserver.com)...")
    daemon_json = """{
  "registry-mirrors": [
    "https://docker.iranserver.com",
    "https://docker.arvancloud.ir"
  ]
}"""
    sftp = client.open_sftp()
    with sftp.file('/tmp/daemon.json', 'w') as f:
        f.write(daemon_json)
    sftp.close()
    exec_cmd(client, "mkdir -p /etc/docker && cp /tmp/daemon.json /etc/docker/daemon.json && systemctl restart docker")

def setup_foreign_server_environment(client):
    print("[*] [خارج] بررسی داکر و آماده‌سازی مخازن سرور خارج...")
    code, out, _ = exec_cmd(client, "docker --version && docker compose version")
    if code != 0:
        print("[*] [خارج] در حال نصب داکر...")
        exec_cmd(client, "curl -fsSL https://get.docker.com | sh", check_err=True)
        exec_cmd(client, "systemctl enable --now docker")

def upload_directory(sftp, local_dir, remote_dir):
    try:
        sftp.mkdir(remote_dir)
    except IOError:
        pass

    for item in os.listdir(local_dir):
        l_path = os.path.join(local_dir, item)
        r_path = f"{remote_dir}/{item}".replace("//", "/")
        if os.path.isdir(l_path):
            upload_directory(sftp, l_path, r_path)
        else:
            sftp.put(l_path, r_path)

def sync_images_if_needed(client_foreign, client_iran):
    """
    Fail-safe: In case Iran server cannot pull an image from domestic cache
    during total international isolation, pull on Foreign and pipe to Iran.
    """
    print("[*] تست و اعتبارسنجی ایمیج‌ها روی سرور ایران...")
    code, _, _ = exec_cmd(client_iran, "docker pull nginx:alpine && docker pull rapiz1/rathole:latest")
    if code != 0:
        print("[!] میرور ایران به اینترنت دسترسی ندارد. انتقال مستقیم ایمیج‌ها از سرور خارج به سرور ایران...")
        exec_cmd(client_foreign, "docker pull nginx:alpine && docker pull rapiz1/rathole:latest")
        exec_cmd(client_foreign, "docker save nginx:alpine rapiz1/rathole:latest | gzip > /tmp/images.tar.gz")
        
        # Stream via SFTP
        with tempfile.TemporaryDirectory() as tmpdir:
            local_tar = Path(tmpdir) / "images.tar.gz"
            print("[*] دریافت ایمیج‌ها از سرور خارج...")
            sftp_f = client_foreign.open_sftp()
            sftp_f.get("/tmp/images.tar.gz", str(local_tar))
            sftp_f.close()

            print("[*] انتقال ایمیج‌ها به سرور ایران...")
            sftp_i = client_iran.open_sftp()
            sftp_i.put(str(local_tar), "/tmp/images.tar.gz")
            sftp_i.close()

            print("[*] بارگذاری ایمیج‌ها در داکر ایران...")
            exec_cmd(client_iran, "docker load -i /tmp/images.tar.gz && rm -f /tmp/images.tar.gz")
    else:
        print("[+] تمام ایمیج‌ها با موفقیت از میرور داخلی docker.iranserver.com دریافت شدند.")

def main():
    clear_screen()
    print("=" * 68)
    print("   EMERGENCY RELAY VPN AUTO-DEPLOYER (WAR-MODE & 100% DOMESTIC)    ")
    print("   استقرار سرور ایران بدون نیاز به اینترنت بین‌الملل (با میرور ایران‌سرور)  ")
    print("=" * 68)
    print()

    # 1. Inputs
    print("--- [۱. مشخصات سرور خارج (Foreign Server / Exit Node)] ---")
    foreign_ip = get_input("Foreign Server IP")
    foreign_port = get_input("SSH Port", "22")
    foreign_user = get_input("SSH Username", "root")
    foreign_pass = get_input("SSH Password")
    print()

    print("--- [۲. مشخصات سرور ایران (Iran Server / Bridge & Camouflage)] ---")
    iran_ip = get_input("Iran Server IP")
    iran_port = get_input("SSH Port", "22")
    iran_user = get_input("SSH Username", "root")
    iran_pass = get_input("SSH Password")
    print()

    print("--- [۳. تنظیمات شبکه و استتار] ---")
    tunnel_port = get_input("Tunnel Port (پورت اتصال مخفی بین دو سرور)", "2333")
    domain = get_input("Domain (اگر دامنه دارید وارد کنید، در غیر اینصورت خالی بگذارید)", "").strip()
    sni_host = domain if domain else iran_ip
    
    # Generate secrets
    client_uuid = str(uuid.uuid4())
    ws_secret_path = f"api-v2-{secrets.token_hex(4)}"
    tunnel_token = secrets.token_hex(16)

    print("\n[*] Initializing setup with parameters:")
    print(f"    - Client UUID:       {client_uuid}")
    print(f"    - WebSocket Path:    /{ws_secret_path}")
    print(f"    - Tunnel Noise Port: {tunnel_port}")
    print()

    # 2. SSH Connections
    client_foreign = create_ssh_client(foreign_ip, foreign_port, foreign_user, foreign_pass)
    if not client_foreign:
        sys.exit(1)

    client_iran = create_ssh_client(iran_ip, iran_port, iran_user, iran_pass)
    if not client_iran:
        sys.exit(1)

    # 3. Setup Environments
    print("\n--- [آماده‌سازی مخازن و داکر روی سرورها] ---")
    setup_foreign_server_environment(client_foreign)
    setup_iran_server_environment(client_iran)
    sync_images_if_needed(client_foreign, client_iran)

    # 4. Generate & Deploy Foreign Configs
    print("\n--- [استقرار سرویس‌ها روی سرور خارج] ---")
    with tempfile.TemporaryDirectory() as tmpdir:
        xray_cfg = (BASE_DIR / "foreign" / "xray-config.json").read_text(encoding="utf-8")
        xray_cfg = xray_cfg.replace("CLIENT_UUID", client_uuid).replace("WS_SECRET_PATH", ws_secret_path)

        rathole_cfg = (BASE_DIR / "foreign" / "rathole-client.toml").read_text(encoding="utf-8")
        rathole_cfg = rathole_cfg.replace("IRAN_IP", iran_ip).replace("TUNNEL_PORT", tunnel_port).replace("TUNNEL_SECRET_TOKEN", tunnel_token)

        docker_cfg = (BASE_DIR / "foreign" / "docker-compose.yml").read_text(encoding="utf-8")

        f_tmp = Path(tmpdir) / "foreign"
        f_tmp.mkdir()
        (f_tmp / "xray-config.json").write_text(xray_cfg, encoding="utf-8")
        (f_tmp / "rathole-client.toml").write_text(rathole_cfg, encoding="utf-8")
        (f_tmp / "docker-compose.yml").write_text(docker_cfg, encoding="utf-8")

        exec_cmd(client_foreign, "mkdir -p /opt/emergency-tunnel")
        sftp_f = client_foreign.open_sftp()
        upload_directory(sftp_f, str(f_tmp), "/opt/emergency-tunnel")
        sftp_f.close()

        print("[*] Starting containers on Foreign server...")
        exec_cmd(client_foreign, "cd /opt/emergency-tunnel && docker compose down && docker compose up -d")

    # 5. Generate & Deploy Iran Configs
    print("\n--- [استقرار سرویس‌ها و سایت استتار روی سرور ایران] ---")
    exec_cmd(client_iran, "mkdir -p /opt/emergency-tunnel/certs")
    print("[*] [ایران] تولید گواهی TLS داخلی...")
    exec_cmd(client_iran, f"openssl req -x509 -nodes -days 3650 -newkey rsa:2048 -keyout /opt/emergency-tunnel/certs/privkey.pem -out /opt/emergency-tunnel/certs/fullchain.pem -subj '/CN={sni_host}'")

    with tempfile.TemporaryDirectory() as tmpdir:
        nginx_cfg = (BASE_DIR / "iran" / "nginx.conf").read_text(encoding="utf-8")
        nginx_cfg = nginx_cfg.replace("WS_SECRET_PATH", ws_secret_path)

        rathole_srv = (BASE_DIR / "iran" / "rathole-server.toml").read_text(encoding="utf-8")
        rathole_srv = rathole_srv.replace("TUNNEL_PORT", tunnel_port).replace("TUNNEL_SECRET_TOKEN", tunnel_token)

        docker_iran = (BASE_DIR / "iran" / "docker-compose.yml").read_text(encoding="utf-8")

        i_tmp = Path(tmpdir) / "iran"
        i_tmp.mkdir()
        (i_tmp / "nginx.conf").write_text(nginx_cfg, encoding="utf-8")
        (i_tmp / "rathole-server.toml").write_text(rathole_srv, encoding="utf-8")
        (i_tmp / "docker-compose.yml").write_text(docker_iran, encoding="utf-8")

        sftp_i = client_iran.open_sftp()
        upload_directory(sftp_i, str(i_tmp), "/opt/emergency-tunnel")
        # Upload decoy site
        upload_directory(sftp_i, str(BASE_DIR / "iran" / "decoy-site"), "/opt/emergency-tunnel/decoy-site")
        sftp_i.close()

        print("[*] Starting containers on Iran server...")
        exec_cmd(client_iran, "cd /opt/emergency-tunnel && docker compose down && docker compose up -d")

    # Restart foreign rathole to ensure connection establishment
    time.sleep(2)
    exec_cmd(client_foreign, "cd /opt/emergency-tunnel && docker compose restart rathole")

    # 6. Build Client VLESS Config
    vless_link = f"vless://{client_uuid}@{iran_ip}:443?path=%2F{ws_secret_path}&security=tls&encryption=none&type=ws&sni={sni_host}#Emergency-Iran-Relay"
    
    # Save config locally
    out_file = BASE_DIR / "client-config.txt"
    out_file.write_text(f"VLESS LINK:\n{vless_link}\n\nClient UUID: {client_uuid}\nWebSocket Path: /{ws_secret_path}\nServer IP: {iran_ip}\nPort: 443\nSNI / Host: {sni_host}\n", encoding="utf-8")

    client_foreign.close()
    client_iran.close()

    print("\n" + "=" * 68)
    print("   [+] راه‌اندازی با موفقیت کامل انجام شد! (DEPLOYED SUCCESSFULLY)   ")
    print("=" * 68)
    print("\nلینک کانفیگ کلاینت شما (جهت کپی در v2rayNG / V2rayN / Nekobox):")
    print("-" * 68)
    print(vless_link)
    print("-" * 68)
    print(f"\nاطلاعات کامل در فایل ذخیره شد:\n{out_file}")
    print(f"\nوضعیت استتار: اگر آدرس https://{iran_ip} را در مرورگر باز کنید، وب‌سایت شرکتی نمایش داده خواهد شد.")
    print("=" * 68 + "\n")

if __name__ == "__main__":
    main()
