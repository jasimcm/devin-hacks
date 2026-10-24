// Easy Bill WhatsApp sender.
// Links a WhatsApp account like WhatsApp Web does (open http://localhost:3001 and scan the QR),
// then sends bills to customers when the Python server asks it to.
//
// This uses Baileys, an UNOFFICIAL WhatsApp Web library. It is against WhatsApp's terms and
// WhatsApp may ban the number, so link a spare SIM, not the shop's main number.
// It only listens on 127.0.0.1, so the Cloudflare tunnel does not expose it.
import fs from "node:fs";
import http from "node:http";
import makeWASocket, { Browsers, DisconnectReason, useMultiFileAuthState } from "baileys";
import pino from "pino";
import QRCode from "qrcode";

const PORT = Number(process.env.PORT || 3001);
const AUTH_DIR = "auth"; // the linked session; delete it to link another phone

let sock = null;
let qr = null; // QR text while waiting to be linked
let connected = false;
let linkedAs = null;

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  sock = makeWASocket({
    auth: state,
    logger: pino({ level: "warn" }),
    browser: Browsers.macOS("Easy Bill"),
  });
  sock.ev.on("creds.update", saveCreds);
  sock.ev.on("connection.update", ({ connection, lastDisconnect, qr: newQr }) => {
    if (newQr) {
      qr = newQr;
      console.log(`Open http://localhost:${PORT} and scan the QR with WhatsApp > Linked devices.`);
    }
    if (connection === "open") {
      connected = true;
      qr = null;
      linkedAs = sock.user?.id?.split(":")[0]?.split("@")[0] || null;
      console.log(`WhatsApp linked as +${linkedAs}. Ready to send bills.`);
    }
    if (connection === "close") {
      connected = false;
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        console.log("Unlinked from the phone. Showing a new QR...");
        fs.rmSync(AUTH_DIR, { recursive: true, force: true });
      }
      setTimeout(connect, 2000); // reconnect (also needed once right after the first scan)
    }
  });
}

async function sendBill({ phone, text, pdf_base64, filename }) {
  if (!connected) throw httpError(503, "WhatsApp is not linked");
  const [result] = (await sock.onWhatsApp(phone)) || [];
  if (!result?.exists) throw httpError(404, "This number is not on WhatsApp");
  await sock.sendMessage(result.jid, {
    document: Buffer.from(pdf_base64, "base64"),
    mimetype: "application/pdf",
    fileName: filename,
    caption: text,
  });
}

function httpError(status, message) {
  return Object.assign(new Error(message), { status });
}

// ---------------------------------------------------------------- HTTP API for the Python server

async function readJson(request) {
  let body = "";
  for await (const chunk of request) body += chunk;
  return JSON.parse(body || "{}");
}

function reply(response, status, data, type = "application/json") {
  response.writeHead(status, { "Content-Type": type });
  response.end(type === "application/json" ? JSON.stringify(data) : data);
}

async function linkPage() {
  const status = connected
    ? `<h2>✅ Linked as +${linkedAs}</h2><p>Bills will be sent from this WhatsApp. You can close this page.</p>`
    : qr
      ? `<h2>Scan with the spare phone</h2>
         <p>WhatsApp → Settings → Linked devices → Link a device</p>
         <img src="${await QRCode.toDataURL(qr, { width: 360 })}" alt="WhatsApp QR">`
      : "<h2>Connecting…</h2>";
  return `<!doctype html><html><head><meta charset="utf-8"><title>Easy Bill WhatsApp</title>
    <meta http-equiv="refresh" content="3">
    <style>body{font-family:system-ui;text-align:center;padding:40px;background:#f4f1ea;color:#111}
    h2{color:#0b6e4f}</style></head><body><h1>Easy Bill · WhatsApp sender</h1>${status}
    <p><small>Unofficial WhatsApp Web link. Use a spare number.</small></p></body></html>`;
}

http
  .createServer(async (request, response) => {
    try {
      if (request.method === "GET" && request.url === "/") {
        reply(response, 200, await linkPage(), "text/html; charset=utf-8");
      } else if (request.method === "GET" && request.url === "/status") {
        reply(response, 200, { connected, waiting_for_scan: Boolean(qr), linked_as: linkedAs });
      } else if (request.method === "POST" && request.url === "/send") {
        await sendBill(await readJson(request));
        reply(response, 200, { sent: true });
      } else {
        reply(response, 404, { error: "Not found" });
      }
    } catch (error) {
      console.error("Send failed:", error.message);
      reply(response, error.status || 500, { error: error.message });
    }
  })
  .listen(PORT, "127.0.0.1", () => console.log(`WhatsApp sender on http://localhost:${PORT}`));

connect();
