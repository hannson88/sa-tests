#!/usr/bin/env node
'use strict';

const fs = require('fs');
const https = require('https');
const path = require('path');

const configPath = path.resolve(process.argv[2] || '/opt/SentryAlert/config.js');
const bundlePath = path.resolve(process.argv[3] || '');

function request(options, parts) {
  return new Promise((resolve, reject) => {
    const req = https.request(options, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => { body += chunk; });
      response.on('end', () => {
        let parsed;
        try {
          parsed = JSON.parse(body);
        } catch {
          reject(new Error(`Telegram returned HTTP ${response.statusCode}`));
          return;
        }
        if (response.statusCode < 200 || response.statusCode >= 300 || !parsed.ok) {
          reject(new Error(parsed.description || `Telegram returned HTTP ${response.statusCode}`));
          return;
        }
        resolve(parsed.result);
      });
    });
    req.setTimeout(120000, () => req.destroy(new Error('Telegram request timed out')));
    req.on('error', reject);
    function writePart(index) {
      if (index >= parts.length) {
        req.end();
        return;
      }
      const part = parts[index];
      if (typeof part === 'string' || Buffer.isBuffer(part)) {
        req.write(part);
        writePart(index + 1);
      } else {
        part.pipe(req, { end: false });
        part.on('error', reject);
        part.on('end', () => writePart(index + 1));
      }
    }
    writePart(0);
  });
}

async function sendDocument(token, chatId) {
  const boundary = `----SentryAlertDiag${Date.now().toString(16)}`;
  const filename = path.basename(bundlePath).replace(/["\r\n]/g, '_');
  const prefix = Buffer.from(
    `--${boundary}\r\n` +
    'Content-Disposition: form-data; name="chat_id"\r\n\r\n' +
    `${chatId}\r\n` +
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="document"; filename="${filename}"\r\n` +
    'Content-Type: application/zip\r\n\r\n'
  );
  const suffix = Buffer.from(`\r\n--${boundary}--\r\n`);
  const contentLength = prefix.length + fs.statSync(bundlePath).size + suffix.length;
  await request(
    {
      hostname: 'api.telegram.org',
      method: 'POST',
      path: `/bot${token}/sendDocument`,
      headers: {
        'Content-Type': `multipart/form-data; boundary=${boundary}`,
        'Content-Length': contentLength,
      },
    },
    [prefix, fs.createReadStream(bundlePath), suffix]
  );
}

async function sendMessage(token, chatId) {
  const body = new URLSearchParams({
    chat_id: String(chatId),
    text: 'SentryAlert USB diagnostics have completed. Please forward the ZIP file above to SentryAlert Support.',
  }).toString();
  await request(
    {
      hostname: 'api.telegram.org',
      method: 'POST',
      path: `/bot${token}/sendMessage`,
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Content-Length': Buffer.byteLength(body),
      },
    },
    [body]
  );
}

async function main() {
  if (!fs.statSync(bundlePath).isFile()) {
    throw new Error('Diagnostic bundle does not exist');
  }
  const config = require(configPath);
  const token = String(config.telegramAPIToken || '');
  const chatId = String(config.telegramChatID || '');
  if (!token || !chatId) {
    throw new Error('SentryAlert Telegram token or chat ID is not configured');
  }
  await sendDocument(token, chatId);
  await sendMessage(token, chatId);
  process.stdout.write('Diagnostic bundle and completion message sent.\n');
}

main().catch((error) => {
  process.stderr.write(`Telegram delivery failed: ${error.message}\n`);
  process.exitCode = 1;
});
