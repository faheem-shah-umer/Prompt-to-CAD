// Optional local browser check: Node 22+ and an existing Chrome/Edge installation.
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, mkdirSync, mkdtempSync } from 'node:fs';
import { resolve, join, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const output = join(root, 'artifacts/website-review');
mkdirSync(output, { recursive: true });
const browser = process.env.CAD_BROWSER || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
].find(existsSync);
if (!browser) throw new Error('Set CAD_BROWSER to an existing Chrome/Edge executable. No browser is downloaded.');
const mime = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.png': 'image/png' };
const server = createServer((request, response) => {
  const path = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
  const name = path.slice('/Prompt-to-CAD/'.length) || 'index.html';
  if (!path.startsWith('/Prompt-to-CAD/') || name.includes('..')) { response.writeHead(404).end(); return; }
  const file = join(root, 'site', name);
  if (!existsSync(file)) { response.writeHead(404).end(); return; }
  response.writeHead(200, { 'Content-Type': mime[extname(file)] || 'application/octet-stream' }).end(readFileSync(file));
});
await new Promise(done => server.listen(0, '127.0.0.1', done));
const url = `http://127.0.0.1:${server.address().port}/Prompt-to-CAD/`;
const temporary = join(root, 'tmp');
mkdirSync(temporary, { recursive: true });
const profile = mkdtempSync(join(temporary, 'website-browser-'));
const child = spawn(browser, ['--headless=new', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { windowsHide: true, stdio: 'ignore' });
const delay = ms => new Promise(done => setTimeout(done, ms));
let socket;
try {
  const portFile = join(profile, 'DevToolsActivePort');
  for (let attempt = 0; !existsSync(portFile) && attempt < 100; attempt++) await delay(100);
  if (!existsSync(portFile)) throw new Error('Browser did not start its local debugging endpoint.');
  const port = readFileSync(portFile, 'utf8').split('\n')[0];
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
  await new Promise((done, fail) => { socket.onopen = done; socket.onerror = fail; });
  let id = 0;
  const pending = new Map();
  const errors = [];
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const callback = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) callback?.reject(new Error(JSON.stringify(message.error)));
      else callback?.resolve(message.result);
    } else if (message.method === 'Runtime.exceptionThrown') errors.push('JavaScript exception');
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const request = ++id;
    pending.set(request, { resolve, reject });
    socket.send(JSON.stringify({ id: request, method, params }));
    setTimeout(() => { if (pending.delete(request)) reject(new Error(`Timeout: ${method}`)); }, 20000).unref();
  });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error('Browser evaluation failed');
    return result.result.value;
  };
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Page.navigate', { url });
  await evaluate('new Promise(done => document.readyState === "complete" ? done() : window.addEventListener("load", done, {once:true}))');
  const results = [];
  for (const width of [320, 390, 768, 1024, 1440, 1920]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 1000, deviceScaleFactor: 1, mobile: width < 700 });
    await delay(100);
    const metrics = await evaluate(`(() => {
      const visible = [...document.querySelectorAll('body *')].filter(e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
      const text = visible.filter(e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()));
      const overflows = visible.filter(e => !e.classList.contains('skip') && (e.getBoundingClientRect().right > innerWidth + 1 || e.getBoundingClientRect().left < -1)).map(e => e.tagName + '.' + e.className);
      const rgb = value => (value.match(/[\\d.]+/g) || []).map(Number);
      const luminance = c => c.slice(0,3).map(v => {v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
      const contrast = e => {let p=e;let bg;while(p){const color=rgb(getComputedStyle(p).backgroundColor);if(color.length===3 || color[3]===1){bg=color;break;}p=p.parentElement;}if(!bg)return 21;const a=luminance(rgb(getComputedStyle(e).color)),b=luminance(bg);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);};
      const contrastFailures = text.filter(e => {const s=getComputedStyle(e);const large=parseFloat(s.fontSize)>=24 || (parseFloat(s.fontSize)>=18.66 && parseInt(s.fontWeight)>=700);return contrast(e)<(large?3:4.5);}).map(e=>({element:e.tagName+'.'+e.className,ratio:+contrast(e).toFixed(2)}));
      return {width:innerWidth,scrollWidth:document.documentElement.scrollWidth,minText:Math.min(...text.map(e=>parseFloat(getComputedStyle(e).fontSize))),overflows,contrastFailures,images:[...document.images].every(i=>i.complete&&i.naturalWidth>0),alt:[...document.images].every(i=>i.hasAttribute('alt'))};
    })()`);
    results.push(metrics);
    if ([390, 1440].includes(width)) {
      const layout = await send('Page.getLayoutMetrics');
      const capture = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true,
        clip: { x: 0, y: 0, width, height: layout.cssContentSize.height, scale: 1 } });
      writeFileSync(join(output, `website-${width}.png`), Buffer.from(capture.data, 'base64'));
    }
  }
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url });
  await evaluate('new Promise(done => document.readyState === "complete" ? done() : window.addEventListener("load", done, {once:true}))');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  const keyboard = await evaluate('document.activeElement.classList.contains("skip")');
  await evaluate('document.querySelector("[data-screenshot=light]").focus()');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r', unmodifiedText: '\r' });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
  await delay(100);
  const theme = await evaluate('document.querySelector("[data-screenshot=light]").getAttribute("aria-pressed") === "true" && document.querySelector("#workspace-image").getAttribute("src").endsWith("workspace-light.png")');
  const passed = keyboard && theme && !errors.length && results.every(r => r.images && r.alt && r.scrollWidth <= r.width && r.minText >= 12 && !r.overflows.length && !r.contrastFailures.length);
  const report = { passed, projectSubpath: true, widths: results, keyboardSkipLink: keyboard, keyboardThemeToggle: theme, scriptErrors: errors.length, physicalPhone: false, independentReview: false };
  writeFileSync(join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
  if (!passed) process.exitCode = 1;
} finally {
  socket?.close();
  child.kill();
  server.close();
}
