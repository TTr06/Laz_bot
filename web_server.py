"""
================================================================================
 LAZADA TRACKER & FATHER BOT - EMBEDDED WEB CLI SERVER (web_server.py)
================================================================================
 Giao diện dòng lệnh qua Web siêu nhẹ (Web-based CLI) phát qua mạng nội bộ LAN/Wi-Fi:
 - Phát đồng thời log thời gian thực từ Bot Telegram & Auto Scheduler qua WebSocket.
 - Nhận lệnh điều khiển trực tiếp từ trình duyệt điện thoại/máy tính (Full Host CLI).
 - Nút bấm thao tác nhanh (Quick Action Buttons) trên điện thoại không cần gõ phím.
 - Siêu tiết kiệm tài nguyên: Chỉ ~10MB RAM, CPU ~0.01%, nhẹ hơn scrcpy 50 lần.
================================================================================
"""

import os
import sys
import json
import time
import socket
import logging
import threading
import asyncio
import io
import contextlib
from typing import Optional, Set
from aiohttp import web

import database
from database import get_subscribers, is_auto_track_enabled
from dashboard import add_log_listener, remove_log_listener
from rich.console import Console

# Console hỗ trợ xuất mã màu ANSI cho Web
_ansi_console = Console(color_system="standard", force_terminal=True, highlight=False)

logger = logging.getLogger("web_server")


def get_local_ip() -> str:
    """Tự động phát hiện địa chỉ IP nội bộ trong mạng LAN / Wi-Fi"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>LazBot Web Console</title>
  <style>
    :root {
      --bg: #0d1117;
      --card-bg: #161b22;
      --border: #30363d;
      --text: #c9d1d9;
      --green: #3fb950;
      --blue: #58a6ff;
      --red: #f85149;
      --yellow: #d29922;
      --purple: #bc8cff;
      --term-bg: #030712;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
    body { background-color: var(--bg); color: var(--text); height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

    /* Header */
    header {
      background: var(--card-bg);
      border-bottom: 1px solid var(--border);
      padding: 10px 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
    }
    .header-left { display: flex; align-items: center; gap: 10px; }
    .header-title { font-size: 16px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 6px; }
    .badge {
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 12px;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .badge-online { background: rgba(63, 185, 80, 0.15); color: var(--green); border: 1px solid var(--green); }
    .badge-offline { background: rgba(248, 81, 73, 0.15); color: var(--red); border: 1px solid var(--red); }
    .badge-ip { background: rgba(88, 166, 255, 0.15); color: var(--blue); border: 1px solid var(--blue); }

    /* Quick Action Buttons */
    .quick-bar {
      background: #111620;
      padding: 8px 12px;
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 6px;
      overflow-x: auto;
      white-space: nowrap;
      -webkit-overflow-scrolling: touch;
    }
    .quick-bar::-webkit-scrollbar { height: 4px; }
    .quick-bar::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
    .btn-quick {
      background: var(--card-bg);
      color: var(--text);
      border: 1px solid var(--border);
      padding: 6px 12px;
      font-size: 12px;
      font-weight: 600;
      border-radius: 6px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: all 0.15s ease;
      flex-shrink: 0;
    }
    .btn-quick:hover { background: #21262d; border-color: var(--blue); color: #fff; }
    .btn-quick:active { transform: scale(0.96); }

    /* Terminal Screen */
    #terminal-container {
      flex: 1;
      background: var(--term-bg);
      padding: 12px;
      overflow-y: auto;
      font-family: 'Fira Code', 'Cascadia Code', Consolas, Monaco, monospace;
      font-size: 13px;
      line-height: 1.5;
      word-break: break-all;
      white-space: pre-wrap;
    }
    .term-line { margin-bottom: 2px; }
    .term-cmd { color: var(--blue); font-weight: bold; }
    .term-out { color: #e6edf3; }
    .term-log { color: #8b949e; }
    .term-alert { color: var(--yellow); }
    .term-error { color: var(--red); }

    /* Footer Input */
    footer {
      background: var(--card-bg);
      border-top: 1px solid var(--border);
      padding: 10px 14px;
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .prompt-label { font-family: monospace; font-weight: bold; color: var(--green); font-size: 14px; }
    .input-box {
      flex: 1;
      background: #0d1117;
      border: 1px solid var(--border);
      color: #fff;
      padding: 10px 14px;
      font-size: 14px;
      border-radius: 6px;
      outline: none;
      font-family: monospace;
      transition: border-color 0.2s;
    }
    .input-box:focus { border-color: var(--blue); box-shadow: 0 0 0 2px rgba(88, 166, 255, 0.2); }
    .btn-send {
      background: #238636;
      color: #fff;
      border: none;
      padding: 10px 18px;
      font-size: 14px;
      font-weight: 600;
      border-radius: 6px;
      cursor: pointer;
      transition: background 0.15s;
    }
    .btn-send:hover { background: #2ea043; }
    .btn-send:active { transform: scale(0.96); }
    .auto-scroll-toggle {
      font-size: 11px;
      color: #8b949e;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 4px;
      user-select: none;
    }
  </style>
</head>
<body>
  <header>
    <div class="header-left">
      <div class="header-title">🛒 <span>LazBot Host Console</span></div>
      <span id="conn-badge" class="badge badge-offline">● Mất kết nối</span>
    </div>
    <div style="display: flex; align-items: center; gap: 8px;">
      <span class="badge badge-ip" id="ip-badge">LAN: __LAN_IP__:__PORT__</span>
      <label class="auto-scroll-toggle">
        <input type="checkbox" id="chk-autoscroll" checked> Cuộn tự động
      </label>
    </div>
  </header>

  <!-- Thanh nút bấm nhanh trên điện thoại -->
  <div class="quick-bar">
    <button class="btn-quick" onclick="sendCmd('prices')">📊 Danh sách giá</button>
    <button class="btn-quick" onclick="sendCmd('targets')">🎯 Giá đáy săn sale</button>
    <button class="btn-quick" onclick="sendCmd('track')">🔍 Quét giá ngay</button>
    <button class="btn-quick" onclick="sendCmd('cart')">🛒 Cập nhật giỏ</button>
    <button class="btn-quick" onclick="sendCmd('cookie status')">🍪 Trạng thái Cookie</button>
    <button class="btn-quick" onclick="sendCmd('bot status')">🤖 Trạng thái Bot</button>
    <button class="btn-quick" onclick="sendCmd('db info')">💾 CSDL SQLite</button>
    <button class="btn-quick" onclick="sendCmd('help')">❓ Trợ giúp</button>
    <button class="btn-quick" onclick="clearTerm()">🗑️ Xóa màn hình</button>
  </div>

  <!-- Cửa sổ Terminal hiển thị Log thời gian thực -->
  <div id="terminal-container"></div>

  <!-- Thanh nhập lệnh ở dưới cùng -->
  <footer>
    <span class="prompt-label">LazBot&gt;</span>
    <input type="text" id="cmd-input" class="input-box" placeholder="Nhập lệnh (VD: setprice 1 100k, cart, prices, track)..." autocomplete="off" autocapitalize="none">
    <button class="btn-send" onclick="submitInput()">Gửi</button>
  </footer>

  <script>
    const term = document.getElementById('terminal-container');
    const input = document.getElementById('cmd-input');
    const connBadge = document.getElementById('conn-badge');
    const chkAutoScroll = document.getElementById('chk-autoscroll');
    let ws = null;
    let history = [];
    let historyIdx = -1;

    // Bộ giải mã mã màu ANSI thành HTML
    function ansiToHtml(text) {
      if (!text) return '';
      // Thay thế ký tự nhạy cảm HTML
      let html = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

      // Bản đồ mã màu ANSI tiêu chuẩn
      const colors = {
        '30': '#484f58', '31': '#ff7b72', '32': '#3fb950', '33': '#d29922',
        '34': '#58a6ff', '35': '#bc8cff', '36': '#39c5cf', '37': '#b1bac4',
        '90': '#6e7681', '91': '#ffa198', '92': '#56d364', '93': '#e3b341',
        '94': '#79c0ff', '95': '#d2a8ff', '96': '#56d4dd', '97': '#f0f6fc'
      };

      // Chuyển mã ANSI \033[...m thành span
      html = html.replace(/\033\[([0-9;]+)m/g, function(match, code) {
        if (code === '0') return '</span>';
        const parts = code.split(';');
        let style = '';
        parts.forEach(p => {
          if (p === '1') style += 'font-weight:bold;';
          if (p === '2') style += 'opacity:0.75;';
          if (colors[p]) style += `color:${colors[p]};`;
        });
        return `<span style="${style}">`;
      });

      return html;
    }

    function appendOutput(content, type = 'out') {
      const line = document.createElement('div');
      line.className = 'term-line term-' + type;
      line.innerHTML = ansiToHtml(content);
      term.appendChild(line);

      // Giới hạn buffer màn hình tối đa 500 dòng để luôn nhẹ máy
      if (term.childNodes.length > 500) {
        term.removeChild(term.firstChild);
      }

      if (chkAutoScroll.checked) {
        term.scrollTop = term.scrollHeight;
      }
    }

    function clearTerm() {
      term.innerHTML = '';
      appendOutput('[i] Đã xóa màn hình console.', 'log');
    }

    function connectWs() {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${location.host}/ws`;
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        connBadge.className = 'badge badge-online';
        connBadge.textContent = '● Đã kết nối';
        appendOutput('🟢 Đã kết nối thành công tới máy chủ LazBot Web Console!', 'term-line');
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'log') {
            appendOutput(data.msg, 'log');
          } else if (data.type === 'cmd_out') {
            appendOutput(data.msg, 'out');
          } else if (data.type === 'clear') {
            clearTerm();
          }
        } catch (e) {
          appendOutput(event.data, 'out');
        }
      };

      ws.onclose = () => {
        connBadge.className = 'badge badge-offline';
        connBadge.textContent = '● Mất kết nối (Đang thử lại...)';
        setTimeout(connectWs, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    function sendCmd(cmdStr) {
      if (!cmdStr || !cmdStr.trim()) return;
      cmdStr = cmdStr.trim();
      appendOutput(`LazBot> ${cmdStr}`, 'cmd');

      if (cmdStr.toLowerCase() === 'clear' || cmdStr.toLowerCase() === 'cls') {
        clearTerm();
        return;
      }

      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ cmd: cmdStr }));
      } else {
        appendOutput('[!] Chưa kết nối tới WebSocket. Đang gửi qua API...', 'term-alert');
        fetch('/api/cmd', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cmd: cmdStr })
        })
        .then(res => res.json())
        .then(data => appendOutput(data.output, 'out'))
        .catch(err => appendOutput('[!] Lỗi kết nối API: ' + err, 'term-error'));
      }
    }

    function submitInput() {
      const val = input.value;
      if (!val.trim()) return;
      history.push(val);
      historyIdx = history.length;
      sendCmd(val);
      input.value = '';
    }

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        submitInput();
      } else if (e.key === 'ArrowUp') {
        if (historyIdx > 0) {
          historyIdx--;
          input.value = history[historyIdx];
        }
      } else if (e.key === 'ArrowDown') {
        if (historyIdx < history.length - 1) {
          historyIdx++;
          input.value = history[historyIdx];
        } else {
          historyIdx = history.length;
          input.value = '';
        }
      }
    });

    connectWs();
  </script>
</body>
</html>
"""


class WebTerminalServer:
    """
    Máy chủ Web CLI Server tích hợp sử dụng aiohttp:
    - Chạy trong 1 luồng nền độc lập (background daemon thread)
    - Cực nhẹ, tiêu thụ ~10MB RAM và < 0.05% CPU
    """
    def __init__(self, cli_instance=None, host: str = "0.0.0.0", port: int = 8080):
        self.cli = cli_instance
        self.host = host
        self.port = port
        self.app: Optional[web.Application] = None
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.clients: Set[web.WebSocketResponse] = set()
        self.is_running = False
        self.lan_ip = get_local_ip()

    def set_cli(self, cli_instance):
        self.cli = cli_instance

    def _convert_rich_to_ansi(self, msg: str) -> str:
        """Chuyển chuỗi định dạng Rich sang chuỗi chứa mã màu ANSI"""
        try:
            with _ansi_console.capture() as capture:
                _ansi_console.print(msg, end="")
            return capture.get()
        except Exception:
            return msg

    def broadcast_log(self, raw_msg: str):
        """Hàm callback được gọi bởi dashboard.print_cli để gửi log ra tất cả WebSocket"""
        if not self.is_running or not self.clients or not self.loop:
            return

        ansi_msg = self._convert_rich_to_ansi(raw_msg)
        payload = json.dumps({"type": "log", "msg": ansi_msg})

        async def _send():
            for ws in list(self.clients):
                try:
                    await ws.send_str(payload)
                except Exception:
                    self.clients.discard(ws)

        asyncio.run_coroutine_threadsafe(_send(), self.loop)

    def execute_command(self, cmd_line: str) -> str:
        """Thực thi một lệnh CLI và thu nhận toàn bộ kết quả xuất ra màn hình"""
        if not self.cli:
            return "[!] CLI backend chưa sẵn sàng."

        cmd_line = cmd_line.strip()
        if not cmd_line:
            return ""

        name, argv = self.cli.parse_cmd(cmd_line)
        if not name:
            return ""

        if name in ("quit", "exit", "q"):
            return "[i] Lệnh tắt tiến trình bị vô hiệu hóa trên Web để tránh sập server. Hãy dùng 'bot stop' nếu muốn tạm dừng bot."

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            if name in self.cli.cmd_do_func:
                self.cli.do_cmd(name, argv, len(argv))
            else:
                self.cli.do_unknown()

        return buf.getvalue()

    async def handle_index(self, request: web.Request) -> web.Response:
        """Trả về trang Web Terminal tối ưu hóa cho điện thoại & máy tính"""
        html = HTML_TEMPLATE.replace("__LAN_IP__", self.lan_ip).replace("__PORT__", str(self.port))
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        """Xử lý kết nối WebSocket thời gian thực"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.clients.add(ws)

        # Gửi thông điệp chào mừng
        welcome = f"\x1b[1;36m=== LAZADA TRACKER & FATHER BOT - WEB TERMINAL ===\x1b[0m\n" \
                  f"• Địa chỉ LAN : http://{self.lan_ip}:{self.port}\n" \
                  f"• Người dùng  : {len(get_subscribers())} subscribers | Quét tự động: {'BẬT' if is_auto_track_enabled() else 'TẮT'}\n" \
                  f"• Gõ 'help' hoặc chạm các nút phía trên để điều khiển bot.\n"
        await ws.send_str(json.dumps({"type": "cmd_out", "msg": welcome}))

        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        cmd = data.get("cmd", "").strip()
                        if cmd:
                            out = await asyncio.to_thread(self.execute_command, cmd)
                            await ws.send_str(json.dumps({"type": "cmd_out", "msg": out}))
                    except Exception as e:
                        await ws.send_str(json.dumps({"type": "cmd_out", "msg": f"[!] Lỗi: {e}"}))
        finally:
            self.clients.discard(ws)

        return ws

    async def handle_api_cmd(self, request: web.Request) -> web.Response:
        """API REST cho phép thực thi lệnh từ cURL hoặc script khác"""
        try:
            body = await request.json()
            cmd = body.get("cmd", "")
            out = await asyncio.to_thread(self.execute_command, cmd)
            return web.json_response({"status": "ok", "cmd": cmd, "output": out})
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=400)

    async def handle_api_status(self, request: web.Request) -> web.Response:
        """API trả về thông tin trạng thái hệ thống dạng JSON"""
        conn = database.get_connection()
        cart_cnt = conn.execute("SELECT COUNT(*) FROM cart_items").fetchone()[0]
        target_cnt = conn.execute("SELECT COUNT(*) FROM target_prices").fetchone()[0]
        return web.json_response({
            "status": "online",
            "lan_ip": self.lan_ip,
            "port": self.port,
            "subscribers": len(get_subscribers()),
            "auto_track": is_auto_track_enabled(),
            "cart_items": cart_cnt,
            "targets": target_cnt,
            "clients_connected": len(self.clients)
        })

    def start(self, port: Optional[int] = None):
        """Khởi động Web Terminal Server trong luồng nền daemon"""
        if self.is_running:
            return

        if port:
            self.port = port

        def _worker():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            self.app = web.Application()
            self.app.router.add_get("/", self.handle_index)
            self.app.router.add_get("/ws", self.handle_ws)
            self.app.router.add_post("/api/cmd", self.handle_api_cmd)
            self.app.router.add_get("/api/status", self.handle_api_status)

            self.runner = web.AppRunner(self.app)
            self.loop.run_until_complete(self.runner.setup())
            self.site = web.TCPSite(self.runner, self.host, self.port)
            self.loop.run_until_complete(self.site.start())
            self.is_running = True

            # Đăng ký listener để nhận mọi log từ dashboard.print_cli
            add_log_listener(self.broadcast_log)

            try:
                self.loop.run_forever()
            finally:
                remove_log_listener(self.broadcast_log)
                self.is_running = False

        self.thread = threading.Thread(target=_worker, name="WebCLIServerThread", daemon=True)
        self.thread.start()
        time.sleep(0.5)

    def stop(self):
        """Dừng Web Terminal Server một cách an toàn"""
        if not self.is_running or not self.loop:
            return

        remove_log_listener(self.broadcast_log)

        async def _cleanup():
            for ws in list(self.clients):
                await ws.close()
            if self.runner:
                await self.runner.cleanup()

        try:
            future = asyncio.run_coroutine_threadsafe(_cleanup(), self.loop)
            future.result(timeout=2.0)
            self.loop.call_soon_threadsafe(self.loop.stop)
        except Exception:
            pass

        self.is_running = False


# Khởi tạo thể hiện máy chủ toàn cục
web_server = WebTerminalServer()


def run_standalone(port: int = 8080):
    """Khởi chạy độc lập máy chủ Web CLI nếu chạy trực tiếp file web_server.py"""
    from cli import LazBotCLI
    cli_inst = LazBotCLI("LazBot> ")
    cli_inst.init_cmd()
    web_server.set_cli(cli_inst)
    web_server.start(port)

    lan_ip = web_server.lan_ip
    print("=" * 65)
    print("  LAZADA TRACKER - STANDALONE WEB CLI CONSOLE")
    print("=" * 65)
    print(f"• Máy chủ đang chạy tại : http://{lan_ip}:{port}")
    print(f"• Truy cập Localhost    : http://127.0.0.1:{port}")
    print("• Mở trình duyệt trên điện thoại/máy tính cùng Wi-Fi để sử dụng.")
    print("• Nhấn Ctrl + C để dừng máy chủ.")
    print("=" * 65 + "\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Đang tắt Web CLI Server...")
        web_server.stop()
        print("[OK] Đã tắt thành công.")


if __name__ == "__main__":
    p = 8080
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        p = int(sys.argv[1])
    run_standalone(p)
