'use strict';

/**
 * DeepSeek Agent Bridge — мост между CLI-агентом и VS Code.
 *
 * Расширение поднимает локальный HTTP-сервер на 127.0.0.1 и записывает порт с
 * токеном доступа в <workspace>/.agent-cache/vscode-bridge.json. Агент (Python,
 * tools/vscode.py) читает этот файл и отправляет JSON-команды:
 *
 *   open      — открыть файл в новой вкладке и поставить курсор на строку;
 *   close     — закрыть вкладку файла (или последнюю вкладку, открытую агентом);
 *   closeAll  — закрыть все вкладки, открытые агентом;
 *   reveal    — показать файл в проводнике;
 *   diff      — открыть дифф «старая версия ↔ текущая»;
 *   highlight — подсветить диапазон строк;
 *   ping      — проверка связи.
 *
 * Сервер слушает только localhost и требует токен, поэтому не торчит наружу.
 */

const vscode = require('vscode');
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const BRIDGE_DIR = '.agent-cache';
const BRIDGE_FILE = 'vscode-bridge.json';
const VERSION = '0.1.0';
const MAX_BODY = 2 * 1024 * 1024; // защита от мусорных запросов

/** @type {http.Server|null} */
let server = null;
let token = '';
let bridgeFilePath = null;
/** @type {vscode.StatusBarItem|null} */
let statusBar = null;
/** @type {vscode.OutputChannel|null} */
let output = null;
/** Вкладки, открытые агентом (uri.toString()). */
const agentTabs = new Set();
/** Подсветки по файлам: uri.toString() -> TextEditorDecorationType. */
const highlights = new Map();

// ---------------------------------------------------------------------------
// Активация / деактивация
// ---------------------------------------------------------------------------

function log(line) {
  if (output) {
    output.appendLine(`[${new Date().toLocaleTimeString()}] ${line}`);
  }
}

function activate(context) {
  output = vscode.window.createOutputChannel('DeepSeek Agent Bridge');

  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBar.command = 'deepseekAgent.showStatus';
  statusBar.text = '$(radio-tower) DeepSeek: мост';
  statusBar.tooltip = 'DeepSeek Agent Bridge';
  statusBar.show();

  context.subscriptions.push(
    output,
    statusBar,
    vscode.commands.registerCommand('deepseekAgent.showStatus', showStatus),
    vscode.commands.registerCommand('deepseekAgent.closeAgentTabs', async () => {
      const result = await cmdCloseAll();
      vscode.window.showInformationMessage(
        `DeepSeek Agent: закрыто вкладок — ${result.closed}`
      );
    }),
    vscode.commands.registerCommand('deepseekAgent.restartBridge', () => {
      startBridge();
      vscode.window.showInformationMessage('DeepSeek Agent: мост перезапущен');
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(() => startBridge()),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('deepseekAgent')) {
        startBridge();
      }
    })
  );

  startBridge();
}

function deactivate() {
  stopBridge();
}

// ---------------------------------------------------------------------------
// Жизненный цикл сервера
// ---------------------------------------------------------------------------

function workspaceRoot() {
  const folders = vscode.workspace.workspaceFolders;
  if (folders && folders.length) {
    return folders[0].uri.fsPath;
  }
  return process.cwd();
}

function config() {
  return vscode.workspace.getConfiguration('deepseekAgent');
}

async function startBridge() {
  stopBridge();

  const host = config().get('host', '127.0.0.1') || '127.0.0.1';
  const wantPort = Number(config().get('port', 0)) || 0;

  token = crypto.randomBytes(24).toString('hex');
  server = http.createServer(handleRequest);

  try {
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(wantPort, host, resolve);
    });
  } catch (err) {
    server = null;
    setStatus('мост не запущен');
    vscode.window.showErrorMessage(
      `DeepSeek Agent Bridge: не удалось запустить мост (${err.message}). ` +
      'Занят порт? Укажите другой в настройке deepseekAgent.port.'
    );
    return;
  }

  const port = server.address().port;
  if (!writeBridgeFile(host, port)) {
    return;
  }
  setStatus('мост активен');
  log(`мост запущен: http://${host}:${port}, дескриптор ${bridgeFilePath}`);
}

function stopBridge() {
  if (server) {
    try {
      server.close();
    } catch (_) { /* ignore */ }
    server = null;
  }
  if (bridgeFilePath) {
    try {
      fs.unlinkSync(bridgeFilePath);
    } catch (_) { /* файла уже нет — это нормально */ }
    bridgeFilePath = null;
  }
}

function writeBridgeFile(host, port) {
  const dir = path.join(workspaceRoot(), BRIDGE_DIR);
  bridgeFilePath = path.join(dir, BRIDGE_FILE);

  const info = {
    port,
    host,
    token,
    pid: process.pid,
    workspace: workspaceRoot(),
    extension: 'deepseek-agent-bridge',
    version: VERSION,
    started: new Date().toISOString(),
  };

  try {
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(bridgeFilePath, JSON.stringify(info, null, 2), 'utf8');
    return true;
  } catch (err) {
    bridgeFilePath = null;
    setStatus('нет доступа к .agent-cache');
    vscode.window.showErrorMessage(
      `DeepSeek Agent Bridge: не удалось создать ${BRIDGE_FILE} (${err.message}). ` +
      'Агент не увидит мост.'
    );
    return false;
  }
}

// ---------------------------------------------------------------------------
// HTTP: приём команд
// ---------------------------------------------------------------------------

function handleRequest(req, res) {
  if (req.method !== 'POST') {
    return send(res, 405, { ok: false, error: 'поддерживается только POST' });
  }

  let body = '';
  req.on('data', (chunk) => {
    body += chunk;
    if (body.length > MAX_BODY) {
      req.destroy();
    }
  });

  req.on('end', async () => {
    let message;
    try {
      message = JSON.parse(body || '{}');
    } catch (_) {
      return send(res, 400, { ok: false, error: 'некорректный JSON' });
    }

    if (!token || message.token !== token) {
      return send(res, 403, { ok: false, error: 'неверный токен доступа' });
    }

    try {
      const result = await dispatch(String(message.command || ''), message.args || {});
      send(res, 200, { ok: true, result: result === undefined ? null : result });
    } catch (err) {
      send(res, 200, { ok: false, error: err && err.message ? err.message : String(err) });
    }
  });
}

function send(res, code, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(code, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

async function dispatch(command, args) {
  log(`команда: ${command} ${JSON.stringify(args)}`);
  switch (command) {
    case 'ping':
      return { pong: true, version: VERSION, workspace: workspaceRoot() };
    case 'open':
      return await cmdOpen(args);
    case 'close':
      return await cmdClose(args);
    case 'closeAll':
      return await cmdCloseAll();
    case 'reveal':
      return await cmdReveal(args);
    case 'diff':
      return await cmdDiff(args);
    case 'highlight':
      return await cmdHighlight(args);
    default:
      throw new Error(`неизвестная команда: ${command}`);
  }
}

// ---------------------------------------------------------------------------
// Вспомогательные функции: пути и вкладки
// ---------------------------------------------------------------------------

function toUri(p) {
  if (!p) {
    throw new Error('не указан путь');
  }
  const abs = path.isAbsolute(p) ? p : path.join(workspaceRoot(), p);
  return vscode.Uri.file(path.normalize(abs));
}

/**
 * Сравнение путей. Windows и macOS по умолчанию используют регистронезависимую
 * файловую систему, Linux — регистрозависимую.
 */
function samePath(a, b) {
  const na = path.normalize(a);
  const nb = path.normalize(b);
  return process.platform === 'linux' ? na === nb : na.toLowerCase() === nb.toLowerCase();
}

function relPath(uri) {
  const rel = path.relative(workspaceRoot(), uri.fsPath);
  return (rel || path.basename(uri.fsPath)).split(path.sep).join('/');
}

function clamp(value, min, max) {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.min(Math.max(value, min), max);
}

/** Все URI, связанные с вкладкой (обычный текст, дифф и т.п.). */
function tabUris(input) {
  const out = [];
  if (!input) {
    return out;
  }
  if (input.uri) {
    out.push(input.uri);
  }
  if (input.original) {
    out.push(input.original);
  }
  if (input.modified) {
    out.push(input.modified);
  }
  return out;
}

async function closeTabByUri(uri) {
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      if (tabUris(tab.input).some((u) => samePath(u.fsPath, uri.fsPath))) {
        await vscode.window.tabGroups.close(tab, true);
        return true;
      }
    }
  }
  return false;
}

function setStatus(text) {
  if (!statusBar) {
    return;
  }
  statusBar.text = `$(radio-tower) ${text}`;
  statusBar.show();
}

// ---------------------------------------------------------------------------
// Команды
// ---------------------------------------------------------------------------

async function cmdOpen(args) {
  const uri = toUri(args.path);

  let stat;
  try {
    stat = fs.statSync(uri.fsPath);
  } catch (_) {
    throw new Error(`файл не найден: ${uri.fsPath}`);
  }
  if (stat.isDirectory()) {
    throw new Error('это папка, а не файл');
  }

  let doc;
  try {
    doc = await vscode.workspace.openTextDocument(uri);
  } catch (err) {
    throw new Error(`не удалось открыть файл (${err.message})`);
  }

  const editor = await vscode.window.showTextDocument(doc, {
    preview: Boolean(args.preview),
    preserveFocus: Boolean(args.preserve_focus),
  });

  const line = clamp(Number(args.line) || 1, 1, doc.lineCount || 1);
  const text = doc.lineAt(line - 1).text;
  const column = clamp(Number(args.column) || 1, 1, text.length + 1);
  const position = new vscode.Position(line - 1, column - 1);

  editor.selection = new vscode.Selection(position, position);
  editor.revealRange(
    new vscode.Range(position, position),
    vscode.TextEditorRevealType.InCenterIfOutsideViewport
  );

  const key = uri.toString();
  agentTabs.add(key);
  setStatus(`открыт ${relPath(uri)}:${line}`);

  return { path: relPath(uri), line };
}

async function cmdClose(args) {
  let uri = null;
  let label = 'последняя вкладка агента';

  if (args.path) {
    uri = toUri(args.path);
    label = relPath(uri);
  } else {
    const opened = Array.from(agentTabs);
    if (opened.length) {
      uri = vscode.Uri.parse(opened[opened.length - 1]);
      label = relPath(uri);
    }
  }

  if (!uri) {
    throw new Error('нет вкладок, открытых агентом');
  }

  const closed = await closeTabByUri(uri);
  if (!closed) {
    throw new Error(`вкладка не найдена: ${label}`);
  }

  agentTabs.delete(uri.toString());
  setStatus(`закрыт ${label}`);
  return { closed: 1, path: label };
}

async function cmdCloseAll() {
  let closed = 0;
  for (const key of Array.from(agentTabs)) {
    const uri = vscode.Uri.parse(key);
    if (await closeTabByUri(uri)) {
      closed += 1;
    }
    agentTabs.delete(key);
  }
  setStatus(closed ? `закрыто вкладок: ${closed}` : 'нечего закрывать');
  return { closed };
}

async function cmdReveal(args) {
  const uri = toUri(args.path);
  try {
    await vscode.commands.executeCommand('revealInExplorer', uri);
  } catch (err) {
    throw new Error(`не удалось показать в проводнике (${err.message})`);
  }
  setStatus(`в проводнике: ${relPath(uri)}`);
  return { path: relPath(uri) };
}

async function cmdDiff(args) {
  const right = toUri(args.path);
  const left = toUri(args.original || args.path);
  const title = args.title || `${relPath(left)} ↔ ${relPath(right)}`;

  try {
    await vscode.commands.executeCommand('vscode.diff', left, right, title);
  } catch (err) {
    throw new Error(`не удалось открыть дифф (${err.message})`);
  }
  setStatus(`дифф: ${title}`);
  return { title };
}

/**
 * Подсветка диапазона строк. Агент (tools/vscode.py) эту команду пока не
 * вызывает, но она часть протокола моста (см. README расширения): её может
 * отправить любой внешний клиент, который говорит с мостом напрямую.
 */
async function cmdHighlight(args) {
  const uri = toUri(args.path);
  const doc = await vscode.workspace.openTextDocument(uri);
  const editor = await vscode.window.showTextDocument(doc, { preview: false });

  const startLine = clamp(Number(args.start_line) || 1, 1, doc.lineCount || 1);
  const endLine = clamp(
    Number(args.end_line) || startLine,
    startLine,
    doc.lineCount || 1
  );

  const key = uri.toString();
  if (highlights.has(key)) {
    highlights.get(key).dispose();
  }

  const decoration = vscode.window.createTextEditorDecorationType({
    isWholeLine: true,
    backgroundColor: new vscode.ThemeColor('editor.findMatchHighlightBackground'),
    overviewRulerColor: new vscode.ThemeColor('editorOverviewRuler.findMatchForeground'),
    overviewRulerLane: vscode.OverviewRulerLane.Right,
  });
  highlights.set(key, decoration);

  const range = new vscode.Range(
    startLine - 1, 0,
    endLine - 1, doc.lineAt(endLine - 1).text.length
  );
  editor.setDecorations(decoration, [range]);
  editor.revealRange(range, vscode.TextEditorRevealType.InCenterIfOutsideViewport);

  setStatus(`подсвечено: ${relPath(uri)} (${startLine}-${endLine})`);
  return { start_line: startLine, end_line: endLine };
}

// ---------------------------------------------------------------------------
// Статус
// ---------------------------------------------------------------------------

function showStatus() {
  const address = server && server.address();
  const lines = [
    `Мост: ${address ? 'активен' : 'не запущен'}`,
    address ? `Адрес: http://${address.address}:${address.port}` : '',
    `Файл-дескриптор: ${bridgeFilePath || '—'}`,
    `Вкладок агента открыто: ${agentTabs.size}`,
    `Версия: ${VERSION}`,
  ].filter(Boolean);

  vscode.window.showInformationMessage(lines.join('\n'), { modal: true });
}

module.exports = { activate, deactivate };
