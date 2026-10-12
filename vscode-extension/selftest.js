// Самопроверка протокола моста: поднимает HTTP-сервер как расширение,
// пишет .agent-cache/vscode-bridge.json, вызывает python-инструменты и выходит.
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawn } = require('child_process');

const root = path.resolve(__dirname, '..');
const dir = path.join(root, '.agent-cache');
const bridgeFile = path.join(dir, 'vscode-bridge.json');
const token = crypto.randomBytes(16).toString('hex');
const calls = [];

// Интерпретатор Python: на macOS/Linux команды `python` обычно нет (только
// `python3`), поэтому выбираем её так же, как это делает сам агент.
// Переопределить можно переменной DEEPSEEK_AGENT_PYTHON.
const pyExe = process.env.DEEPSEEK_AGENT_PYTHON
  || (process.platform === 'win32' ? 'python' : 'python3');

const server = http.createServer((req, res) => {
  let body = '';
  req.on('data', (c) => (body += c));
  req.on('end', () => {
    const msg = JSON.parse(body || '{}');
    if (msg.token !== token) {
      res.writeHead(403).end(JSON.stringify({ ok: false, error: 'bad token' }));
      return;
    }
    calls.push(msg);
    const result = msg.command === 'closeAll'
      ? { closed: 2 }
      : { path: msg.args.path ? path.basename(msg.args.path) : null, line: msg.args.line || 1 };
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ok: true, result }));
  });
});

server.listen(0, '127.0.0.1', () => {
  const port = server.address().port;
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(bridgeFile, JSON.stringify(
    { port, host: '127.0.0.1', token, pid: process.pid, workspace: root }, null, 2));

  const py = [
    'from tools import vscode as v',
    'print(v.vscode_status())',
    'print(v.vscode_open("agent.py", 42))',
    'print(v.vscode_reveal("README.md"))',
    'print(v.vscode_close("agent.py"))',
    'print(v.vscode_close())',
    'print(v.vscode_close_all())',
    'print(v.auto_open("config.py"))',
  ].join('\n');

  const child = spawn(pyExe, ['-c', py], {
    cwd: root,
    // Дочерний Python пишет UTF-8 — иначе на Windows кириллица в выводе
    // превращается в мусор при чтении из Node.
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });
  let out = '';
  child.stdout.on('data', (d) => (out += d));
  child.stderr.on('data', (d) => (out += d));

  child.on('error', (e) => {
    console.log('--- python не запустился ---');
    console.log(`${pyExe}: ${e.message}`);
    console.log('Укажите интерпретатор: DEEPSEEK_AGENT_PYTHON=/путь/python node selftest.js');
    try { fs.unlinkSync(bridgeFile); } catch (_) {}
    server.close();
    process.exit(1);
  });

  child.on('close', (code) => {
    console.log('--- python (exit ' + code + ') ---');
    console.log(out.trim());
    console.log('--- commands received ---');
    for (const c of calls) {
      console.log(c.command, JSON.stringify(c.args));
    }
    try { fs.unlinkSync(bridgeFile); } catch (_) {}
    server.close();
    process.exit(code === 0 ? 0 : 1);
  });
});
