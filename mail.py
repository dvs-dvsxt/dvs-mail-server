#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
命令行邮件服务器 - 纯CLI版本
支持：接收邮件、发送邮件、查看邮件列表
"""

import os
import sys
import socket
import smtplib
import dns.resolver
import threading
import socketserver
import re
import time
import base64
import json
import hashlib
import getpass
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email import message_from_string
from email.header import decode_header
import chardet

# ========== 配置 ==========
CONFIG_FILE = "mail_config.json"
DATA_FILE = "email_data.json"

# 全局配置
config = {
    "domain": "",          # 用户指定的域名
    "smtp_ports": [25, 587, 465],
    "admin_password_hash": ""
}

# 数据存储
email_storage = {
    'received': [],
    'sent': [],
    'servers': {}
}

running_servers = {}

# ========== 颜色输出 ==========
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_color(text, color=Colors.RESET):
    print(f"{color}{text}{Colors.RESET}")

def print_success(text):
    print_color(f"✅ {text}", Colors.GREEN)

def print_error(text):
    print_color(f"❌ {text}", Colors.RED)

def print_warning(text):
    print_color(f"⚠️  {text}", Colors.YELLOW)

def print_info(text):
    print_color(f"ℹ️  {text}", Colors.CYAN)

def print_title(text):
    print_color(f"\n{'='*60}", Colors.BOLD)
    print_color(f"  {text}", Colors.BOLD)
    print_color(f"{'='*60}\n", Colors.BOLD)

# ========== 配置管理 ==========
def load_config():
    """加载配置文件"""
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config.update(json.load(f))
            print_success(f"加载配置成功: {CONFIG_FILE}")
            return True
        except Exception as e:
            print_error(f"加载配置失败: {e}")
            return False
    return False

def save_config():
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print_success(f"配置已保存: {CONFIG_FILE}")
        return True
    except Exception as e:
        print_error(f"保存配置失败: {e}")
        return False

def init_config():
    """初始化配置（用户交互）"""
    print_title("邮件服务器初始化配置")
    
    # 设置域名
    while True:
        domain = input("请输入您的邮件域名 (如: example.com): ").strip()
        if domain:
            config["domain"] = domain
            break
        print_error("域名不能为空，请重新输入")
    
    # 设置管理员密码
    while True:
        password = getpass.getpass("请设置管理员密码: ")
        confirm = getpass.getpass("请再次输入密码: ")
        if password == confirm and len(password) >= 6:
            config["admin_password_hash"] = hashlib.sha256(password.encode('utf-8')).hexdigest()
            break
        print_error("密码不一致或长度小于6位，请重新设置")
    
    # SMTP端口配置
    ports_input = input("请输入SMTP监听端口 (多个用逗号分隔，默认: 25,587,465): ").strip()
    if ports_input:
        try:
            ports = [int(p.strip()) for p in ports_input.split(',') if p.strip().isdigit()]
            if ports:
                config["smtp_ports"] = ports
        except:
            print_warning("端口格式错误，使用默认端口")
    
    save_config()
    print_success("配置完成！")
    return True

# ========== 数据持久化 ==========
def load_data():
    """从JSON文件加载数据"""
    global email_storage
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                email_storage = json.load(f)
            print_success(f"加载数据成功: {DATA_FILE}")
        except Exception as e:
            print_error(f"加载数据失败: {e}")
            email_storage = {'received': [], 'sent': [], 'servers': {}}
    else:
        save_data()

def save_data():
    """保存数据到JSON文件"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(email_storage, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print_error(f"保存数据失败: {e}")

# ========== 密码验证 ==========
def verify_password():
    """验证管理员密码"""
    if not config.get("admin_password_hash"):
        print_error("未设置管理员密码，请先运行 init 命令")
        return False
    
    max_attempts = 3
    for attempt in range(max_attempts):
        password = getpass.getpass(f"请输入管理员密码 (尝试 {attempt+1}/{max_attempts}): ")
        password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
        if password_hash == config["admin_password_hash"]:
            return True
        print_error("密码错误")
    
    print_error("密码验证失败次数过多")
    return False

# ========== 邮件发送 ==========
class MailSender:
    def __init__(self, domain):
        self.domain = domain
    
    def find_mx_server(self, domain):
        """查找域名的MX记录"""
        try:
            answers = dns.resolver.resolve(domain, 'MX')
            mx_records = []
            for rdata in answers:
                mx_records.append((rdata.preference, str(rdata.exchange).rstrip('.')))
            mx_records.sort()
            if mx_records:
                return mx_records[0][1]
            return domain
        except Exception as e:
            print_warning(f"MX查找失败: {e}，使用域名直连")
            return domain
    
    def send_email(self, from_addr, to_addr, subject, body, attachment_paths=None):
        """发送邮件（支持附件）"""
        print_info(f"准备发送邮件: {from_addr} -> {to_addr}")
        
        # 记录发送信息
        send_record = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'from': from_addr,
            'to': to_addr,
            'subject': subject,
            'status': 'pending',
            'attachments': attachment_paths or []
        }
        
        try:
            target_domain = to_addr.split('@')[1]
            mx_server = self.find_mx_server(target_domain)
            print_info(f"目标MX服务器: {mx_server}")
            
            ports = [25, 587, 465]
            success = False
            
            for port in ports:
                try:
                    print_info(f"尝试连接 {mx_server}:{port}...")
                    
                    if port == 465:
                        server = smtplib.SMTP_SSL(mx_server, port, timeout=30)
                    else:
                        server = smtplib.SMTP(mx_server, port, timeout=30)
                        if port == 587:
                            server.starttls()
                    
                    server.ehlo_or_helo_if_needed()
                    
                    # 构建邮件
                    msg = MIMEMultipart()
                    msg['From'] = from_addr
                    msg['To'] = to_addr
                    msg['Subject'] = subject
                    msg['Date'] = time.strftime('%a, %d %b %Y %H:%M:%S +0000', time.gmtime())
                    msg.attach(MIMEText(body, 'plain', 'utf-8'))
                    
                    # 添加附件
                    if attachment_paths:
                        for filepath in attachment_paths:
                            if os.path.exists(filepath):
                                filename = os.path.basename(filepath)
                                with open(filepath, 'rb') as f:
                                    file_data = f.read()
                                part = MIMEBase('application', 'octet-stream')
                                part.set_payload(file_data)
                                encoders.encode_base64(part)
                                part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                                msg.attach(part)
                                print_info(f"已添加附件: {filename}")
                    
                    server.sendmail(from_addr, [to_addr], msg.as_string())
                    server.quit()
                    
                    print_success(f"邮件发送成功！(端口 {port})")
                    success = True
                    send_record['status'] = 'success'
                    send_record['details'] = f'通过端口 {port} 发送成功'
                    break
                    
                except Exception as e:
                    print_warning(f"端口 {port} 失败: {e}")
                    continue
            
            if not success:
                print_error("所有端口都尝试失败")
                send_record['status'] = 'failed'
                send_record['details'] = '所有端口尝试失败'
            
        except Exception as e:
            print_error(f"发送失败: {e}")
            send_record['status'] = 'error'
            send_record['details'] = str(e)
        
        email_storage['sent'].append(send_record)
        save_data()
        return send_record['status'] == 'success'

# ========== 邮件接收服务器 ==========
class SMTPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        client_ip = self.client_address[0]
        port = self.server.server_address[1]
        print_info(f"新连接来自: {client_ip} (端口 {port})")
        
        self.request.send(b'220 Mail Server Ready\r\n')
        
        sender = None
        recipients = []
        data_buffer = []
        in_data = False
        expecting_data = False
        
        try:
            while True:
                data = self.request.recv(4096).decode('utf-8', errors='ignore').strip()
                if not data:
                    break
                
                lines = data.split('\r\n')
                for line in lines:
                    if not line.strip():
                        continue
                    
                    if line.upper().startswith(('HELO', 'EHLO')):
                        self.request.send(b'250-mail.example.com\r\n250-PIPELINING\r\n250-SIZE 52428800\r\n250 OK\r\n')
                    
                    elif line.upper().startswith('MAIL FROM:'):
                        match = re.search(r'MAIL FROM:\s*<(.+?)>', line, re.IGNORECASE)
                        if match:
                            sender = match.group(1)
                            self.request.send(b'250 OK\r\n')
                        else:
                            self.request.send(b'501 Bad sender address\r\n')
                    
                    elif line.upper().startswith('RCPT TO:'):
                        match = re.search(r'RCPT TO:\s*<(.+?)>', line, re.IGNORECASE)
                        if match:
                            recipient = match.group(1)
                            recipients.append(recipient)
                            self.request.send(b'250 OK\r\n')
                        else:
                            self.request.send(b'501 Bad recipient address\r\n')
                    
                    elif line.upper() == 'DATA':
                        if not recipients:
                            self.request.send(b'503 No valid recipients\r\n')
                        else:
                            self.request.send(b'354 End data with <CR><LF>.<CR><LF>\r\n')
                            in_data = True
                            expecting_data = True
                    
                    elif line == '.' and expecting_data:
                        in_data = False
                        expecting_data = False
                        full_message = '\r\n'.join(data_buffer)
                        self.process_email(sender, recipients, full_message, port)
                        self.request.send(b'250 OK Message received\r\n')
                        sender = None
                        recipients = []
                        data_buffer = []
                    
                    elif line.upper() == 'QUIT':
                        self.request.send(b'221 Bye\r\n')
                        return
                    
                    elif in_data:
                        data_buffer.append(line)
                    
                    else:
                        self.request.send(b'250 OK\r\n')
                        
        except Exception as e:
            print_error(f"处理错误: {e}")
    
    def process_email(self, sender, recipients, raw_data, port):
        """处理接收的邮件"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        print_success(f"收到邮件 - 端口 {port}")
        print_info(f"发件人: {sender}")
        print_info(f"收件人: {', '.join(recipients)}")
        
        email_info = {
            'timestamp': timestamp,
            'port': port,
            'sender': sender,
            'recipients': recipients,
            'raw_data': raw_data[:5000],  # 截断存储
            'parsed': {},
            'attachments': []
        }
        
        try:
            parsed, attachments = self.parse_email(raw_data)
            email_info['parsed'] = parsed
            email_info['attachments'] = attachments
            
            if parsed.get('subject'):
                print_info(f"主题: {parsed['subject']}")
            if parsed.get('body'):
                print_info(f"正文预览: {parsed['body'][:100]}...")
            if attachments:
                print_info(f"附件: {', '.join([a['name'] for a in attachments])}")
                
        except Exception as e:
            print_warning(f"邮件解析失败: {e}")
            email_info['error'] = str(e)
        
        email_storage['received'].append(email_info)
        save_data()
    
    def parse_email(self, raw_data):
        """解析邮件内容"""
        email_msg = message_from_string(raw_data)
        
        parsed = {'subject': '', 'date': '', 'body': '', 'html_body': ''}
        attachments = []
        
        parsed['subject'] = self.decode_header(email_msg.get('Subject', ''))
        parsed['date'] = email_msg.get('Date', '')
        
        if email_msg.is_multipart():
            for part in email_msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get('Content-Disposition', ''))
                
                if 'attachment' in content_disposition:
                    filename = self.decode_header(part.get_filename())
                    if filename:
                        payload = part.get_payload(decode=True)
                        if payload:
                            attachments.append({
                                'name': filename,
                                'data': base64.b64encode(payload).decode('utf-8'),
                                'size': len(payload)
                            })
                    continue
                
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        text = payload.decode(charset, errors='replace')
                        if content_type == 'text/plain':
                            parsed['body'] = text
                        elif content_type == 'text/html':
                            parsed['html_body'] = text
                    except:
                        parsed['body'] = str(payload)
        else:
            payload = email_msg.get_payload(decode=True)
            if payload:
                charset = email_msg.get_content_charset() or 'utf-8'
                try:
                    parsed['body'] = payload.decode(charset, errors='replace')
                except:
                    parsed['body'] = str(payload)
        
        return parsed, attachments
    
    def decode_header(self, header):
        """解码邮件头"""
        if not header:
            return ""
        try:
            parts = []
            for part, encoding in decode_header(header):
                if isinstance(part, bytes):
                    if encoding:
                        parts.append(part.decode(encoding, errors='replace'))
                    else:
                        detected = chardet.detect(part)
                        enc = detected['encoding'] or 'utf-8'
                        parts.append(part.decode(enc, errors='replace'))
                else:
                    parts.append(part)
            return ''.join(parts)
        except:
            return str(header)

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True

def start_smtp_server(port):
    """启动SMTP服务器"""
    if port in running_servers:
        print_warning(f"端口 {port} 已在运行")
        return False
    
    try:
        print_info(f"启动SMTP服务器在端口 {port}...")
        server = ThreadedTCPServer(('0.0.0.0', port), SMTPHandler)
        running_servers[port] = server
        
        email_storage['servers'][str(port)] = {
            'status': 'running',
            'host': '0.0.0.0',
            'start_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        save_data()
        
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print_success(f"SMTP服务器已启动 (端口 {port})")
        return True
        
    except PermissionError:
        print_error(f"需要管理员权限绑定端口 {port}")
        email_storage['servers'][str(port)] = {'status': 'error', 'error': 'Permission denied'}
        save_data()
        return False
    except OSError as e:
        print_error(f"端口 {port} 已被占用")
        email_storage['servers'][str(port)] = {'status': 'error', 'error': 'Port in use'}
        save_data()
        return False
    except Exception as e:
        print_error(f"启动失败: {e}")
        return False

def stop_smtp_server(port):
    """停止SMTP服务器"""
    if port not in running_servers:
        print_warning(f"端口 {port} 未运行")
        return False
    
    try:
        running_servers[port].shutdown()
        running_servers[port].server_close()
        del running_servers[port]
        
        if str(port) in email_storage['servers']:
            email_storage['servers'][str(port)]['status'] = 'stopped'
            email_storage['servers'][str(port)]['stop_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            save_data()
        
        print_success(f"SMTP服务器已停止 (端口 {port})")
        return True
    except Exception as e:
        print_error(f"停止失败: {e}")
        return False

# ========== 命令行界面 ==========
def cmd_help():
    """显示帮助信息"""
    print_title("帮助信息")
    print("""
命令列表:
  init          - 初始化配置（设置域名和密码）
  start [端口]  - 启动SMTP服务器（默认所有配置端口）
  stop [端口]   - 停止SMTP服务器
  status        - 查看服务器状态
  send          - 发送邮件（交互式）
  list          - 列出所有邮件
  list in       - 列出接收的邮件
  list out      - 列出已发送的邮件
  view [ID]     - 查看邮件详情
  download [ID] - 下载附件
  clear         - 清空所有邮件记录
  help          - 显示此帮助
  exit/quit     - 退出程序
""")

def cmd_init():
    """初始化配置"""
    init_config()

def cmd_start(args):
    """启动SMTP服务器"""
    if not config.get("domain"):
        print_error("请先运行 init 配置域名")
        return
    
    ports = []
    if args:
        try:
            ports = [int(p.strip()) for p in args.split(',') if p.strip().isdigit()]
        except:
            pass
    
    if not ports:
        ports = config.get("smtp_ports", [25, 587, 465])
    
    for port in ports:
        start_smtp_server(port)
    
    print_info(f"当前运行端口: {list(running_servers.keys())}")

def cmd_stop(args):
    """停止SMTP服务器"""
    if not args:
        # 停止所有
        for port in list(running_servers.keys()):
            stop_smtp_server(port)
        return
    
    try:
        port = int(args)
        stop_smtp_server(port)
    except:
        print_error("请输入有效的端口号")

def cmd_status():
    """查看服务器状态"""
    print_title("服务器状态")
    
    if not email_storage['servers']:
        print_info("没有配置任何服务器")
        return
    
    for port, info in email_storage['servers'].items():
        status = info.get('status', 'unknown')
        status_color = Colors.GREEN if status == 'running' else Colors.YELLOW if status == 'stopped' else Colors.RED
        print(f"端口 {port}: {status_color}{status.upper()}{Colors.RESET}")
        if info.get('start_time'):
            print(f"  启动时间: {info['start_time']}")
        if info.get('error'):
            print(f"  错误: {info['error']}")

def cmd_send():
    """交互式发送邮件"""
    if not config.get("domain"):
        print_error("请先运行 init 配置域名")
        return
    
    if not verify_password():
        return
    
    print_title("发送邮件")
    
    # 发件人
    default_from = f"admin@{config['domain']}"
    from_addr = input(f"发件人邮箱 (默认: {default_from}): ").strip()
    if not from_addr:
        from_addr = default_from
    
    # 收件人
    to_addr = input("收件人邮箱: ").strip()
    while not to_addr or '@' not in to_addr:
        print_error("请输入有效的邮箱地址")
        to_addr = input("收件人邮箱: ").strip()
    
    # 主题
    subject = input("邮件主题: ").strip()
    if not subject:
        subject = "无主题"
    
    # 正文
    print("请输入邮件内容 (输入空行结束，或输入 'END' 结束):")
    lines = []
    while True:
        line = input()
        if line == 'END' or (not line and lines and lines[-1] == ''):
            break
        lines.append(line)
    body = '\n'.join(lines[:-1]) if lines else ""
    
    # 附件
    attachments = []
    while True:
        add = input("添加附件? (y/n): ").strip().lower()
        if add == 'y':
            filepath = input("请输入文件路径: ").strip()
            if os.path.exists(filepath):
                attachments.append(filepath)
                print_success(f"已添加: {filepath}")
            else:
                print_error("文件不存在")
        else:
            break
    
    # 确认发送
    print("\n" + "="*50)
    print(f"发件人: {from_addr}")
    print(f"收件人: {to_addr}")
    print(f"主题: {subject}")
    print(f"正文: {body[:100]}...")
    if attachments:
        print(f"附件: {', '.join(attachments)}")
    print("="*50)
    
    confirm = input("\n确认发送? (y/n): ").strip().lower()
    if confirm != 'y':
        print_info("已取消发送")
        return
    
    sender = MailSender(config['domain'])
    success = sender.send_email(from_addr, to_addr, subject, body, attachments)
    
    if success:
        print_success("邮件发送成功！")
    else:
        print_error("邮件发送失败")

def cmd_list(args):
    """列出邮件"""
    if args == 'in':
        emails = email_storage['received']
        title = "接收的邮件"
    elif args == 'out':
        emails = email_storage['sent']
        title = "已发送邮件"
    else:
        print("用法: list in | list out")
        return
    
    print_title(f"{title} (共 {len(emails)} 封)")
    
    if not emails:
        print_info("暂无邮件")
        return
    
    for i, email in enumerate(emails):
        if 'parsed' in email:
            subject = email['parsed'].get('subject', '无主题')
        else:
            subject = email.get('subject', '无主题')
        
        sender = email.get('sender') or email.get('from', '未知')
        timestamp = email.get('timestamp', '未知时间')
        status = email.get('status', '')
        
        status_str = f" [{status}]" if status else ""
        print(f"  [{i}] {timestamp} | {sender} | {subject[:40]}{status_str}")

def cmd_view(args):
    """查看邮件详情"""
    if not args:
        print_error("请指定邮件ID，如: view 0")
        return
    
    try:
        idx = int(args)
    except:
        print_error("请输入有效的数字ID")
        return
    
    print_title("邮件详情")
    
    # 先尝试在接收邮件中查找
    if idx < len(email_storage['received']):
        email = email_storage['received'][idx]
        print(f"类型: 接收邮件")
        print(f"时间: {email.get('timestamp', '未知')}")
        print(f"端口: {email.get('port', '未知')}")
        print(f"发件人: {email.get('sender', '未知')}")
        print(f"收件人: {', '.join(email.get('recipients', []))}")
        
        parsed = email.get('parsed', {})
        print(f"主题: {parsed.get('subject', '无')}")
        print(f"日期: {parsed.get('date', '无')}")
        
        body = parsed.get('body', '')
        if body:
            print("\n正文:")
            print(body[:500] + ("..." if len(body) > 500 else ""))
        
        attachments = email.get('attachments', [])
        if attachments:
            print(f"\n附件 ({len(attachments)}个):")
            for a in attachments:
                print(f"  - {a['name']} ({a.get('size', 0)} bytes)")
        
        return
    
    # 再尝试在已发送邮件中查找
    sent_idx = idx - len(email_storage['received'])
    if sent_idx < len(email_storage['sent']):
        email = email_storage['sent'][sent_idx]
        print(f"类型: 已发送邮件")
        print(f"时间: {email.get('timestamp', '未知')}")
        print(f"发件人: {email.get('from', '未知')}")
        print(f"收件人: {email.get('to', '未知')}")
        print(f"主题: {email.get('subject', '无')}")
        print(f"状态: {email.get('status', '未知')}")
        print(f"详情: {email.get('details', '无')}")
        
        attachments = email.get('attachments', [])
        if attachments:
            print(f"\n附件: {', '.join(attachments)}")
        return
    
    print_error("未找到对应的邮件")

def cmd_download(args):
    """下载附件"""
    if not args:
        print_error("请指定邮件ID，如: download 0")
        return
    
    try:
        idx = int(args)
    except:
        print_error("请输入有效的数字ID")
        return
    
    if idx >= len(email_storage['received']):
        print_error("邮件不存在")
        return
    
    email = email_storage['received'][idx]
    attachments = email.get('attachments', [])
    
    if not attachments:
        print_info("该邮件没有附件")
        return
    
    print(f"找到 {len(attachments)} 个附件:")
    for i, a in enumerate(attachments):
        print(f"  [{i}] {a['name']} ({a.get('size', 0)} bytes)")
    
    try:
        attach_idx = int(input("选择要下载的附件编号: ").strip())
        if attach_idx < 0 or attach_idx >= len(attachments):
            print_error("无效编号")
            return
    except:
        print_error("请输入有效的数字")
        return
    
    attachment = attachments[attach_idx]
    file_data = base64.b64decode(attachment['data'])
    
    # 创建下载目录
    if not os.path.exists('downloads'):
        os.makedirs('downloads')
    
    filename = attachment['name']
    filepath = os.path.join('downloads', filename)
    
    # 处理重名
    counter = 1
    while os.path.exists(filepath):
        name, ext = os.path.splitext(filename)
        filepath = os.path.join('downloads', f"{name}_{counter}{ext}")
        counter += 1
    
    with open(filepath, 'wb') as f:
        f.write(file_data)
    
    print_success(f"附件已保存: {filepath}")

def cmd_clear():
    """清空邮件记录"""
    if not verify_password():
        return
    
    confirm = input("确定要清空所有邮件记录吗? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print_info("已取消")
        return
    
    email_storage['received'] = []
    email_storage['sent'] = []
    save_data()
    print_success("所有邮件记录已清空")

def cmd_exit():
    """退出程序"""
    print_info("正在停止所有服务器...")
    for port in list(running_servers.keys()):
        stop_smtp_server(port)
    print_success("再见！")
    sys.exit(0)

# ========== 主函数 ==========
def main():
    """主入口"""
    print_title("命令行邮件服务器 v2.0")
    print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 加载配置和数据
    config_loaded = load_config()
    load_data()
    
    if not config_loaded:
        print_warning("未找到配置文件，请运行 init 初始化")
    
    print(f"域名: {config.get('domain', '未设置')}")
    print(f"SMTP端口: {config.get('smtp_ports', [])}")
    print(f"接收邮件: {len(email_storage.get('received', []))} 封")
    print(f"发送邮件: {len(email_storage.get('sent', []))} 封")
    print(f"运行端口: {list(running_servers.keys())}")
    print("\n输入 'help' 查看命令列表\n")
    
    # 命令循环
    while True:
        try:
            cmd = input("mail> ").strip().lower()
            if not cmd:
                continue
            
            parts = cmd.split(maxsplit=1)
            command = parts[0]
            args = parts[1] if len(parts) > 1 else ""
            
            if command in ['exit', 'quit']:
                cmd_exit()
            elif command == 'help':
                cmd_help()
            elif command == 'init':
                cmd_init()
            elif command == 'start':
                cmd_start(args)
            elif command == 'stop':
                cmd_stop(args)
            elif command == 'status':
                cmd_status()
            elif command == 'send':
                cmd_send()
            elif command == 'list':
                cmd_list(args)
            elif command == 'view':
                cmd_view(args)
            elif command == 'download':
                cmd_download(args)
            elif command == 'clear':
                cmd_clear()
            else:
                print_error(f"未知命令: {command}，输入 'help' 查看帮助")
                
        except KeyboardInterrupt:
            print("\n")
            cmd_exit()
        except Exception as e:
            print_error(f"错误: {e}")

if __name__ == '__main__':
    main()